/* Canvas backgrounds lifted from the design prototype (docs/design/):
   breathing dot grid, rising ember particles, horizontal data streams.
   Each returns nothing; it owns the canvas until the element leaves the DOM
   or its `epoch` marker changes. Reduced motion: one static frame. */

export const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

export function fit(cv) {
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const w = cv.clientWidth;
  const h = cv.clientHeight;
  cv.width = w * dpr;
  cv.height = h * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  return { ctx, w, h };
}

function alive(cv, epoch) {
  return cv.isConnected && cv.__epoch === epoch;
}

function claim(cv) {
  cv.__epoch = (cv.__epoch || 0) + 1;
  return cv.__epoch;
}

export function dotMatrix(cv) {
  const epoch = claim(cv);
  let { ctx, w, h } = fit(cv);
  const gap = 22;
  const draw = (t) => {
    if (!alive(cv, epoch)) return;
    if (cv.clientWidth !== w) ({ ctx, w, h } = fit(cv));
    ctx.clearRect(0, 0, w, h);
    const cx = w * 0.5 + Math.sin(t / 2600) * 80;
    const cy = h * 0.5 + Math.cos(t / 3100) * 54;
    for (let y = gap / 2; y < h; y += gap) {
      for (let x = gap / 2; x < w; x += gap) {
        const d = Math.hypot(x - cx, y - cy);
        const pulse = Math.sin(d / 60 - t / 560);
        const a = Math.max(0, 0.5 - d / 820) * (0.45 + 0.55 * pulse);
        ctx.fillStyle = "rgba(255,255,255,0.04)";
        ctx.fillRect(x - 0.6, y - 0.6, 1.2, 1.2);
        if (a > 0.02) {
          ctx.fillStyle = `rgba(232,44,44,${0.07 + a * 0.9})`;
          ctx.beginPath();
          ctx.arc(x, y, 0.8 + a * 2.4, 0, 7);
          ctx.fill();
        }
      }
    }
    if (!REDUCED) requestAnimationFrame(draw);
  };
  if (REDUCED) draw(900);
  else requestAnimationFrame(draw);
}

export function particles(cv) {
  const epoch = claim(cv);
  let { ctx, w, h } = fit(cv);
  const pts = [];
  for (let i = 0; i < 90; i++)
    pts.push({ x: Math.random() * w, y: Math.random() * h, z: Math.random(), s: 0.15 + Math.random() * 0.6 });
  const draw = () => {
    if (!alive(cv, epoch)) return;
    if (cv.clientWidth !== w) ({ ctx, w, h } = fit(cv));
    ctx.clearRect(0, 0, w, h);
    for (const p of pts) {
      if (!REDUCED) {
        p.y -= p.s * (0.35 + p.z);
        if (p.y < -4) {
          p.y = h + 4;
          p.x = Math.random() * w;
        }
      }
      ctx.fillStyle = `rgba(255,${Math.round(72 - p.z * 42)},60,${0.1 + p.z * 0.5})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 0.5 + p.z * 1.9, 0, 7);
      ctx.fill();
    }
    if (!REDUCED) requestAnimationFrame(draw);
  };
  draw();
}

export function streamViz(cv) {
  const epoch = claim(cv);
  let { ctx, w, h } = fit(cv);
  const rows = [];
  for (let i = 0; i < 26; i++)
    rows.push({ y: Math.random(), sp: 0.4 + Math.random() * 1.4, x: Math.random(), len: 0.04 + Math.random() * 0.12 });
  const draw = () => {
    if (!alive(cv, epoch)) return;
    if (cv.clientWidth !== w) ({ ctx, w, h } = fit(cv));
    ctx.clearRect(0, 0, w, h);
    for (const r of rows) {
      if (!REDUCED) {
        r.x += r.sp / w;
        if (r.x > 1.1) r.x = -0.1;
      }
      const y = r.y * h;
      const x = r.x * w;
      const len = r.len * w;
      const g = ctx.createLinearGradient(x - len, 0, x, 0);
      g.addColorStop(0, "rgba(230,40,40,0)");
      g.addColorStop(1, "rgba(255,110,80,0.7)");
      ctx.strokeStyle = g;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(x - len, y);
      ctx.lineTo(x, y);
      ctx.stroke();
      ctx.fillStyle = "rgba(255,140,110,0.9)";
      ctx.fillRect(x - 1, y - 1, 2, 2);
    }
    if (!REDUCED) requestAnimationFrame(draw);
  };
  draw();
}

/* Tiny trend line: filled area + stroke + end dot, min/max normalised,
   drawn left-to-right over ~900ms (summary slide, handoff §6). */
export function sparkline(cv, data, color = "#ff8a72") {
  const epoch = claim(cv);
  const { ctx, w, h } = fit(cv);
  const pad = 3;
  const min = Math.min(...data);
  const rng = Math.max(...data) - min || 1;
  const pts = data.map((v, i) => ({
    x: pad + (i / (data.length - 1)) * (w - pad * 2),
    y: h - pad - ((v - min) / rng) * (h - pad * 2),
  }));
  const t0 = performance.now();
  const draw = (t) => {
    if (!alive(cv, epoch)) return;
    const p = REDUCED ? 1 : Math.min(1, (t - t0) / 900);
    ctx.clearRect(0, 0, w, h);
    const vis = pts.slice(0, Math.max(2, Math.ceil(p * pts.length)));
    ctx.beginPath();
    ctx.moveTo(vis[0].x, h - pad);
    for (const pt of vis) ctx.lineTo(pt.x, pt.y);
    ctx.lineTo(vis[vis.length - 1].x, h - pad);
    ctx.closePath();
    ctx.fillStyle = "rgba(255,138,114,0.16)";
    ctx.fill();
    ctx.beginPath();
    vis.forEach((pt, i) => (i ? ctx.lineTo(pt.x, pt.y) : ctx.moveTo(pt.x, pt.y)));
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.stroke();
    const last = vis[vis.length - 1];
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(last.x, last.y, 2.4, 0, 7);
    ctx.fill();
    if (p < 1 && !REDUCED) requestAnimationFrame(draw);
  };
  if (REDUCED) draw(0);
  else requestAnimationFrame(draw);
}

/* Terminal line that types itself; pass an array of lines to rotate. */
export function typeLine(el, lines) {
  if (!lines.length) return;
  if (REDUCED) {
    el.textContent = lines[0];
    return;
  }
  const caret = document.createElement("span");
  caret.className = "caret";
  const epoch = claim(el);
  let li = 0;
  function run() {
    const s = lines[li];
    let i = 0;
    const tick = () => {
      if (!alive(el, epoch)) return;
      el.textContent = s.slice(0, i);
      el.append(caret);
      i++;
      if (i <= s.length) setTimeout(tick, 28);
      else if (lines.length > 1)
        setTimeout(() => {
          li = (li + 1) % lines.length;
          run();
        }, 1600);
    };
    tick();
  }
  run();
}
