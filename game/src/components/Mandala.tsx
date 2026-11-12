/* Gold pen-line mandala, generated deterministically (no assets, no random). */

const TAU = Math.PI * 2;
const round2 = (value: number) => Math.round(value * 100) / 100;
const polar = (radius: number, angle: number): [number, number] => [
  radius * Math.cos(angle),
  radius * Math.sin(angle),
];

function petals(count: number, rIn: number, rOut: number, spreadK = 0.42, rot = 0): string {
  const step = TAU / count;
  const controlRadius = rIn + (rOut - rIn) * 0.62;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const angle = rot + i * step;
    const spread = step * spreadK;
    const [sx, sy] = polar(rIn, angle - spread);
    const [ex, ey] = polar(rIn, angle + spread);
    const [tx, ty] = polar(rOut, angle);
    const [c1x, c1y] = polar(controlRadius, angle - spread * 0.94);
    const [c2x, c2y] = polar(controlRadius, angle + spread * 0.94);
    d += `M${round2(sx)} ${round2(sy)}Q${round2(c1x)} ${round2(c1y)} ${round2(tx)} ${round2(ty)}Q${round2(c2x)} ${round2(c2y)} ${round2(ex)} ${round2(ey)}`;
  }
  return d;
}

function leaves(count: number, radius: number, length: number, width: number, rot = 0): string {
  const step = TAU / count;
  const half = length / 2;
  const w = width / 2;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const angle = rot + i * step;
    const [cx, cy] = polar(radius, angle);
    const tx = -Math.sin(angle);
    const ty = Math.cos(angle);
    const nx = Math.cos(angle);
    const ny = Math.sin(angle);
    d +=
      `M${round2(cx - tx * half)} ${round2(cy - ty * half)}` +
      `Q${round2(cx + nx * w + tx * half * 0.18)} ${round2(cy + ny * w + ty * half * 0.18)} ${round2(cx + tx * half)} ${round2(cy + ty * half)}` +
      `Q${round2(cx - nx * w + tx * half * 0.18)} ${round2(cy - ny * w + ty * half * 0.18)} ${round2(cx - tx * half)} ${round2(cy - ty * half)}`;
  }
  return d;
}

function scallops(radius: number, count: number): string {
  const step = TAU / count;
  const chord = 2 * radius * Math.sin(step / 2);
  const arc = chord * 0.58;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const [x0, y0] = polar(radius, i * step);
    const [x1, y1] = polar(radius, (i + 1) * step);
    d += `M${round2(x0)} ${round2(y0)}A${round2(arc)} ${round2(arc)} 0 0 1 ${round2(x1)} ${round2(y1)}`;
  }
  return d;
}

function radialTicks(count: number, r1: number, r2: number): string {
  const step = TAU / count;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const [x1, y1] = polar(r1, i * step);
    const [x2, y2] = polar(r2, i * step);
    d += `M${round2(x1)} ${round2(y1)}L${round2(x2)} ${round2(y2)}`;
  }
  return d;
}

function dotRing(radius: number, count: number): string {
  const step = TAU / count;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const [x, y] = polar(radius, i * step);
    d += `M${round2(x - 1.6)} ${round2(y)}a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0 -3.2 0`;
  }
  return d;
}

interface Stroke {
  d: string;
  width: number;
  opacity: number;
}

const STROKES: Stroke[] = [
  { d: scallops(456, 60), width: 1, opacity: 0.75 },
  { d: petals(60, 408, 440, 0.4), width: 0.9, opacity: 0.7 },
  { d: radialTicks(96, 372, 396), width: 0.9, opacity: 0.6 },
  { d: petals(24, 300, 362, 0.38), width: 1.3, opacity: 0.95 },
  { d: leaves(24, 272, 42, 20), width: 1, opacity: 0.8 },
  { d: leaves(12, 272, 30, 12, Math.PI / 24), width: 0.9, opacity: 0.5 },
  { d: petals(16, 128, 228, 0.36), width: 1.1, opacity: 0.9 },
  { d: petals(16, 128, 190, 0.3, Math.PI / 16), width: 0.8, opacity: 0.45 },
  { d: petals(8, 46, 118, 0.4), width: 1.2, opacity: 0.95 },
  { d: dotRing(66, 30), width: 1, opacity: 0.7 },
];

const RINGS: Stroke[] = [
  { d: "M444 0a444 444 0 1 0 0 0", width: 1.2, opacity: 0.9 },
  { d: "M400 0a400 400 0 1 0 0 0", width: 0.9, opacity: 0.65 },
  { d: "M366 0a366 366 0 1 0 0 0", width: 0.8, opacity: 0.5 },
  { d: "M296 0a296 296 0 1 0 0 0", width: 1, opacity: 0.75 },
  { d: "M244 0a244 244 0 1 0 0 0", width: 1.2, opacity: 0.85 },
  { d: "M122 0a122 122 0 1 0 0 0", width: 1, opacity: 0.7 },
  { d: "M42 0a42 42 0 1 0 0 0", width: 1.1, opacity: 0.8 },
  { d: "M24 0a24 24 0 1 0 0 0", width: 1.3, opacity: 1 },
  { d: "M5 0a5 5 0 1 0 0 0", width: 1.4, opacity: 1 },
];

export function Mandala({ rotation = 0 }: { rotation?: number }) {
  return (
    <svg
      viewBox="-500 -500 1000 1000"
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      focusable="false"
      style={{ transform: `rotate(${rotation}deg)` }}
    >
      <circle
        r="496"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray="0.1 12"
        opacity="0.35"
      />
      <circle r="236" strokeWidth="3" strokeLinecap="round" strokeDasharray="0.1 7" opacity="0.5" />
      {RINGS.map((ring) => (
        <path key={ring.d} d={ring.d} strokeWidth={ring.width} opacity={ring.opacity} />
      ))}
      {STROKES.map((stroke) => (
        <path key={stroke.d} d={stroke.d} strokeWidth={stroke.width} opacity={stroke.opacity} />
      ))}
    </svg>
  );
}

export function Ornaments() {
  return (
    <div className="ornament-layer" aria-hidden="true">
      <div className="mandala mandala-tl">
        <Mandala />
      </div>
      <div className="mandala mandala-br">
        <Mandala rotation={18} />
      </div>
    </div>
  );
}

export function CornerFlourish() {
  return (
    <svg viewBox="0 0 72 72" fill="none" stroke="currentColor" aria-hidden="true">
      <path d="M4 68V28Q4 4 28 4h40" strokeWidth="1.1" />
      <path d="M13 68V34Q13 13 34 13h38" strokeWidth="1" opacity="0.45" />
      <path d="M26 20q12-7 21 3" strokeWidth="1" opacity="0.6" />
      <path d="M20 30q7 7 1 14" strokeWidth="1" opacity="0.45" />
      <circle cx="13" cy="13" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function LotusMark() {
  return (
    <svg viewBox="0 0 44 24" fill="none" stroke="currentColor" className="h-4 w-8" aria-hidden="true">
      <path d="M22 4l6 8-6 8-6-8 6-8Z" strokeWidth="1" />
      <path d="M11 12q6-6 10 0-4 6-10 0Z" strokeWidth="1" opacity="0.65" />
      <path d="M33 12q-6-6-10 0 4 6 10 0Z" strokeWidth="1" opacity="0.65" />
      <circle cx="22" cy="12" r="1.3" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function StrikeMark({ on }: { on: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      className={on ? "strike is-on" : "strike"}
      aria-hidden="true"
    >
      <path d="M5 5l14 14M19 5L5 19" strokeWidth="1.7" />
    </svg>
  );
}
