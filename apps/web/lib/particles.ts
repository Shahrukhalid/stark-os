/**
 * Particle presence for the assistants: a glowing cloud that forms an abstract core, or a soft feminine or
 * masculine bust. Original artwork drawn from simple shapes (no likeness of any real person or character).
 *
 * States: idle (drift and twinkle), listening (gathers inward), thinking (sparks orbit), speaking (pulses from
 * the voice). Switching shape sends every particle on a swirling flight with a brief "signal" flicker.
 */

export type AvatarShape = "core" | "female" | "male";
export type AvatarState = "idle" | "listening" | "thinking" | "speaking";

export interface AvatarTheme {
  /** main colour, e.g. "#67e8f9" */
  color: string;
  /** accent for highlights and sparks */
  accent: string;
  /** "flow": wisps drift upward like smoke; "grid": particles snap to a faint lattice shimmer */
  energy: "flow" | "grid";
}

const W = 240; // design space; scaled to the canvas
const H = 280;
const COUNT = 5600;

interface Target {
  x: number;
  y: number;
  z: number;
  b: number; // brightness 0..1
  r: number; // size
}

function rand(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function hexRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Draw a silhouette mask (white = inside) for a bust shape. */
function drawMask(ctx: CanvasRenderingContext2D, shape: "female" | "male", layer: "body" | "hair" | "face") {
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#fff";
  const cx = W / 2;
  if (layer === "face") {
    // forehead, cheekbones, jaw and chin (narrower and softer for the feminine form, squarer for the masculine)
    const f = shape === "female";
    const top = f ? 60 : 56;
    const hw = f ? 33 : 37;
    const chin = f ? 150 : 152;
    ctx.beginPath();
    ctx.moveTo(cx, top);
    ctx.bezierCurveTo(cx + hw * 0.75, top, cx + hw, top + 22, cx + hw, top + 44);
    ctx.bezierCurveTo(cx + hw, top + 62, cx + hw * (f ? 0.8 : 0.92), chin - (f ? 22 : 16), cx + hw * (f ? 0.42 : 0.55), chin - 6);
    ctx.bezierCurveTo(cx + hw * 0.25, chin, cx - hw * 0.25, chin, cx - hw * (f ? 0.42 : 0.55), chin - 6);
    ctx.bezierCurveTo(cx - hw * (f ? 0.8 : 0.92), chin - (f ? 22 : 16), cx - hw, top + 62, cx - hw, top + 44);
    ctx.bezierCurveTo(cx - hw, top + 22, cx - hw * 0.75, top, cx, top);
    ctx.fill();
    return;
  }
  if (layer === "hair") {
    if (shape === "female") {
      // crown and long hair framing the face, falling past the shoulders
      ctx.beginPath();
      ctx.moveTo(cx - 44, 205);
      ctx.bezierCurveTo(cx - 70, 150, cx - 62, 60, cx - 34, 46);
      ctx.bezierCurveTo(cx - 12, 32, cx + 12, 32, cx + 34, 46);
      ctx.bezierCurveTo(cx + 62, 60, cx + 70, 150, cx + 44, 205);
      ctx.bezierCurveTo(cx + 30, 170, cx + 40, 120, cx + 30, 92);
      ctx.bezierCurveTo(cx + 20, 70, cx - 20, 70, cx - 30, 92);
      ctx.bezierCurveTo(cx - 40, 120, cx - 30, 170, cx - 44, 205);
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.moveTo(cx - 38, 96);
      ctx.bezierCurveTo(cx - 44, 60, cx - 22, 44, cx, 44);
      ctx.bezierCurveTo(cx + 22, 44, cx + 44, 60, cx + 38, 96);
      ctx.bezierCurveTo(cx + 30, 72, cx - 30, 72, cx - 38, 96);
      ctx.fill();
    }
    return;
  }
  // neck and shoulders
  const sw = shape === "female" ? 82 : 98;
  ctx.beginPath();
  ctx.moveTo(cx - 14, 140);
  ctx.lineTo(cx + 14, 140);
  ctx.lineTo(cx + 16, 172);
  ctx.bezierCurveTo(cx + 40, 182, cx + sw, 190, cx + sw + 8, 230);
  ctx.lineTo(cx + sw + 14, H);
  ctx.lineTo(cx - sw - 14, H);
  ctx.lineTo(cx - sw - 8, 230);
  ctx.bezierCurveTo(cx - sw, 190, cx - 40, 182, cx - 16, 172);
  ctx.closePath();
  ctx.fill();
}

function samplePoints(shape: "female" | "male", seed: number): Target[] {
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  const layers: { layer: "face" | "hair" | "body"; share: number; data?: Uint8ClampedArray }[] = [
    { layer: "face", share: shape === "female" ? 0.5 : 0.55 },
    { layer: "hair", share: shape === "female" ? 0.32 : 0.12 },
    { layer: "body", share: shape === "female" ? 0.18 : 0.33 },
  ];
  for (const l of layers) {
    drawMask(ctx, shape, l.layer);
    l.data = ctx.getImageData(0, 0, W, H).data;
  }
  const r = rand(seed);
  const fy = shape === "female" ? 104 : 103;
  const fw = shape === "female" ? 33 : 37;
  const fh = shape === "female" ? 46 : 48;
  const out: Target[] = [];
  for (const l of layers) {
    const goal = out.length + Math.round(COUNT * l.share);
    for (let tries = 0; out.length < goal && tries < COUNT * 400; tries++) {
      const x = r() * W;
      const y = r() * H;
      if (l.data![(Math.floor(y) * W + Math.floor(x)) * 4 + 3] < 128) continue;
      const dx = (x - W / 2) / fw;
      const dy = (y - fy) / fh;
      let b = 0.55;
      let z = 0;
      if (l.layer === "face") {
        const zz = Math.sqrt(Math.max(0, 1 - dx * dx * 0.9 - dy * dy * 0.8));
        // soft hollows: eye sockets, under the nose, the line of the lips
        const eye = Math.min(Math.hypot((dx + 0.4) / 0.26, (dy + 0.1) / 0.13), Math.hypot((dx - 0.4) / 0.26, (dy + 0.1) / 0.13));
        if (eye < 1 && r() < 0.85 * (1 - eye * eye * 0.6)) continue;
        if (Math.hypot(dx / 0.34, (dy - 0.56) / 0.045) < 1 && r() < 0.7) continue;
        // relief: brow, nose bridge and tip, cheekbones, lips, chin
        const brow = Math.exp(-(((dy + 0.3) / 0.07) ** 2)) * Math.exp(-(((Math.abs(dx) - 0.38) / 0.3) ** 2));
        const nose = Math.exp(-((dx / 0.08) ** 2)) * Math.exp(-(((dy - 0.12) / 0.26) ** 2));
        const cheek = Math.exp(-(((Math.abs(dx) - 0.5) / 0.16) ** 2)) * Math.exp(-(((dy - 0.12) / 0.14) ** 2));
        const lips = Math.exp(-((dx / 0.28) ** 2)) * Math.exp(-(((dy - 0.58) / 0.07) ** 2));
        const chin = Math.exp(-((dx / 0.25) ** 2)) * Math.exp(-(((dy - 0.86) / 0.08) ** 2));
        z = (zz + nose * 0.35 + brow * 0.1 + cheek * 0.12) * 36;
        // light from the upper left and the front
        const nx = -dx * 0.9;
        const ny = -dy * 0.8;
        const diffuse = Math.max(0, (nx * -0.45 + ny * -0.5 + zz * 0.74) / Math.hypot(nx, ny, zz || 0.01));
        b = 0.25 + diffuse * 0.6 + brow * 0.25 + nose * 0.35 + cheek * 0.25 + lips * 0.2 + chin * 0.15;
      } else if (l.layer === "hair") {
        z = -6 + r() * 10;
        // flowing strands: brightness follows gentle waves down the hair
        const strand = 0.5 + 0.5 * Math.sin((x - W / 2) * 0.35 + y * 0.04);
        b = 0.3 + strand * 0.35 + (y < 70 ? 0.15 : 0);
      } else {
        const sx = (x - W / 2) / 110;
        z = Math.sqrt(Math.max(0, 1 - sx * sx)) * 18 - 8;
        const fade = Math.max(0, 1 - (y - 150) / (H - 150));
        const collar = Math.exp(-(((y - 186 - Math.abs(x - W / 2) * 0.1) / 5) ** 2)) * (Math.abs(x - W / 2) < 60 ? 1 : 0);
        if (r() > 0.25 + fade * 0.75) continue; // thins out toward the bottom
        b = 0.15 + fade * 0.4 + collar * 0.35;
      }
      out.push({ x, y, z, b: Math.min(1, b), r: l.layer === "face" ? 0.45 + r() * 0.8 : 0.4 + r() * 0.9 });
    }
  }
  while (out.length < COUNT) out.push({ ...out[Math.floor(r() * out.length)] });
  return out.slice(0, COUNT);
}

function corePoints(seed: number): Target[] {
  const r = rand(seed);
  const out: Target[] = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < COUNT; i++) {
    if (i < COUNT * 0.62) {
      // a glowing sphere, denser at its heart
      const k = i / (COUNT * 0.62);
      const yy = 1 - k * 2;
      const rad = Math.sqrt(1 - yy * yy);
      const th = golden * i;
      const depth = 0.55 + 0.45 * Math.pow(r(), 0.6);
      const R = 62 * depth;
      out.push({ x: W / 2 + Math.cos(th) * rad * R, y: 128 + yy * R, z: Math.sin(th) * rad * R, b: 0.45 + (1 - depth) * 0.9, r: 0.5 + r() });
    } else {
      // two tilted rings around it
      const a = r() * Math.PI * 2;
      const ring = i % 2 ? 1 : -1;
      const R = 92 + r() * 6;
      const x = Math.cos(a) * R;
      const yRing = Math.sin(a) * R * 0.22;
      out.push({ x: W / 2 + x * (ring > 0 ? 1 : 0.86), y: 128 + yRing * (ring > 0 ? 1 : 0.6) + ring * x * 0.06, z: Math.sin(a) * R * 0.5, b: 0.3 + r() * 0.4, r: 0.35 + r() * 0.6 });
    }
  }
  return out;
}

