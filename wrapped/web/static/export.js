/* Client-side PNG export: hand-drawn canvas per card template.
   Nothing leaves the browser — the redaction layer (private: true) is
   enforced upstream in the picker; this module only ever sees public cards. */

const W = 1080;
const H = 1350; // 4:5 portrait, share-friendly

const COLORS = {
  bg: "#050506",
  ink: "#ffffff",
  muted: "rgba(255,255,255,0.62)",
  faint: "rgba(255,255,255,0.45)",
  primary: "#e63232",
  accent: "#ffbcb2",
};

const FONT = "'Space Grotesk', system-ui, sans-serif";
const MONO = "'JetBrains Mono', ui-monospace, monospace";
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
  ctx.font = `600 26px ${MONO}`;
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
  glow.addColorStop(0, "rgba(230, 50, 50, 0.18)");
  glow.addColorStop(1, "rgba(230, 50, 50, 0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);

  // the shell's dot matrix, one static frame
  for (let y = 11; y < H; y += 26) {
    for (let x = 11; x < W; x += 26) {
      ctx.fillStyle = "rgba(255,255,255,0.045)";
      ctx.fillRect(x, y, 2, 2);
    }
  }

  // film grain — felt, not seen
  for (let i = 0; i < 2200; i++) {
    ctx.fillStyle = `rgba(255, 255, 255, ${Math.random() * 0.04})`;
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
  ctx.font = `500 34px ${MONO}`;
  ctx.textAlign = "center";
  ctx.fillText(periodLabel, W / 2, 250);

  if (card.template === "top_list") {
    drawCentered(ctx, card.headline, 380, `700 64px ${FONT}`, COLORS.ink);
    let y = 480;
    (card.items || []).slice(0, 5).forEach((item, i) => {
      // surface row with hairline, like the on-screen list
      ctx.fillStyle = i === 0 ? "rgba(230, 50, 50, 0.12)" : "rgba(255, 255, 255, 0.04)";
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
      grad.addColorStop(0, "#ffffff");
      grad.addColorStop(0.55, "#ffb0a4");
      grad.addColorStop(1, "#e51010");
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
  ctx.font = `700 30px ${MONO}`;
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

export async function downloadCardPNG(card, periodLabel) {
  await document.fonts.ready; // Space Grotesk / JetBrains Mono must be loaded before canvas text
  const canvas = renderCardPNG(card, periodLabel);
  canvas.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `wrapped-${card.fact.replaceAll(".", "-")}.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, "image/png");
}

/* ---------- full report (summary slide + summary PNG) ---------- */

/* "2026" for yearly, "June 2026" for monthly — the report's period tag. */
export function periodTag(story) {
  return story.period.type === "year" ? story.period.id : story.period.label;
}

/* "412 hours watched" with value 412 → "hours watched"; else the headline. */
function cellLabel(card) {
  const prefix = fmt(card.value) + " ";
  const h = card.headline || (card.fact || "").split(".")[0];
  return h.startsWith(prefix) ? h.slice(prefix.length) : h;
}

/* One condensed stat per public card — the single source both the summary
   slide's bento grid and the full-report PNG render from. */
export function summaryCells(story) {
  const cells = [];
  for (const c of story.cards) {
    if (c.private) continue;
    if (c.template === "big_number" || c.template === "superlative") {
      cells.push({ label: cellLabel(c), value: fmt(c.value), num: c.value, sub: c.sub || "", grad: true });
    } else if (c.template === "streak") {
      cells.push({
        label: cellLabel(c),
        value: `${fmt(c.value)} days`,
        num: c.value,
        unit: " days",
        sub: c.sub || "",
        accent: true,
      });
    } else if (c.template === "top_list" && c.items?.length) {
      const more = c.items.length - 1;
      cells.push({
        label: cellLabel(c),
        value: c.items[0].label,
        sub: String(c.items[0].value) + (more > 0 ? ` · ${more} more` : ""),
      });
    } else if (c.template === "comparison" && c.items?.length) {
      const items = c.items.slice(0, 3);
      const nums = items.map((i) => Number(i.raw ?? i.value) || 0);
      const leader = items[nums.indexOf(Math.max(...nums))];
      cells.push({
        label: items.map((i) => i.label).join(" / "),
        value: leader.label,
        bars: nums,
        sub: items.map((i) => String(i.value)).join(" · "),
      });
    } else if (c.template === "heatmap" && c.data) {
      const keys = Object.keys(c.data).sort();
      const values = keys.map((k) => c.data[k]);
      const active = values.filter(Boolean).length;
      // real trend, not decoration: daily totals folded into 12 buckets
      let series = null;
      if (values.length >= 4) {
        series = Array(12).fill(0);
        values.forEach((v, i) => {
          series[Math.floor((i / values.length) * 12)] += v;
        });
      }
      cells.push({
        label: "Activity",
        value: `${fmt(active)} days`,
        num: active,
        unit: " days",
        sub: "with something happening",
        accent: true,
        series,
      });
    }
  }
  return cells;
}

/* The "Full report" share card: every public stat on one 1080×1350 PNG,
   laid out per the Summary + Export handoff (§3). */
export function renderSummaryPNG(story) {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  const padX = 70;
  const tag = periodTag(story).toUpperCase();

  const bg = ctx.createRadialGradient(W * 0.5, H * 0.4, 60, W * 0.5, H * 0.4, H * 0.78);
  bg.addColorStop(0, "#3a0808");
  bg.addColorStop(0.72, "#0a0304");
  bg.addColorStop(1, "#0a0304");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // header: beacon + wordmark left, period right
  ctx.textBaseline = "middle";
  ctx.fillStyle = COLORS.primary;
  ctx.beginPath();
  ctx.arc(padX + 7, 92, 7, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = COLORS.ink;
  ctx.font = `600 22px ${MONO}`;
  ctx.textAlign = "left";
  ctx.letterSpacing = "3px";
  ctx.fillText("HOMELAB WRAPPED", padX + 26, 94);
  ctx.letterSpacing = "0px";
  ctx.textAlign = "right";
  ctx.fillStyle = COLORS.faint;
  ctx.fillText(tag, W - padX, 94);
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";

  // kicker + two-line title
  ctx.fillStyle = "#ff9a8f";
  ctx.font = `600 26px ${MONO}`;
  ctx.letterSpacing = "5px";
  ctx.fillText(`${tag} · FULL REPORT`, padX, 220);
  ctx.letterSpacing = "0px";
  const noun = story.period.type === "month" ? "month" : "year";
  ctx.fillStyle = COLORS.ink;
  ctx.font = `700 78px ${FONT}`;
  ctx.fillText(`The ${noun}`, padX, 320);
  const hg = ctx.createLinearGradient(padX, 340, padX, 410);
  hg.addColorStop(0, "#ff8472");
  hg.addColorStop(1, "#d20c0c");
  ctx.fillStyle = hg;
  ctx.fillText("in numbers", padX, 402);

  // one rounded stat box; the value shrinks until it fits its box
  const stat = (x, y, w, h, cell, big, grad) => {
    ctx.fillStyle = "rgba(255,255,255,0.05)";
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 22);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.14)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = COLORS.accent;
    ctx.font = `600 18px ${MONO}`;
    ctx.letterSpacing = "2px";
    const label = cell.label.toUpperCase();
    ctx.fillText(label.length > 34 ? label.slice(0, 33) + "…" : label, x + 30, y + 50);
    ctx.letterSpacing = "0px";
    let size = big;
    ctx.font = `700 ${size}px ${FONT}`;
    while (size > 26 && ctx.measureText(cell.value).width > w - 60) {
      size -= 6;
      ctx.font = `700 ${size}px ${FONT}`;
    }
    // the hero's huge digits anchor to the box bottom so they can never
    // run into the sub line; small cells hang off the label instead
    const baseline = grad ? y + h - 84 : y + 50 + size;
    if (grad) {
      const vg = ctx.createLinearGradient(0, baseline - size, 0, baseline);
      vg.addColorStop(0, "#ffffff");
      vg.addColorStop(0.55, "#ffb0a4");
      vg.addColorStop(1, "#e51010");
      ctx.fillStyle = vg;
    } else {
      ctx.fillStyle = cell.accent ? "#ff7a5a" : COLORS.ink;
    }
    ctx.fillText(cell.value, x + 30, baseline);
    if (cell.sub) {
      ctx.fillStyle = COLORS.muted;
      ctx.font = `400 22px ${MONO}`;
      const sub = cell.sub.length > Math.floor(w / 14) ? cell.sub.slice(0, Math.floor(w / 14) - 1) + "…" : cell.sub;
      ctx.fillText(sub, x + 30, y + h - 34);
    }
  };

  const cells = summaryCells(story);
  const heroIdx = Math.max(cells.findIndex((c) => c.grad), 0);
  const hero = cells[heroIdx];
  const rest = cells.filter((_, i) => i !== heroIdx).slice(0, 6);

  const gw = W - padX * 2;
  const gap = 22;
  const cw = (gw - gap) / 2;
  let y = 470;
  if (hero) {
    stat(padX, y, gw, 250, hero, 132, hero.grad);
    y += 250 + gap;
  }
  const rH = rest.length > 4 ? 150 : 200;
  const vSize = rest.length > 4 ? 44 : 58;
  rest.forEach((cell, i) => {
    stat(padX + (i % 2) * (cw + gap), y + Math.floor(i / 2) * (rH + gap), cw, rH, cell, vSize, false);
  });

  ctx.textAlign = "center";
  ctx.fillStyle = COLORS.faint;
  ctx.font = `400 24px ${MONO}`;
  ctx.fillText("generated on your hardware · nothing left the building", W / 2, H - 64);
  ctx.textAlign = "left";
  return canvas;
}

export async function downloadSummaryPNG(story) {
  await document.fonts.ready;
  const canvas = renderSummaryPNG(story);
  canvas.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `homelab-wrapped-${story.period.id}-summary.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, "image/png");
}
