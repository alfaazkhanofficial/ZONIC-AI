"""Tiny Chrome DevTools Protocol client used to drive the REAL Electron app in end-to-end tests."""
from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx
import websockets


class Page:
    def __init__(self, ws: Any):
        self.ws, self._id, self._pending, self.console_errors, self.exceptions = ws, 0, {}, [], []
        self._reader = asyncio.ensure_future(self._read())

    @classmethod
    async def attach(cls, port: int = 9333, timeout: float = 40) -> "Page":
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            try:
                targets = httpx.get(f"http://127.0.0.1:{port}/json", timeout=2).json()
                page = next(t for t in targets if t["type"] == "page")
                p = cls(await websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000))
                await p.send("Runtime.enable"); await p.send("Page.enable")
                return p
            except Exception:
                await asyncio.sleep(0.5)
        raise RuntimeError("could not attach to Electron's DevTools port")

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if "id" in m and m["id"] in self._pending:
                    self._pending.pop(m["id"]).set_result(m)
                elif m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] in ("error", "assert"):
                    self.console_errors.append(" ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"]))
                elif m.get("method") == "Runtime.exceptionThrown":
                    self.exceptions.append(m["params"]["exceptionDetails"].get("exception", {}).get("description", "exception"))
        except Exception:
            pass

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        fut = asyncio.get_event_loop().create_future()
        self._pending[self._id] = fut
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        res = await asyncio.wait_for(fut, 30)
        if "error" in res:
            raise RuntimeError(res["error"])
        return res["result"]

    async def js(self, expr: str) -> Any:
        r = await self.send("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "js error"))
        return r["result"].get("value")

    async def wait(self, expr: str, timeout: float = 15, what: str = "") -> Any:
        end = asyncio.get_event_loop().time() + timeout
        last = None
        while asyncio.get_event_loop().time() < end:
            try:
                last = await self.js(expr)
                if last:
                    return last
            except Exception as e:  # page may be navigating
                if "Object reference chain" in str(e):  # expression returned a DOM node => it exists
                    return True
                last = e
            await asyncio.sleep(0.25)
        raise TimeoutError(f"timed out waiting for {what or expr} (last={last!r})")

    async def text(self) -> str:
        return await self.js("document.body.innerText")

    async def click_text(self, text: str, tag: str = "button", exact: bool = True) -> None:
        ok = await self.js(f"""(() => {{ const t = {json.dumps(text)}; const el = [...document.querySelectorAll({json.dumps(tag)})].find(b => {{ const s = b.textContent.trim(); return {'s === t' if exact else 's.includes(t)'}; }});
          if (!el || el.disabled) return false; el.click(); return true; }})()""")
        if not ok:
            raise RuntimeError(f"no enabled <{tag}> with text {text!r}")

    async def set_value(self, selector: str, value: str) -> None:
        ok = await self.js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false;
          const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, {json.dumps(value)}); el.dispatchEvent(new Event('input', {{bubbles: true}})); return true; }})()""")
        if not ok:
            raise RuntimeError(f"no element {selector}")

    async def shot(self, path: str) -> None:
        r = await self.send("Page.captureScreenshot", {"format": "png"})
        open(path, "wb").write(base64.b64decode(r["data"]))

    async def close(self) -> None:
        self._reader.cancel()
        await self.ws.close()
