/* Client-side PNG export: hand-drawn canvas per card template.
   Nothing leaves the browser — the redaction layer (private: true) is
   enforced upstream in the picker; this module only ever sees public cards. */

const W = 1080;
const H = 1350; // 4:5 portrait, share-friendly

const COLORS = {
  bg: "#0a0a0a",
  surface: "#151515",
  ink: "#fafafa",
  muted: "#9ca3af",
  primary: "#ea2b2b",
  accent: "#fafafa",
};

const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
const EXPORTABLE = new Set(["big_number", "superlative", "streak", "top_list", "comparison"]);

export function isExportable(card) {
  return !card.private && EXPORTABLE.has(card.template);
}

const fmt = (n) => Number(n).toLocaleString("en-GB");

function wrapText(ctx, text, maxWidth) {
  const words = String(text).split(" ");
  const lines = [];
  let line = "";
  for (const word of words) {
    const probe = line ? `${line} ${word}` : word;
    if (ctx.measureText(probe).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = probe;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function drawCentered(ctx, text, y, font, color, lineHeight = 1.2) {
  ctx.font = font;
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  const lines = wrapText(ctx, text, W - 160);
  const size = parseInt(font, 10);
  for (const line of lines) {
    ctx.fillText(line, W / 2, y);
    y += size * lineHeight;
  }
  return y;
}

/* Category chip at the top: "media.total_hours" → red dot + "MEDIA" pill. */
function drawChip(ctx, fact, y) {
  const label = (fact || "").split(".")[0].replaceAll("_", " ").toUpperCase();
  if (!label) return;
  ctx.font = `600 26px ${FONT}`;
  ctx.letterSpacing = "6px";
  const tw = ctx.measureText(label).width;
  const pad = 36;
  const dot = 12;
  const cw = tw + dot + 18 + pad * 2;
  const x = (W - cw) / 2;
  ctx.strokeStyle = "rgba(255, 255, 255, 0.14)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.roundRect(x, y - 42, cw, 62, 31);
  ctx.stroke();
  ctx.fillStyle = COLORS.primary;
  ctx.beginPath();
  ctx.arc(x + pad + dot / 2, y - 11, dot / 2, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = COLORS.muted;
  ctx.textAlign = "left";
  ctx.fillText(label, x + pad + dot + 18, y);
  ctx.letterSpacing = "0px";
  ctx.textAlign = "center";
}

export function renderCardPNG(card, periodLabel) {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");

  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, W, H);

  // red glow behind the content
  const glow = ctx.createRadialGradient(W / 2, H * 0.42, 80, W / 2, H * 0.42, 720);
  glow.addColorStop(0, "rgba(234, 43, 43, 0.16)");
  glow.addColorStop(1, "rgba(234, 43, 43, 0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);

  // film grain — felt, not seen
  for (let i = 0; i < 2800; i++) {
    ctx.fillStyle = `rgba(255, 255, 255, ${Math.random() * 0.045})`;
    ctx.fillRect(Math.random() * W, Math.random() * H, 2, 2);
  }

  // hairline frame
  ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.roundRect(36, 36, W - 72, H - 72, 56);
  ctx.stroke();

  drawChip(ctx, card.fact, 160);

  ctx.fillStyle = COLORS.muted;
  ctx.font = `600 34px ${FONT}`;
  ctx.textAlign = "center";
  ctx.fillText(periodLabel, W / 2, 250);

  if (card.template === "top_list") {
    drawCentered(ctx, card.headline, 380, `700 64px ${FONT}`, COLORS.ink);
    let y = 480;
    (card.items || []).slice(0, 5).forEach((item, i) => {
      // surface row with hairline, like the on-screen list
      ctx.fillStyle = i === 0 ? "rgba(234, 43, 43, 0.1)" : "rgba(255, 255, 255, 0.04)";
      ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.roundRect(110, y, W - 220, 96, 20);
      ctx.fill();
      ctx.stroke();
      const baseline = y + 62;
      ctx.textAlign = "left";
      ctx.font = `800 44px ${FONT}`;
      ctx.fillStyle = COLORS.primary;
      ctx.fillText(String(i + 1), 150, baseline);
      ctx.font = `600 42px ${FONT}`;
      ctx.fillStyle = COLORS.ink;
      const label =
        item.label.length > 26 ? item.label.slice(0, 25) + "…" : item.label;
      ctx.fillText(label, 220, baseline);
      ctx.textAlign = "right";
      ctx.font = `400 36px ${FONT}`;
      ctx.fillStyle = i === 0 ? COLORS.accent : COLORS.muted;
      ctx.fillText(String(item.value), W - 150, baseline);
      y += 118;
    });
  } else if (card.template === "comparison") {
    drawCentered(ctx, card.headline, 380, `700 64px ${FONT}`, COLORS.ink);
    const items = (card.items || []).slice(0, 4);
    const max = Math.max(...items.map((i) => Number(i.raw ?? i.value) || 0), 1);
    let y = 520;
    for (const [i, item] of items.entries()) {
      ctx.textAlign = "left";
      ctx.font = `600 40px ${FONT}`;
      ctx.fillStyle = COLORS.ink;
      ctx.fillText(item.label, 140, y);
      ctx.textAlign = "right";
      ctx.fillStyle = COLORS.muted;
      ctx.fillText(String(item.value), W - 140, y);
      // full-width track, then the value bar on top
      ctx.fillStyle = "rgba(255, 255, 255, 0.07)";
      ctx.beginPath();
      ctx.roundRect(140, y + 28, W - 280, 24, 12);
      ctx.fill();
      const w = Math.max((Number(item.raw ?? item.value) || 0) / max, 0.04) * (W - 280);
      ctx.fillStyle = i === 1 ? COLORS.accent : COLORS.primary;
      ctx.beginPath();
      ctx.roundRect(140, y + 28, w, 24, 12);
      ctx.fill();
      y += 160;
    }
  } else {
    // big_number / superlative / streak: one huge value
    const value = fmt(card.value);
    let size = 280;
    ctx.font = `800 ${size}px ${FONT}`;
    if (ctx.measureText(value).width > W - 220) {
      size = 180;
      ctx.font = `800 ${size}px ${FONT}`;
    }
    ctx.textAlign = "center";
    // ghost echo behind the number
    ctx.fillStyle = "rgba(255, 255, 255, 0.03)";
    ctx.font = `800 ${Math.round(size * 1.7)}px ${FONT}`;
    ctx.fillText(value, W / 2, 700);
    // gradient-filled number, white for streaks and red for the rest
    ctx.font = `800 ${size}px ${FONT}`;
    const grad = ctx.createLinearGradient(0, 640 - size, 0, 640);
    if (card.template === "streak") {
      grad.addColorStop(0, "#ffffff");
      grad.addColorStop(1, "#9ca3af");
    } else {
      grad.addColorStop(0, "#ff6b6b");
      grad.addColorStop(0.55, COLORS.primary);
      grad.addColorStop(1, "#a81a1a");
    }
    ctx.fillStyle = grad;
    ctx.fillText(value, W / 2, 640);

    const prefix = value + " ";
    const label = card.headline.startsWith(prefix)
      ? card.headline.slice(prefix.length)
      : card.headline;
    let y = drawCentered(ctx, label, 790, `700 64px ${FONT}`, COLORS.ink);
    if (card.sub) drawCentered(ctx, card.sub, y + 40, `400 44px ${FONT}`, COLORS.muted);
  }

  // footer wordmark
  ctx.font = `700 30px ${FONT}`;
  ctx.letterSpacing = "8px";
  ctx.textAlign = "center";
  ctx.fillStyle = COLORS.muted;
  ctx.fillText("HOMELAB WRAPPED", W / 2, H - 100);
  ctx.letterSpacing = "0px";
  ctx.fillStyle = COLORS.primary;
  ctx.beginPath();
  ctx.arc(W / 2, H - 148, 5, 0, Math.PI * 2);
  ctx.fill();

  return canvas;
}

export function downloadCardPNG(card, periodLabel) {
  const canvas = renderCardPNG(card, periodLabel);
  canvas.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `wrapped-${card.fact.replaceAll(".", "-")}.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, "image/png");
}
