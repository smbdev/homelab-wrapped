/* Client-side PNG export: hand-drawn canvas per card template.
   Nothing leaves the browser — the redaction layer (private: true) is
   enforced upstream in the picker; this module only ever sees public cards. */

const W = 1080;
const H = 1350; // 4:5 portrait, share-friendly

const COLORS = {
  bg: "oklch(0.12 0 0)",
  surface: "oklch(0.17 0.004 36)",
  ink: "oklch(0.96 0.005 36)",
  muted: "oklch(0.74 0.01 36)",
  primary: "oklch(0.68 0.16 36)",
  accent: "oklch(0.85 0.12 85)",
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

export function renderCardPNG(card, periodLabel) {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");

  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, W, H);

  // a soft ember glow behind the number — the projector beam
  const glow = ctx.createRadialGradient(W / 2, H * 0.42, 60, W / 2, H * 0.42, 620);
  glow.addColorStop(0, "oklch(0.22 0.045 36)");
  glow.addColorStop(1, COLORS.bg);
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = COLORS.muted;
  ctx.font = `600 34px ${FONT}`;
  ctx.textAlign = "center";
  ctx.fillText(periodLabel, W / 2, 140);

  if (card.template === "top_list") {
    drawCentered(ctx, card.headline, 320, `700 64px ${FONT}`, COLORS.ink);
    let y = 470;
    (card.items || []).slice(0, 5).forEach((item, i) => {
      ctx.textAlign = "left";
      ctx.font = `800 44px ${FONT}`;
      ctx.fillStyle = COLORS.primary;
      ctx.fillText(String(i + 1), 140, y);
      ctx.font = `600 44px ${FONT}`;
      ctx.fillStyle = COLORS.ink;
      const label =
        item.label.length > 26 ? item.label.slice(0, 25) + "…" : item.label;
      ctx.fillText(label, 210, y);
      ctx.textAlign = "right";
      ctx.font = `400 38px ${FONT}`;
      ctx.fillStyle = i === 0 ? COLORS.accent : COLORS.muted;
      ctx.fillText(String(item.value), W - 140, y);
      y += 110;
    });
  } else if (card.template === "comparison") {
    drawCentered(ctx, card.headline, 320, `700 64px ${FONT}`, COLORS.ink);
    const items = (card.items || []).slice(0, 4);
    const max = Math.max(...items.map((i) => Number(i.raw ?? i.value) || 0), 1);
    let y = 480;
    for (const [i, item] of items.entries()) {
      ctx.textAlign = "left";
      ctx.font = `600 40px ${FONT}`;
      ctx.fillStyle = COLORS.ink;
      ctx.fillText(item.label, 140, y);
      ctx.textAlign = "right";
      ctx.fillStyle = COLORS.muted;
      ctx.fillText(String(item.value), W - 140, y);
      const w = Math.max((Number(item.raw ?? item.value) || 0) / max, 0.04) * (W - 280);
      ctx.fillStyle = i === 1 ? COLORS.accent : COLORS.primary;
      ctx.beginPath();
      ctx.roundRect(140, y + 24, w, 20, 10);
      ctx.fill();
      y += 150;
    }
  } else {
    // big_number / superlative / streak: one huge value
    const value = fmt(card.value);
    const color = card.template === "streak" ? COLORS.accent : COLORS.primary;
    ctx.font = `800 260px ${FONT}`;
    // shrink to fit if the number is long
    if (ctx.measureText(value).width > W - 200) ctx.font = `800 170px ${FONT}`;
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.fillText(value, W / 2, 620);

    const prefix = value + " ";
    const label = card.headline.startsWith(prefix)
      ? card.headline.slice(prefix.length)
      : card.headline;
    let y = drawCentered(ctx, label, 760, `700 64px ${FONT}`, COLORS.ink);
    if (card.sub) drawCentered(ctx, card.sub, y + 40, `400 44px ${FONT}`, COLORS.muted);
  }

  ctx.font = `600 32px ${FONT}`;
  ctx.fillStyle = COLORS.muted;
  ctx.textAlign = "center";
  ctx.fillText("· Homelab Wrapped ·", W / 2, H - 90);

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