export class ParticleAvatar {
  private ctx: CanvasRenderingContext2D;
  private px = new Float32Array(COUNT);
  private py = new Float32Array(COUNT);
  private pz = new Float32Array(COUNT);
  private from: Target[] = [];
  private to: Target[] = [];
  private phase = new Float32Array(COUNT);
  private delay = new Float32Array(COUNT);
  private morphStart = -1e9;
  private shapes: Partial<Record<AvatarShape, Target[]>> = {};
  private sprite: HTMLCanvasElement | null = null;
  private raf = 0;
  private t0 = performance.now();
  private pointer = { x: 0, y: 0 };
  private level = 0;
  shape: AvatarShape = "core";
  state: AvatarState = "idle";

  constructor(
    private canvas: HTMLCanvasElement,
    private theme: AvatarTheme,
    private reduced = false,
  ) {
    this.ctx = canvas.getContext("2d")!;
    const r = rand(7);
    for (let i = 0; i < COUNT; i++) {
      this.phase[i] = r() * Math.PI * 2;
      this.delay[i] = r() * 0.35;
    }
    this.to = this.points("core");
    this.from = this.to;
    this.to.forEach((t, i) => {
      this.px[i] = t.x;
      this.py[i] = t.y;
      this.pz[i] = t.z;
    });
    this.setTheme(theme);
  }

