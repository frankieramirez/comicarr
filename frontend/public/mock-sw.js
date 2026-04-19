// Comicarr mock-mode service worker.
// Synthesizes gradient SVG covers for /api/metadata/art/:id and /api/cache/art/:id
// so the Library, Series Detail, Dashboard, etc. have real artwork while the
// real backend sits idle. Registered only when mock mode is enabled.

const COVERS = {
  "absolute-flash":     { bg: ["#c1281e", "#f5a623"], accent: "#ffeb3b", label: "ABSOLUTE FLASH" },
  "ultimate-wolverine": { bg: ["#2a2f3a", "#6d7685"], accent: "#f8c13b", label: "ULT WOLVERINE" },
  "tmnt":               { bg: ["#0e3a1a", "#58a93a"], accent: "#ffffff", label: "TMNT" },
  "transformers":       { bg: ["#1a1148", "#4a2dbb"], accent: "#ff4081", label: "TRANSFORMERS" },
  "absolute-batman":    { bg: ["#0b0b10", "#2a2d3a"], accent: "#f5c842", label: "ABS BATMAN" },
  "20cb":               { bg: ["#d4a373", "#1d1d1b"], accent: "#e63946", label: "20TH C BOYS" },
  "chainsaw":           { bg: ["#f25c54", "#1a1a1a"], accent: "#ffd166", label: "CHAINSAW MAN" },
  "fujimoto":           { bg: ["#2a1a3a", "#d4a3ff"], accent: "#ffd166", label: "17-21" },
  "monster":            { bg: ["#3a2a1a", "#d4c4a3"], accent: "#8a5a3a", label: "MONSTER" },
  "ark-m":              { bg: ["#1a1a24", "#5c3a8a"], accent: "#58a93a", label: "ARK-M" },
  "annual-25":          { bg: ["#2a1414", "#c1281e"], accent: "#f5c842", label: "ANNUAL 25" },
  "21cb":               { bg: ["#1a3a5c", "#d4a373"], accent: "#e63946", label: "21ST C BOYS" },
};

const FALLBACK_PALETTE = [
  ["#2a1a3a", "#d4a3ff", "#ffd166"],
  ["#0e3a1a", "#58a93a", "#ffffff"],
  ["#1a1148", "#4a2dbb", "#ff4081"],
  ["#c1281e", "#f5a623", "#ffeb3b"],
  ["#3a2a1a", "#d4c4a3", "#8a5a3a"],
];

function hash(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function escapeXml(text) {
  return text.replace(/[&<>"']/g, (ch) => {
    switch (ch) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}

function coverSvg(id) {
  const cover = COVERS[id];
  let c1, c2, accent, label;
  if (cover) {
    [c1, c2] = cover.bg;
    accent = cover.accent;
    label = cover.label;
  } else {
    const pal = FALLBACK_PALETTE[hash(id) % FALLBACK_PALETTE.length];
    c1 = pal[0];
    c2 = pal[1];
    accent = pal[2];
    label = id.slice(0, 10).toUpperCase();
  }
  const w = 200, h = 300;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="${c1}"/>
        <stop offset="1" stop-color="${c2}"/>
      </linearGradient>
      <pattern id="p" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="8" height="8" fill="url(#g)"/>
        <line x1="0" y1="0" x2="0" y2="8" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
      </pattern>
    </defs>
    <rect width="${w}" height="${h}" fill="url(#p)"/>
    <rect x="0" y="${h * 0.62}" width="${w}" height="${h * 0.38}" fill="rgba(0,0,0,0.45)"/>
    <text x="${w * 0.08}" y="${h * 0.78}" fill="${accent}" font-family="Inter, sans-serif" font-weight="800" font-size="20" letter-spacing="-0.5">${escapeXml(label)}</text>
    <text x="${w * 0.08}" y="${h * 0.94}" fill="rgba(255,255,255,0.65)" font-family="ui-monospace, Menlo, monospace" font-size="11">MOCK</text>
  </svg>`;
}

self.addEventListener("install", (e) => {
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const m = url.pathname.match(/^\/api\/(metadata|cache)\/art\/([^/]+)$/);
  if (!m) return;
  const id = m[2];
  const svg = coverSvg(id);
  event.respondWith(
    new Response(svg, {
      headers: {
        "Content-Type": "image/svg+xml",
        "Cache-Control": "no-store",
      },
    }),
  );
});
