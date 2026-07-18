/* Shell chrome behaviour: dot-matrix background + terminal typing lines.
   Lifted from the design prototype (docs/design/), adapted to vanilla.
   Reduced motion: one static frame / final text, no loops. */

const RM = matchMedia("(prefers-reduced-motion: reduce)").matches;

function fit(cv) {
  const dpr = Math.min(devicePixelRatio || 1, 2);
  const w = cv.clientWidth;
  const h = cv.clientHeight;
  cv.width = w * dpr;
  cv.height = h * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  return { ctx, w, h };
}

/* Breathing dot grid with a red pulse wandering through it. */
function dotMatrix(cv) {
  let { ctx, w, h } = fit(cv);
  const gap = 22;
  const draw = (t) => {
    if (!cv.isConnected) return;
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
    if (!RM) requestAnimationFrame(draw);
  };
  if (RM) draw(900);
  else requestAnimationFrame(draw);
}

/* Terminal line that types itself; data-lines is a JSON array to rotate. */
function typeLine(el) {
  const lines = JSON.parse(el.dataset.lines || "[]");
  if (!lines.length) return;
  if (RM) {
    el.textContent = lines[0];
    return;
  }
  const caret = document.createElement("span");
  caret.className = "caret";
  let li = 0;
  function run() {
    const s = lines[li];
    let i = 0;
    const tick = () => {
      if (!el.isConnected) return;
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

const bg = document.getElementById("hw-bg");
if (bg) dotMatrix(bg);
document.querySelectorAll(".hw-term[data-lines]").forEach(typeLine);
