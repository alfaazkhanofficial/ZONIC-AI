import { downsample, floatToInt16, int16ToFloat, rms, toLevel } from "./pcm";
import type { Connection, VoiceState } from "./types";

/** Live audio levels for the avatar. Mutated ~30x/s and read inside the render loop, so React never re-renders for it. */
export const audioLevel = { mic: 0, out: 0 };

export interface VoiceHandlers {
  onState(state: VoiceState, detail: string | null, code: string | null): void;
  onTranscript(role: "user" | "assistant", text: string): void;
}
export interface VoiceDevices { inputId?: string; outputId?: string }

const OUT_RATE = 24000, IN_RATE = 16000;

export class VoiceClient {
  private ws: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private inCtx: AudioContext | null = null;
  private outCtx: AudioContext | null = null;
  private proc: ScriptProcessorNode | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private active = false;
  private levelTimer: number | null = null;

  constructor(private conn: Connection, private h: VoiceHandlers) {}

  get running(): boolean { return this.active; }

  async start(dev: VoiceDevices = {}): Promise<void> {
    if (this.active) return;
    this.active = true;
    this.h.onState("connecting", "Requesting microphone…", null);
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: dev.inputId ? { exact: dev.inputId } : undefined, echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    } catch (e) {
      this.active = false;
      const name = (e as DOMException).name;
      const msg = name === "NotAllowedError" ? "Microphone permission was denied. Allow it in Windows Settings → Privacy → Microphone, then try again."
        : name === "NotFoundError" ? "No microphone was found. Plug one in or pick another device in Settings → Voice." : `Could not open the microphone (${name}).`;
      this.h.onState("error", msg + " Text chat still works.", "microphone");
      return;
    }
    this.outCtx = new AudioContext({ sampleRate: OUT_RATE });
    if (dev.outputId && "setSinkId" in this.outCtx) { try { await (this.outCtx as AudioContext & { setSinkId(id: string): Promise<void> }).setSinkId(dev.outputId); } catch { /* keep default output */ } }
    this.inCtx = new AudioContext();
    const src = this.inCtx.createMediaStreamSource(this.stream);
    this.proc = this.inCtx.createScriptProcessor(4096, 1, 1); // deprecated but dependency-free and CSP-friendly; fine for 16 kHz speech
    const mute = this.inCtx.createGain();
    mute.gain.value = 0;
    src.connect(this.proc); this.proc.connect(mute); mute.connect(this.inCtx.destination);
    this.proc.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0);
      audioLevel.mic = toLevel(rms(data));
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(floatToInt16(downsample(data, this.inCtx!.sampleRate, IN_RATE)).buffer);
    };
    this.levelTimer = window.setInterval(() => { audioLevel.out *= 0.8; }, 50);

    const url = this.conn.baseUrl.replace(/^http/, "ws") + `/api/voice/ws?token=${encodeURIComponent(this.conn.token)}`;
    this.ws = new WebSocket(url);
    this.ws.binaryType = "arraybuffer";
    this.ws.onopen = () => this.ws!.send(JSON.stringify({ type: "start" }));
    this.ws.onmessage = (ev) => (typeof ev.data === "string" ? this.onControl(JSON.parse(ev.data)) : this.play(ev.data as ArrayBuffer));
    this.ws.onclose = () => { if (this.active) { this.h.onState("disconnected", "Voice connection closed. Text chat still works.", "closed"); void this.stop(false); } };
    this.ws.onerror = () => this.h.onState("error", "Could not reach the local voice service.", "ws");
  }

  private onControl(m: { type: string; state?: VoiceState; detail?: string | null; code?: string | null; role?: "user" | "assistant"; text?: string }): void {
    if (m.type === "state" && m.state) this.h.onState(m.state, m.detail ?? null, m.code ?? null);
    else if (m.type === "transcript" && m.role && m.text) this.h.onTranscript(m.role, m.text);
    else if (m.type === "clear_playback") this.clearPlayback();
  }

  private play(buf: ArrayBuffer): void {
    if (!this.outCtx) return;
    const f = int16ToFloat(new Int16Array(buf));
    audioLevel.out = Math.max(audioLevel.out, toLevel(rms(f)));
    const ab = this.outCtx.createBuffer(1, f.length, OUT_RATE);
    ab.copyToChannel(f, 0);
    const s = this.outCtx.createBufferSource();
    s.buffer = ab; s.connect(this.outCtx.destination);
    const t = Math.max(this.outCtx.currentTime + 0.02, this.nextTime);
    s.start(t); this.nextTime = t + ab.duration;
    this.sources.add(s); s.onended = () => this.sources.delete(s);
  }

  clearPlayback(): void {
    for (const s of this.sources) { try { s.stop(); } catch { /* already ended */ } }
    this.sources.clear(); this.nextTime = 0; audioLevel.out = 0;
  }

  interrupt(): void {
    this.clearPlayback();
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "interrupt" }));
  }

  async stop(notify = true): Promise<void> {
    const wasActive = this.active;
    this.active = false;
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "stop" }));
    this.ws?.close(); this.ws = null;
    if (this.levelTimer) { clearInterval(this.levelTimer); this.levelTimer = null; }
    this.clearPlayback();
    this.proc?.disconnect(); this.proc = null;
    this.stream?.getTracks().forEach((t) => t.stop()); this.stream = null;
    await this.inCtx?.close().catch(() => undefined); this.inCtx = null;
    await this.outCtx?.close().catch(() => undefined); this.outCtx = null;
    audioLevel.mic = 0; audioLevel.out = 0;
    if (wasActive && notify) this.h.onState("disconnected", "Voice session ended", null);
  }
}