  private points(shape: AvatarShape): Target[] {
    if (!this.shapes[shape]) this.shapes[shape] = shape === "core" ? corePoints(11) : samplePoints(shape, shape === "female" ? 21 : 31);
    return this.shapes[shape]!;
  }

  setTheme(theme: AvatarTheme) {
    this.theme = theme;
    const s = document.createElement("canvas");
    s.width = s.height = 32;
    const g = s.getContext("2d")!;
    const [r, gg, b] = hexRgb(theme.color);
    const grad = g.createRadialGradient(16, 16, 0, 16, 16, 16);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.18, `rgba(${Math.min(255, r + 90)},${Math.min(255, gg + 90)},${Math.min(255, b + 90)},0.95)`);
    grad.addColorStop(0.45, `rgba(${r},${gg},${b},0.35)`);
    grad.addColorStop(1, `rgba(${r},${gg},${b},0)`);
    g.fillStyle = grad;
    g.fillRect(0, 0, 32, 32);
    this.sprite = s;
  }

  setShape(shape: AvatarShape) {
    if (shape === this.shape) return;
    this.shape = shape;
    const now = (performance.now() - this.t0) / 1000;
    this.from = Array.from({ length: COUNT }, (_, i) => ({ x: this.px[i], y: this.py[i], z: this.pz[i], b: this.to[i]?.b ?? 0.5, r: this.to[i]?.r ?? 1 }));
    this.to = this.points(shape);
    this.morphStart = now;
  }

  setState(state: AvatarState) {
    this.state = state;
  }

  /** 0..1 loudness of the voice, for the speaking pulse. */
  setLevel(level: number) {
    this.level = Math.max(0, Math.min(1, level));
  }

  setPointer(x: number, y: number) {
    this.pointer = { x, y };
  }

  start() {
    const loop = () => {
      this.frame();
      this.raf = requestAnimationFrame(loop);
    };
    if (this.reduced) this.frame();
    else this.raf = requestAnimationFrame(loop);
  }

  stop() {
    cancelAnimationFrame(this.raf);
  }

  private frame() {
    const { canvas, ctx } = this;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    if (canvas.width !== Math.round(cw * dpr) || canvas.height !== Math.round(ch * dpr)) {
      canvas.width = Math.round(cw * dpr);
      canvas.height = Math.round(ch * dpr);
    }
    const t = (performance.now() - this.t0) / 1000;
    const scale = Math.min(canvas.width / W, canvas.height / H);
    const ox = (canvas.width - W * scale) / 2;
    const oy = (canvas.height - H * scale) / 2;
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const [gr, gg, gb] = hexRgb(this.theme.color);
    const glow = ctx.createRadialGradient(canvas.width / 2, oy + 110 * scale, 0, canvas.width / 2, oy + 110 * scale, 130 * scale);
    glow.addColorStop(0, `rgba(${gr},${gg},${gb},${this.state === "speaking" ? 0.16 : 0.1})`);
    glow.addColorStop(1, `rgba(${gr},${gg},${gb},0)`);
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.globalCompositeOperation = "lighter";

    const st = this.state;
    const speaking = st === "speaking";
    const voice = speaking ? 0.35 + 0.65 * Math.max(this.level, 0.5 + 0.5 * Math.sin(t * 13) * Math.sin(t * 5.3)) : 0;
    const yaw = Math.sin(t * 0.35) * 0.22 + this.pointer.x * 0.35 + (this.shape === "core" ? t * 0.4 : 0);
    const pitch = Math.sin(t * 0.27) * 0.05 + this.pointer.y * 0.15;
    const cy = Math.cos(yaw);
    const sy = Math.sin(yaw);
    const morph = Math.min(1, (t - this.morphStart) / 1.6);
    const glitch = morph < 0.35 ? 1 - morph / 0.35 : 0;
    const breathe = 1 + Math.sin(t * 1.4) * 0.008 + (st === "listening" ? -0.03 : 0);
    const flow = this.theme.energy === "flow";
    const sprite = this.sprite!;
    const mouthY = this.shape === "core" ? 128 : 125;

    for (let i = 0; i < COUNT; i++) {
      const a = this.from[i] || this.to[i];
      const b = this.to[i];
      let k = morph >= 1 ? 1 : Math.max(0, Math.min(1, (morph - this.delay[i]) / (1 - 0.35)));
      k = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; // ease in-out
      const swirl = Math.sin(k * Math.PI) * 60;
      const ph = this.phase[i];
      let x = a.x + (b.x - a.x) * k + Math.cos(ph + t) * swirl * 0.6;
      let y = a.y + (b.y - a.y) * k + Math.sin(ph * 1.3 + t) * swirl * 0.4;
      let z = a.z + (b.z - a.z) * k;
      // living drift
      x += Math.sin(t * 0.9 + ph) * 0.7;
      y += Math.cos(t * 0.7 + ph * 1.7) * 0.7;
      if (flow && b.b < 0.6) y -= ((t * 9 + ph * 20) % 26) * 0.18; // wisps rise like smoke from the edges
      if (!flow) {
        const g = 3;
        const snap = Math.max(0, Math.sin(t * 0.5 + y * 0.03)) * 0.35; // a slow scan of order passing down
        x += (Math.round(x / g) * g - x) * snap;
        y += (Math.round(y / g) * g - y) * snap;
      }
      if (speaking) {
        const d = Math.hypot(x - W / 2, y - mouthY);
        const wave = Math.sin(d * 0.12 - t * 9);
        const push = voice * wave * 2.4 * Math.exp(-d / 90);
        x += ((x - W / 2) / (d + 1)) * push;
        y += ((y - mouthY) / (d + 1)) * push;
      }
      if (st === "thinking" && i % 9 === 0) {
        const orb = t * (0.8 + (i % 5) * 0.12) + ph;
        const R = 96 + (i % 7) * 4;
        x = W / 2 + Math.cos(orb) * R;
        y = 120 + Math.sin(orb) * R * 0.32;
        z = Math.sin(orb) * R * 0.4;
      }
      // signal flicker while morphing: bands of particles slip sideways
      if (glitch > 0) {
        const band = Math.floor(y / 7);
        if ((band * 7919 + Math.floor(t * 30)) % 5 === 0) x += (((band * 31) % 11) - 5) * 5 * glitch;
      }
      // rotate and project
      const cx0 = (x - W / 2) * breathe;
      const cy0 = (y - H / 2) * breathe;
      const rx = cx0 * cy + z * sy;
      const rz = -cx0 * sy + z * cy;
      const ry = cy0 * Math.cos(pitch) - rz * Math.sin(pitch);
      const persp = 340 / (340 - rz);
      const sx = ox + (W / 2 + rx * persp) * scale;
      const sy2 = oy + (H / 2 + ry * persp) * scale;
      const tw = 0.75 + 0.25 * Math.sin(t * 2.2 + ph * 3);
      let alpha = (a.b + (b.b - a.b) * k) * tw * (0.55 + 0.45 * persp);
      if (speaking) alpha *= 0.85 + voice * 0.35;
      if (st === "listening") alpha *= 1.1;
      const size = (a.r + (b.r - a.r) * k) * scale * persp * 3.2;
      ctx.globalAlpha = Math.min(1, alpha);
      ctx.drawImage(sprite, sx - size / 2, sy2 - size / 2, size, size);
    }

    // faint dust around the figure for depth
    ctx.fillStyle = this.theme.color;
    for (let j = 0; j < 220; j++) {
      const ph = this.phase[j * 17];
      const x = ox + ((j * 53.3) % W + Math.sin(t * 0.2 + ph) * 8) * scale;
      const y = oy + (((j * 97.1) % H) - ((t * 4 + ph * 10) % H) + H) % H * scale;
      ctx.globalAlpha = 0.12 + 0.12 * Math.sin(t * 1.5 + ph);
      ctx.fillRect(x, y, scale * 0.7, scale * 0.7);
    }

    // accent sparks: a few brighter motes in the accent colour
    ctx.globalAlpha = 1;
    ctx.fillStyle = this.theme.accent;
    for (let j = 0; j < 26; j++) {
      const ph = this.phase[j * 97];
      const ang = t * 0.25 + ph;
      const R = 70 + ((j * 13) % 40);
      const x = ox + (W / 2 + Math.cos(ang) * R) * scale;
      const y = oy + (130 + Math.sin(ang * 1.3) * R * 0.8) * scale;
      ctx.globalAlpha = 0.25 + 0.35 * Math.sin(t * 3 + ph);
      ctx.beginPath();
      ctx.arc(x, y, scale * 0.9, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }
}
