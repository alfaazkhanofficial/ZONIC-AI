import path from "path";

export interface LaunchInput {
  packaged: boolean;
  resourcesPath: string;
  repoRoot: string;
  platform: NodeJS.Platform;
  env: NodeJS.ProcessEnv;
  exists: (p: string) => boolean;
}
export type LaunchResult = { command: string; args: string[]; cwd: string } | { error: string };

/** Decide how to start the Python backend. Packaged builds run the frozen executable; dev runs the venv interpreter. */
export function resolveBackendLaunch(i: LaunchInput): LaunchResult {
  const backendDir = path.join(i.repoRoot, "backend");
  if (i.env.ZONIC_PYTHON) {
    return i.exists(i.env.ZONIC_PYTHON)
      ? { command: i.env.ZONIC_PYTHON, args: ["-m", "app.main"], cwd: backendDir }
      : { error: `ZONIC_PYTHON points to a file that does not exist: ${i.env.ZONIC_PYTHON}` };
  }
  if (i.packaged) {
    const exe = path.join(i.resourcesPath, "backend", i.platform === "win32" ? "zonic-backend.exe" : "zonic-backend");
    return i.exists(exe)
      ? { command: exe, args: [], cwd: path.dirname(exe) }
      : { error: "The bundled backend is missing from this installation. Reinstall ZONIC M4." };
  }
  const py = i.platform === "win32" ? path.join(backendDir, ".venv", "Scripts", "python.exe") : path.join(backendDir, ".venv", "bin", "python");
  return i.exists(py)
    ? { command: py, args: ["-m", "app.main"], cwd: backendDir }
    : { error: "Backend virtual environment not found. Run scripts/setup.ps1 once, then start again." };
}
