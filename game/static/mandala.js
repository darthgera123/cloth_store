/* Game Night — ornamental mandala generator.
   Draws concentric floral linework as thin gold strokes on transparent
   ground (UI-DESIGN §3). Geometry is deterministic: same input, same art.
   Coordinates are centred on 0,0 inside a -500..500 viewBox. */

const TAU = Math.PI * 2;
const r2 = (v) => Math.round(v * 100) / 100;
const polar = (r, a) => [r * Math.cos(a), r * Math.sin(a)];

function petals(count, rIn, rOut, spreadK = 0.42, rot = 0) {
  const step = TAU / count;
  const cR = rIn + (rOut - rIn) * 0.62;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const a = rot + i * step;
    const s = step * spreadK;
    const [sx, sy] = polar(rIn, a - s);
    const [ex, ey] = polar(rIn, a + s);
    const [tx, ty] = polar(rOut, a);
    const [c1x, c1y] = polar(cR, a - s * 0.94);
    const [c2x, c2y] = polar(cR, a + s * 0.94);
    d += `M${r2(sx)} ${r2(sy)}Q${r2(c1x)} ${r2(c1y)} ${r2(tx)} ${r2(ty)}Q${r2(c2x)} ${r2(c2y)} ${r2(ex)} ${r2(ey)}`;
  }
  return d;
}

function leaves(count, r, len, wid, rot = 0) {
  const step = TAU / count;
  const half = len / 2;
  const w = wid / 2;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const a = rot + i * step;
    const [cx, cy] = polar(r, a);
    const tx = -Math.sin(a);
    const ty = Math.cos(a);
    const nx = Math.cos(a);
    const ny = Math.sin(a);
    d +=
      `M${r2(cx - tx * half)} ${r2(cy - ty * half)}` +
      `Q${r2(cx + nx * w + tx * half * 0.18)} ${r2(cy + ny * w + ty * half * 0.18)} ${r2(cx + tx * half)} ${r2(cy + ty * half)}` +
      `Q${r2(cx - nx * w + tx * half * 0.18)} ${r2(cy - ny * w + ty * half * 0.18)} ${r2(cx - tx * half)} ${r2(cy - ty * half)}`;
  }
  return d;
}

function scallops(r, count, rot = 0) {
  const step = TAU / count;
  const chord = 2 * r * Math.sin(step / 2);
  const rad = chord * 0.58;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const a0 = rot + i * step;
    const a1 = a0 + step;
    const [x0, y0] = polar(r, a0);
    const [x1, y1] = polar(r, a1);
    d += `M${r2(x0)} ${r2(y0)}A${r2(rad)} ${r2(rad)} 0 0 1 ${r2(x1)} ${r2(y1)}`;
  }
  return d;
}

function ticks(count, r1, r2v, rot = 0) {
  const step = TAU / count;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const a = rot + i * step;
    const [x1, y1] = polar(r1, a);
    const [x2, y2] = polar(r2v, a);
    d += `M${r2(x1)} ${r2(y1)}L${r2(x2)} ${r2(y2)}`;
  }
  return d;
}

function dots(r, count, rot = 0) {
  const step = TAU / count;
  let d = "";
  for (let i = 0; i < count; i += 1) {
    const [x, y] = polar(r, rot + i * step);
    d += `M${r2(x - 1.6)} ${r2(y)}a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0 -3.2 0`;
  }
  return d;
}

export function mandalaMarkup() {
  const stroke = (d, width, opacity) =>
    `<path d="${d}" stroke-width="${width}" opacity="${opacity}"/>`;
  const ring = (r, width = 1, opacity = 1) =>
    `<circle r="${r}" stroke-width="${width}" opacity="${opacity}"/>`;

  return [
    // outer dotted halo
    `<circle r="496" stroke-width="3" stroke-linecap="round" stroke-dasharray="0.1 12" opacity="0.35"/>`,
    // scalloped rim
    stroke(scallops(456, 60), 1, 0.75),
    ring(444, 1.2, 0.9),
    stroke(petals(60, 408, 440, 0.4), 0.9, 0.7),
    ring(400, 0.9, 0.65),
    stroke(ticks(96, 372, 396), 0.9, 0.6),
    ring(366, 0.8, 0.5),
    // main lotus ring
    stroke(petals(24, 300, 362, 0.38), 1.3, 0.95),
    ring(296, 1, 0.75),
    // paisley leaf ring
    stroke(leaves(24, 272, 42, 20), 1, 0.8),
    stroke(leaves(12, 272, 30, 12, Math.PI / 24), 0.9, 0.5),
    ring(244, 1.2, 0.85),
    `<circle r="236" stroke-width="3" stroke-linecap="round" stroke-dasharray="0.1 7" opacity="0.5"/>`,
    // rosette
    stroke(petals(16, 128, 228, 0.36), 1.1, 0.9),
    ring(122, 1, 0.7),
    stroke(petals(16, 128, 190, 0.3, Math.PI / 16), 0.8, 0.45),
    stroke(petals(8, 46, 118, 0.4), 1.2, 0.95),
    ring(42, 1.1, 0.8),
    stroke(dots(30, 66), 1, 0.7),
    ring(24, 1.3, 1),
    `<circle r="5" stroke-width="1.4" opacity="1"/>`,
  ].join("");
}

/** Replace the contents of `el` with a mandala drawn in currentColor. */
export function mountMandala(el, { rotation = 0, opacity = 1 } = {}) {
  el.innerHTML =
    `<svg viewBox="-500 -500 1000 1000" fill="none" stroke="currentColor" ` +
    `aria-hidden="true" focusable="false">${mandalaMarkup()}</svg>`;
  el.style.setProperty("--rot", `${rotation}deg`);
  el.style.opacity = String(opacity);
  return el;
}
