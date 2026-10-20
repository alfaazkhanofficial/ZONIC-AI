/** Pure security configuration so it can be unit-tested without launching Electron. */
export interface WebPrefsInput {
  preload: string;
  packaged: boolean;
}

export function webPreferences({ preload, packaged }: WebPrefsInput) {
  return {
    preload,
    contextIsolation: true, // renderer cannot reach preload/Node globals
    nodeIntegration: false, // no require() in the renderer
    nodeIntegrationInWorker: false,
    nodeIntegrationInSubFrames: false,
    sandbox: true,
    webSecurity: true,
    allowRunningInsecureContent: false,
    experimentalFeatures: false,
    webviewTag: false,
    spellcheck: false,
    devTools: !packaged,
  } as const;
}

/** Only the microphone is ever granted (needed for voice). Camera, geolocation, notifications etc. are denied. */
export const ALLOWED_PERMISSIONS: ReadonlySet<string> = new Set(["media"]);
export const isAllowedPermission = (p: string): boolean => ALLOWED_PERMISSIONS.has(p);

export interface TrustContext {
  devUrl: string | null;
  distFileUrlPrefix: string; // e.g. file:///C:/Program%20Files/ZONIC%20M4/resources/app/dist/
}

export function isTrustedUrl(url: string, ctx: TrustContext): boolean {
  if (!url) return false;
  if (ctx.devUrl && (url === ctx.devUrl || url.startsWith(ctx.devUrl + "/"))) return true;
  return url.startsWith(ctx.distFileUrlPrefix);
}
