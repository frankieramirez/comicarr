import { useEffect, useRef } from "react";

const SPACING = 40;
const SAMPLE_STEP = 6;
const WARP_RADIUS = 180;
const WARP_STRENGTH = 10;
const GLOW_RADIUS = 220;

function readCssColor(varName: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim();
  return v || fallback;
}

function parseRGB(color: string): [number, number, number] | null {
  if (!color) return null;
  if (color.startsWith("#")) {
    const hex = color.slice(1);
    const full =
      hex.length === 3
        ? hex
            .split("")
            .map((c) => c + c)
            .join("")
        : hex;
    if (full.length !== 6) return null;
    return [
      parseInt(full.slice(0, 2), 16),
      parseInt(full.slice(2, 4), 16),
      parseInt(full.slice(4, 6), 16),
    ];
  }
  const m = color.match(/\d+(\.\d+)?/g);
  if (!m || m.length < 3) return null;
  return [Number(m[0]), Number(m[1]), Number(m[2])];
}

export default function GridShader() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    let width = window.innerWidth;
    let height = window.innerHeight;

    const mouse = { x: -9999, y: -9999, active: false };
    const smooth = { x: -9999, y: -9999, glow: 0 };
    let running = false;
    let rafId = 0;

    const borderRGB = parseRGB(readCssColor("--border", "#232834")) || [
      35, 40, 52,
    ];
    const accentRGB = parseRGB(readCssColor("--primary", "#ff6a1f")) || [
      255, 106, 31,
    ];

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    };

    const warpOffset = (dx: number, dy: number) => {
      const d2 = dx * dx + dy * dy;
      const r2 = WARP_RADIUS * WARP_RADIUS;
      if (d2 > r2 * 4) return { ox: 0, oy: 0, intensity: 0 };
      const f = Math.exp(-d2 / (r2 * 0.5));
      const len = Math.sqrt(d2) || 1;
      return {
        ox: (dx / len) * WARP_STRENGTH * f * smooth.glow,
        oy: (dy / len) * WARP_STRENGTH * f * smooth.glow,
        intensity: f * smooth.glow,
      };
    };

    const radialMask = (x: number, y: number) => {
      const cx = width / 2;
      const cy = height / 2;
      const dx = x - cx;
      const dy = y - cy;
      const maxR = Math.hypot(cx, cy);
      const r = Math.hypot(dx, dy) / maxR;
      return Math.max(0, 1 - Math.pow(r / 0.7, 2));
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      const baseAlpha = 0.085;
      const mx = smooth.x;
      const my = smooth.y;
      const glowing = smooth.glow > 0.01;

      for (let x = 0; x <= width + SPACING; x += SPACING) {
        ctx.beginPath();
        let started = false;
        let accumIntensity = 0;
        let samples = 0;
        for (let y = 0; y <= height; y += SAMPLE_STEP) {
          let px = x;
          let py = y;
          if (glowing) {
            const { ox, oy, intensity } = warpOffset(x - mx, y - my);
            px += ox;
            py += oy;
            accumIntensity += intensity;
            samples++;
          }
          if (!started) {
            ctx.moveTo(px, py);
            started = true;
          } else {
            ctx.lineTo(px, py);
          }
        }
        const mid = radialMask(x, height / 2);
        let alpha = baseAlpha * mid;
        let r = borderRGB[0];
        let g = borderRGB[1];
        let b = borderRGB[2];
        if (glowing && samples > 0) {
          const avg = accumIntensity / samples;
          const boost = Math.min(1, avg * 2.8);
          alpha = Math.min(0.5, (baseAlpha + boost * 0.28) * mid);
          const mix = Math.min(1, avg * 3.2);
          r = Math.round(borderRGB[0] + (accentRGB[0] - borderRGB[0]) * mix);
          g = Math.round(borderRGB[1] + (accentRGB[1] - borderRGB[1]) * mix);
          b = Math.round(borderRGB[2] + (accentRGB[2] - borderRGB[2]) * mix);
        }
        ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      for (let y = 0; y <= height + SPACING; y += SPACING) {
        ctx.beginPath();
        let started = false;
        let accumIntensity = 0;
        let samples = 0;
        for (let x = 0; x <= width; x += SAMPLE_STEP) {
          let px = x;
          let py = y;
          if (glowing) {
            const { ox, oy, intensity } = warpOffset(x - mx, y - my);
            px += ox;
            py += oy;
            accumIntensity += intensity;
            samples++;
          }
          if (!started) {
            ctx.moveTo(px, py);
            started = true;
          } else {
            ctx.lineTo(px, py);
          }
        }
        const mid = radialMask(width / 2, y);
        let alpha = baseAlpha * mid;
        let r = borderRGB[0];
        let g = borderRGB[1];
        let b = borderRGB[2];
        if (glowing && samples > 0) {
          const avg = accumIntensity / samples;
          const boost = Math.min(1, avg * 2.8);
          alpha = Math.min(0.5, (baseAlpha + boost * 0.28) * mid);
          const mix = Math.min(1, avg * 3.2);
          r = Math.round(borderRGB[0] + (accentRGB[0] - borderRGB[0]) * mix);
          g = Math.round(borderRGB[1] + (accentRGB[1] - borderRGB[1]) * mix);
          b = Math.round(borderRGB[2] + (accentRGB[2] - borderRGB[2]) * mix);
        }
        ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Soft accent bloom directly under cursor
      if (glowing) {
        const grad = ctx.createRadialGradient(mx, my, 0, mx, my, GLOW_RADIUS);
        const a = 0.1 * smooth.glow;
        grad.addColorStop(
          0,
          `rgba(${accentRGB[0]}, ${accentRGB[1]}, ${accentRGB[2]}, ${a})`,
        );
        grad.addColorStop(
          1,
          `rgba(${accentRGB[0]}, ${accentRGB[1]}, ${accentRGB[2]}, 0)`,
        );
        ctx.fillStyle = grad;
        ctx.fillRect(
          mx - GLOW_RADIUS,
          my - GLOW_RADIUS,
          GLOW_RADIUS * 2,
          GLOW_RADIUS * 2,
        );
      }
    };

    const tick = () => {
      const tx = mouse.x;
      const ty = mouse.y;
      smooth.x += (tx - smooth.x) * 0.18;
      smooth.y += (ty - smooth.y) * 0.18;
      const targetGlow = mouse.active ? 1 : 0;
      smooth.glow += (targetGlow - smooth.glow) * 0.08;
      draw();
      if (
        mouse.active ||
        smooth.glow > 0.02 ||
        Math.abs(tx - smooth.x) > 0.5 ||
        Math.abs(ty - smooth.y) > 0.5
      ) {
        rafId = requestAnimationFrame(tick);
      } else {
        running = false;
        smooth.glow = 0;
        draw();
      }
    };

    const ensureRunning = () => {
      if (running || reduce) return;
      running = true;
      rafId = requestAnimationFrame(tick);
    };

    const onMove = (e: MouseEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.active = true;
      ensureRunning();
    };
    const onLeave = () => {
      mouse.active = false;
      ensureRunning();
    };

    window.addEventListener("resize", resize);
    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("mouseleave", onLeave);

    resize();

    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseleave", onLeave);
      cancelAnimationFrame(rafId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="absolute inset-0 w-full h-full pointer-events-none"
    />
  );
}
