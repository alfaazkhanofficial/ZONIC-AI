export function elapsed(startIso: string, endIso: string | null, now = Date.now()): string {
  const start = Date.parse(startIso);
  const end = endIso ? Date.parse(endIso) : now;
  const s = Math.max(0, Math.round((end - start) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}
export const timeOf = (iso: string): string => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const dateTimeOf = (iso: string): string => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
export const pretty = (s: string): string => s.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
