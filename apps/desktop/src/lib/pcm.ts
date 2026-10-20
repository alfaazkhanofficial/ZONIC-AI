/** Audio helpers for the voice pipeline: capture is mono PCM16 @16 kHz, playback is mono PCM16 @24 kHz (Gemini Live formats). */
export function downsample(input: Float32Array, inRate: number, outRate: number): Float32Array {
  if (outRate >= inRate) return input;
  const ratio = inRate / outRate;
  const len = Math.floor(input.length / ratio);
  const out = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    const start = Math.floor(i * ratio), end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = sum / Math.max(1, end - start); // box filter: cheap anti-aliasing
  }
  return out;
}
export function floatToInt16(f: Float32Array): Int16Array {
  const out = new Int16Array(f.length);
  for (let i = 0; i < f.length; i++) { const s = Math.max(-1, Math.min(1, f[i])); out[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
  return out;
}
export function int16ToFloat(b: Int16Array): Float32Array {
  const out = new Float32Array(b.length);
  for (let i = 0; i < b.length; i++) out[i] = b[i] / (b[i] < 0 ? 0x8000 : 0x7fff);
  return out;
}
export function rms(f: Float32Array): number {
  if (!f.length) return 0;
  let s = 0;
  for (let i = 0; i < f.length; i++) s += f[i] * f[i];
  return Math.sqrt(s / f.length);
}
/** Map raw RMS (~0..0.3 for speech) to a 0..1 visual level. */
export const toLevel = (r: number): number => Math.min(1, Math.sqrt(r) * 1.8);
