import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { PROFILES, STATE_GLYPH, webglAvailable, type AvatarState } from "../lib/avatar";
import { audioLevel } from "../lib/voice";

const RINGS = [
  { r: 1.55, tilt: [1.1, 0.2], speed: 1.0 }, { r: 1.85, tilt: [0.4, 1.0], speed: -0.7 },
  { r: 2.15, tilt: [1.4, -0.5], speed: 0.5 }, { r: 2.45, tilt: [0.2, 0.3], speed: -0.35 },
] as const;

function radialTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, "rgba(255,255,255,0.9)"); grd.addColorStop(0.35, "rgba(255,255,255,0.25)"); grd.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

function Scene({ state, intensity, animate }: { state: AvatarState; intensity: number; animate: boolean }) {
  const invalidate = useThree((s) => s.invalidate);
  const root = useRef<THREE.Group>(null), shell = useRef<THREE.Mesh>(null), inner = useRef<THREE.Mesh>(null), core = useRef<THREE.Mesh>(null);
  const rings = useRef<THREE.Group>(null), pts = useRef<THREE.Points>(null), halo = useRef<THREE.Sprite>(null), sat = useRef<THREE.Mesh>(null);
  const cur = useRef({ color: new THREE.Color(PROFILES[state].color), core: PROFILES[state].core, dim: PROFILES[state].dim });
  const target = useRef(new THREE.Color());
  const tex = useMemo(radialTexture, []);
  const particles = useMemo(() => {
    const n = 520, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, r = 1.9 + Math.random() * 1.1, s = Math.sqrt(1 - u * u);
      pos.set([r * s * Math.cos(th), r * u * 0.8, r * s * Math.sin(th)], i * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    return g;
  }, []);
  useEffect(() => () => { tex.dispose(); particles.dispose(); }, [tex, particles]);
  useEffect(() => { invalidate(); }, [state, intensity, animate, invalidate]);

  useFrame((st, dtRaw) => {
    const p = PROFILES[state], c = cur.current, k = intensity;
    const dt = animate ? Math.min(dtRaw, 0.05) : 1;
    const t = animate ? st.clock.elapsedTime : 0;
    const a = 1 - Math.exp(-dt * (animate ? 5 : 100));
    target.current.set(p.color);
    c.color.lerp(target.current, a); c.core += (p.core - c.core) * a; c.dim += (p.dim - c.dim) * a;
    const level = state === "speaking" ? audioLevel.out : state === "listening" ? audioLevel.mic : 0; // real audio amplitude only
    const breathe = animate ? Math.sin(t * p.pulseRate) * 0.5 + 0.5 : 0.5;
    const scale = 1 + (p.pulse * breathe + level * p.audioGain * 0.45) * k;
    if (animate) {
      if (root.current) root.current.rotation.y += dt * p.spin * k;
      if (shell.current) { shell.current.rotation.x += dt * p.spin * 0.7 * k; shell.current.rotation.z -= dt * p.spin * 0.4 * k; }
      if (inner.current) { inner.current.rotation.y -= dt * (p.spin * 1.6 + 0.05) * k; inner.current.rotation.x += dt * p.spin * 0.9 * k; }
      if (pts.current) pts.current.rotation.y += dt * (0.02 + p.particles) * k;
      rings.current?.children.forEach((g, i) => { g.rotation.z += dt * p.ring * RINGS[i].speed * k; });
    }
    core.current?.scale.setScalar(0.62 * scale);
    inner.current?.scale.setScalar(0.85 * scale);
    shell.current?.scale.setScalar(scale);
    const opacity = (o: number) => o * c.dim;
    const set = (m: THREE.Object3D | null, o: number) => { if (!m) return; const mat = (m as THREE.Mesh).material as THREE.Material & { color: THREE.Color; opacity: number }; mat.color.copy(c.color); mat.opacity = opacity(o); };
    set(core.current, 0.35 + c.core * 0.5); set(inner.current, 0.5); set(shell.current, 0.28);
    set(pts.current, 0.65);
    rings.current?.children.forEach((g) => { const m = (g.children[0] as THREE.Mesh).material as THREE.MeshBasicMaterial; m.color.copy(c.color); m.opacity = opacity(0.55); });
    if (halo.current) { const m = halo.current.material; m.color.copy(c.color); m.opacity = opacity(0.14 + c.core * 0.3 + level * 0.3); halo.current.scale.setScalar(5.2 * (1 + 0.04 * breathe)); }
    if (sat.current) { sat.current.visible = state === "executing"; (sat.current.material as THREE.MeshBasicMaterial).color.copy(c.color).lerp(new THREE.Color("#ffffff"), 0.4); }
  });

  return (
    <group ref={root} rotation={[0.35, 0, 0]}>
      <sprite ref={halo}><spriteMaterial map={tex} transparent depthWrite={false} blending={THREE.AdditiveBlending} /></sprite>
      <mesh ref={core}><sphereGeometry args={[1, 32, 32]} /><meshBasicMaterial transparent depthWrite={false} blending={THREE.AdditiveBlending} /></mesh>
      <mesh ref={inner}><icosahedronGeometry args={[1, 1]} /><meshBasicMaterial wireframe transparent depthWrite={false} /></mesh>
      <mesh ref={shell}><icosahedronGeometry args={[1.25, 2]} /><meshBasicMaterial wireframe transparent depthWrite={false} /></mesh>
      <group ref={rings}>
        {RINGS.map((r, i) => (
          <group key={i} rotation={[r.tilt[0], r.tilt[1], 0]}>
            <mesh><torusGeometry args={[r.r, 0.006, 8, 180]} /><meshBasicMaterial transparent depthWrite={false} blending={THREE.AdditiveBlending} /></mesh>
            {i === 0 && <mesh ref={sat} position={[r.r, 0, 0]} visible={false}><sphereGeometry args={[0.06, 12, 12]} /><meshBasicMaterial /></mesh>}
          </group>
        ))}
      </group>
      <points ref={pts} geometry={particles}><pointsMaterial size={0.022} transparent depthWrite={false} blending={THREE.AdditiveBlending} sizeAttenuation /></points>
    </group>
  );
}

function Fallback({ state }: { state: AvatarState }) {
  return <div className="avatar-fallback" style={{ ["--c" as string]: PROFILES[state].color }}><i aria-hidden /></div>;
}

interface Props { state: AvatarState; intensity: number; reduced: boolean }
export const Avatar = memo(function Avatar({ state, intensity, reduced }: Props) {
  const [webgl] = useState(webglAvailable);
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => {
    const f = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  const animate = visible && !reduced; // hidden window or reduced motion => one static frame, no render loop
  const p = PROFILES[state];
  return (
    <div className="avatar-box" role="img" aria-label={`ZONIC avatar. Current state: ${p.label}`} data-animating={String(animate)} data-renderer={webgl ? "webgl" : "fallback"} data-state={state}>
      {webgl ? (
        <Canvas frameloop={animate ? "always" : "demand"} dpr={[1, 1.5]} gl={{ antialias: true, alpha: true, powerPreference: "low-power" }} camera={{ position: [0, 0, 7.8], fov: 42 }}>
          <Scene state={state} intensity={Math.max(0.05, intensity)} animate={animate} />
        </Canvas>
      ) : <Fallback state={state} />}
    </div>
  );
});

export const StateLabel = ({ state }: { state: AvatarState }) => (
  <div className="state-label" aria-live="polite"><span className="dot" aria-hidden style={{ color: PROFILES[state].color }}>{STATE_GLYPH[state]}</span><span>{PROFILES[state].label}</span></div>
);
