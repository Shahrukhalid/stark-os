"use client";

import { useEffect, useRef } from "react";

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  hue: number;
}

interface Spark {
  a: number;
  b: number;
  t: number;
  speed: number;
}

/**
 * A slow "neural network" behind the dashboard: drifting nodes, links between neighbours and signals that
 * travel along the links. `activity` (0..1) speeds it up while agents are working. Pauses when the tab is hidden.
 */
export function ParticleField({ activity = 0, dense = true }: { activity?: number; dense?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const act = useRef(activity);
  act.current = activity;

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let w = 0;
    let h = 0;
    let dpr = 1;
    let nodes: Node[] = [];
    const sparks: Spark[] = [];
    let raf = 0;
    let last = performance.now();
    const light = () => document.documentElement.dataset.theme === "light";

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.round(Math.min(110, (w * h) / (dense ? 14000 : 26000)));
      nodes = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
        r: 0.8 + Math.random() * 1.6,
        hue: Math.random() < 0.72 ? 188 : Math.random() < 0.6 ? 262 : 322,
      }));
    };
    resize();
    window.addEventListener("resize", resize);

    const LINK = 130;
    const frame = (now: number) => {
      const dt = Math.min(48, now - last) / 16.7;
      last = now;
      const a = act.current;
      const speed = 1 + a * 2.2;
      const lt = light();
      ctx.clearRect(0, 0, w, h);
      for (const n of nodes) {
        n.x += n.vx * dt * speed;
        n.y += n.vy * dt * speed;
        if (n.x < -10) n.x = w + 10;
        if (n.x > w + 10) n.x = -10;
        if (n.y < -10) n.y = h + 10;
        if (n.y > h + 10) n.y = -10;
      }
      // links
      ctx.lineWidth = 0.6;
      const pairs: [number, number][] = [];
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const d = Math.hypot(dx, dy);
          if (d < LINK) {
            const o = (1 - d / LINK) * (lt ? 0.16 : 0.22);
            ctx.strokeStyle = `hsla(${nodes[i].hue}, 90%, ${lt ? 40 : 62}%, ${o})`;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
            pairs.push([i, j]);
          }
        }
      }
      // signals travelling along links: more while the team is working
      if (pairs.length && sparks.length < 6 + a * 40 && Math.random() < 0.05 + a * 0.4) {
        const [i, j] = pairs[(Math.random() * pairs.length) | 0];
        sparks.push({ a: i, b: j, t: 0, speed: 0.012 + Math.random() * 0.02 + a * 0.02 });
      }
      for (let k = sparks.length - 1; k >= 0; k--) {
        const s = sparks[k];
        s.t += s.speed * dt;
        const A = nodes[s.a];
        const B = nodes[s.b];
        if (!A || !B || s.t >= 1) {
          sparks.splice(k, 1);
          continue;
        }
        const x = A.x + (B.x - A.x) * s.t;
        const y = A.y + (B.y - A.y) * s.t;
        const g = ctx.createRadialGradient(x, y, 0, x, y, 7);
        g.addColorStop(0, `hsla(${A.hue}, 100%, ${lt ? 45 : 75}%, 0.95)`);
        g.addColorStop(1, `hsla(${A.hue}, 100%, 60%, 0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, 7, 0, Math.PI * 2);
        ctx.fill();
      }
      // nodes
      for (const n of nodes) {
        ctx.fillStyle = `hsla(${n.hue}, 95%, ${lt ? 42 : 70}%, ${lt ? 0.45 : 0.75})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(frame);
    };
    const start = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };
    start();
    document.addEventListener("visibilitychange", start);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", start);
    };
  }, [dense]);

  return <canvas ref={ref} aria-hidden className="pointer-events-none fixed inset-0 z-0" />;
}
