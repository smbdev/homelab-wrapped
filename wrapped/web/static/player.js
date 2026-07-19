/* Story player: renders story-spec JSON as swipeable full-screen cards.
   Vanilla ES module, no dependencies, no build step. */

import { dotMatrix, particles, sparkline, streamViz, typeLine } from "./canvas-bg.js";
import {
  downloadCardPNG,
  downloadSummaryPNG,
  isExportable,
  periodTag,
  summaryCells,
} from "./export.js";

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const story = JSON.parse(document.getElementById("story-data").textContent);

/* The full-report summary needs at least two stats to summarise; day
   recaps are a single moment and skip it. */
const HAS_SUMMARY = story.period.type !== "day" && summaryCells(story).length >= 2;

/* ---------- helpers ---------- */

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

const fmt = (n) => Number(n).toLocaleString("en-GB");

/* Count a number up from 0 over ~800ms (ease-out-expo). Reduced motion: final value. */
function countUp(node, target) {
  if (REDUCED || target === 0) {
    node.textContent = fmt(target);
    return;
  }
  const t0 = performance.now();
  const dur = 800;
  function tick(t) {
    const p = Math.min((t - t0) / dur, 1);
    const eased = 1 - Math.pow(2, -10 * p);
    node.textContent = fmt(Math.round(target * eased));
    if (p < 1) requestAnimationFrame(tick);
    else node.textContent = fmt(target);
  }
  requestAnimationFrame(tick);
}

/* Category chip from the fact id: "media.total_hours" → "media". */
function eyebrow(card) {
  const cat = (card.fact || "").split(".")[0];
  return cat ? el("p", "eyebrow", cat.replaceAll("_", " ")) : null;
}

function withEyebrow(root, card) {
  const chip = eyebrow(card);
  if (chip) root.prepend(chip);
  return root;
}

/* Satellite mini-cards around a big number, derived from OTHER public cards
   in the SAME category ("files.total" ↔ "files.top_folders") — a corner card
   must relate to the screen it decorates, never a random other fact. */
function satellites(card) {
  const cat = (card.fact || "").split(".")[0];
  if (!cat) return null;
  const sats = [];
  for (const c of story.cards) {
    if (c === card || c.private) continue;
    if ((c.fact || "").split(".")[0] !== cat) continue;
    if (c.template === "top_list" && c.items?.length) {
      sats.push({ k: "top of the list", v: c.items[0].label, s: c.items[0].value });
    } else if (c.template === "streak" && c.value) {
      sats.push({ k: "streak", v: `${fmt(c.value)} days`, s: c.sub || "" });
    } else if (c.template === "comparison" && c.items?.length) {
      const best = [...c.items].sort(
        (a, b) => (Number(b.raw ?? b.value) || 0) - (Number(a.raw ?? a.value) || 0)
      )[0];
      sats.push({ k: "heavyweight", v: best.label, s: String(best.value) });
    } else if (c.template === "heatmap" && c.data) {
      const [day, n] = Object.entries(c.data).sort((a, b) => b[1] - a[1])[0] || [];
      if (day) sats.push({ k: "busiest day", v: day, s: `${fmt(n)} events` });
    }
  }
  if (!sats.length) return null;
  // Two at most, on opposite corners; diagonal alternates slide to slide.
  const bigs = story.cards.filter((c) => c.template === "big_number" && !c.private);
  const corners = bigs.indexOf(card) % 2 ? ["sat-tr", "sat-bl"] : ["sat-tl", "sat-br"];
  const wrap = el("div", "sats");
  wrap.setAttribute("aria-hidden", "true");
  sats.slice(0, 2).forEach((s, i) => {
    const node = el("div", `sat ${corners[i]}`);
    node.append(el("div", "k", s.k), el("div", "v", s.v));
    if (s.s) node.append(el("div", "s", s.s));
    wrap.append(node);
  });
  return wrap;
}

/* "412 hours watched" + value 412 → label "hours watched"; else keep whole headline. */
function splitHeadline(card) {
  const prefix = fmt(card.value) + " ";
  if (card.headline && card.headline.startsWith(prefix)) {
    return card.headline.slice(prefix.length);
  }
  return null;
}

/* ---------- card renderers ---------- */

function bigNumber(card) {
  const root = el("article", "card big-number");
  const label = splitHeadline(card);
  const display = el("p", "display", "0");
  root.append(display);
  root.append(el("h2", null, label ?? card.headline));
  if (card.sub) root.append(el("p", "sub", card.sub));
  countUp(display, card.value);
  const sats = satellites(card);
  if (sats) root.append(sats);
  return withEyebrow(root, card);
}

function streak(card) {
  const root = el("article", "card streak");
  const display = el("p", "display", "0");
  root.append(display);
  root.append(el("h2", null, card.headline));
  if (card.sub) root.append(el("p", "sub", card.sub));
  countUp(display, card.value);
  return withEyebrow(root, card);
}

function topList(card) {
  const root = el("article", "card top-list");
  root.append(el("h2", null, card.headline));
  const list = el("ol", "toplist");
  const items = card.items || [];
  // bars scale to the numeric prefix of each value ("31 eps" → 31); if the
  // values aren't numeric, rows render without bars rather than fake ones
  const nums = items.map((it) => parseFloat(String(it.raw ?? it.value)) || 0);
  const max = Math.max(...nums, 0);
  items.forEach((item, i) => {
    const li = el("li");
    li.style.setProperty("--i", i);
    const top = el("div", "row-top");
    top.append(
      el("span", "rank", String(i + 1).padStart(2, "0")),
      el("span", "label", item.label),
      el("span", "value", item.value)
    );
    li.append(top);
    if (max > 0 && nums[i] > 0) {
      const track = el("div", "track");
      const fill = el("div", "fill");
      fill.style.width = `${Math.max((nums[i] / max) * 100, 4)}%`;
      track.append(fill);
      li.append(track);
    }
    list.append(li);
  });
  root.append(list);
  return withEyebrow(root, card);
}

function comparison(card) {
  const root = el("article", "card comparison");
  root.append(el("h2", null, card.headline));
  const wrap = el("div", "compare");
  const items = card.items || [];
  const max = Math.max(...items.map((i) => Number(i.raw ?? i.value) || 0), 1);
  for (const item of items) {
    const row = el("div", "row");
    const top = el("div", "top");
    top.append(el("span", "label", item.label), el("span", "value", String(item.value)));
    const bar = el("div", "bar");
    bar.style.width = `${Math.max((Number(item.raw ?? item.value) || 0) / max, 0.04) * 100}%`;
    row.append(top, bar);
    wrap.append(row);
  }
  root.append(wrap);
  if (card.sub) root.append(el("p", "sub", card.sub));
  return withEyebrow(root, card);
}

function heatmap(card) {
  const root = el("article", "card heatmap-card");
  root.append(el("h2", null, card.headline));
  const scroll = el("div", "heatmap-scroll");
  const wrap = el("div", "heatmap-wrap");
  const months = el("div", "heatmap-months");
  const days = el("div", "heatmap-days");
  for (const [row, name] of [[1, "Mon"], [3, "Wed"], [5, "Fri"]]) {
    const s = el("span", null, name);
    s.style.gridRow = row;
    days.append(s);
  }
  const grid = el("div", "heatmap");
  grid.setAttribute("role", "img");
  grid.setAttribute("aria-label", `${card.headline}: activity per day`);

  const COL = 16; // 13px cell + 3px gap
  const dates = Object.keys(card.data || {});
  if (dates.length) {
    const values = Object.values(card.data);
    const max = Math.max(...values);
    const first = new Date(dates[0] + "T00:00:00");
    const last = new Date(dates[dates.length - 1] + "T00:00:00");
    // Start on the Monday of the first week so columns are calendar weeks.
    const start = new Date(first);
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    const localISO = (d) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    let i = 0;
    let lastLabelCol = -3;
    for (let d = new Date(start); d <= last; d.setDate(d.getDate() + 1)) {
      const col = Math.floor(i / 7);
      if (d.getDate() === 1 && col > lastLabelCol + 2) {
        const m = el("span", "m", d.toLocaleString("en", { month: "short" }));
        m.style.left = `${col * COL}px`;
        months.append(m);
        lastLabelCol = col;
      }
      const iso = localISO(d); // not toISOString(): that shifts to UTC and misses local dates
      const v = card.data[iso] || 0;
      const cell = el("div", "cell");
      cell.style.setProperty("--c", col);
      if (v > 0) {
        const level = Math.max(1, Math.ceil((4 * v) / max));
        cell.classList.add(`l${level}`);
        cell.title = `${iso}: ${fmt(v)}`;
      }
      grid.append(cell);
      i++;
    }
  }
  const body = el("div", "heatmap-body");
  body.append(days, grid);
  const legend = el("div", "heatmap-legend");
  legend.append(el("span", null, "Less"));
  for (const lvl of ["", " l1", " l2", " l3", " l4"]) legend.append(el("i", "cell" + lvl));
  legend.append(el("span", null, "More"));
  wrap.append(months, body, legend);
  scroll.append(wrap);
  root.append(scroll);
  root.append(el("p", "sub", card.sub || "One square per day — the brighter, the busier."));
  return withEyebrow(root, card);
}

function superlative(card) {
  return bigNumber(card); // same anatomy, different fact flavour
}

function intro() {
  const root = el("article", "card intro");
  root.append(el("p", "kicker", "Homelab Wrapped"));
  root.append(el("h1", "display", story.period.label));
  const hint = el("p", "hint-line");
  hint.append("Tap anywhere to begin — or use ");
  hint.append(el("kbd", "key", "←"));
  hint.append(" ");
  hint.append(el("kbd", "key", "→"));
  root.append(hint);
  return root;
}

function quiet() {
  const root = el("article", "card quiet");
  root.append(el("p", "display", "…"));
  root.append(el("h2", null, "A quiet one"));
  root.append(el("p", "sub", "No events in this period. Point a connector at some data and rebuild."));
  return root;
}

/* Chapter 9: the whole wrap as one bento grid (Summary + Export handoff). */
function summary() {
  const root = el("article", "card summary");
  for (const pos of ["tl", "tr", "bl", "br"]) root.append(el("i", `hud ${pos}`));
  if (!REDUCED) root.append(el("i", "scanline"));

  const head = el("header", "summary-head");
  head.append(el("p", "kicker", `${periodTag(story)} · full report`));
  const noun = story.period.type === "month" ? "month" : "year";
  const title = el("h2", "summary-title");
  title.append(`The ${noun} in `);
  title.append(el("span", "grad", "numbers"));
  head.append(title);
  head.append(el("p", "sub", "everything above, on one screen — read straight off your box"));
  root.append(head);

  const cells = summaryCells(story);
  const heroIdx = Math.max(cells.findIndex((c) => c.grad), 0);
  const grid = el("div", "bento");
  cells.slice(0, 8).forEach((cell, i) => {
    const box = el("div", i === heroIdx ? "cell hero" : "cell");
    box.append(el("div", "k", cell.label));
    if (cell.bars) {
      const bars = el("div", "mini-bars");
      const max = Math.max(...cell.bars, 1);
      for (const n of cell.bars) {
        const track = el("div", "track");
        const fill = el("div", "fill");
        fill.style.width = `${Math.max((n / max) * 100, 6)}%`;
        track.append(fill);
        bars.append(track);
      }
      box.append(bars);
    } else {
      const v = el("div", cell.accent && i !== heroIdx ? "v accent" : "v");
      if (cell.num != null) {
        const n = el("span");
        countUp(n, cell.num);
        v.append(n);
        if (cell.unit) v.append(cell.unit);
      } else {
        v.textContent = cell.value;
      }
      box.append(v);
    }
    if (cell.sub) box.append(el("div", "s", cell.sub));
    if (cell.series) {
      const cv = el("canvas", "spark");
      cv.setAttribute("aria-hidden", "true");
      box.append(cv);
      // canvas needs layout before it can be fitted — draw next frame
      requestAnimationFrame(() => sparkline(cv, cell.series));
    }
    grid.append(box);
  });
  root.append(grid);
  return root;
}

function outro() {
  const root = el("article", "card outro");
  if (!REDUCED) {
    const conf = el("div", "confetti");
    conf.setAttribute("aria-hidden", "true");
    for (let i = 0; i < 18; i++) {
      const p = el("i");
      p.style.left = `${(i * 61 + 13) % 100}%`;
      p.style.animationDelay = `${(i * 137) % 900}ms`;
      p.style.animationDuration = `${2200 + ((i * 271) % 1400)}ms`;
      conf.append(p);
    }
    root.append(conf);
  }
  root.append(el("h2", "big", "That's a wrap"));
  root.append(el("p", "sub", story.period.label));

  const actions = el("div", "actions");
  const replay = el("button", "btn ghost", "Replay");
  replay.addEventListener("click", () => go(0));
  actions.append(replay);

  const exportable = story.cards.filter((c) => isExportable(c) || c.private);
  if (exportable.length || HAS_SUMMARY) {
    const list = el("ul", "export-list");
    list.setAttribute("aria-label", "Export a card as PNG");
    if (HAS_SUMMARY) {
      const li = el("li", "full-report");
      li.append(el("span", "swatch"));
      const who = el("span", "name");
      const noun = story.period.type === "month" ? "month" : "year";
      who.append(el("span", "rep-name", `Full ${noun} report`));
      who.append(el("span", "rep-sub", "summary · everything on one card"));
      li.append(who);
      const dl = el("button", "btn ghost", "PNG");
      dl.setAttribute("aria-label", `Download the full ${noun} report as PNG`);
      dl.addEventListener("click", () => downloadSummaryPNG(story));
      li.append(dl);
      list.append(li);
    }
    for (const c of exportable) {
      const li = el("li");
      li.append(el("span", "name", c.headline));
      if (c.private) {
        li.classList.add("private");
        li.append(el("span", "chip", "off the record"));
      } else {
        const dl = el("button", "btn ghost", "PNG");
        dl.setAttribute("aria-label", `Download “${c.headline}” as PNG`);
        dl.addEventListener("click", () => downloadCardPNG(c, story.period.label));
        li.append(dl);
      }
      list.append(li);
    }
    root.append(actions, list);
  } else {
    root.append(actions);
  }
  return root;
}

const RENDERERS = {
  big_number: bigNumber,
  top_list: topList,
  superlative,
  streak,
  heatmap,
  comparison,
  intro,
  quiet,
  summary,
  outro,
};

/* ---------- deck assembly ---------- */

const deck = [{ template: "intro" }];
if (story.cards.length) {
  deck.push(...story.cards.filter((c) => RENDERERS[c.template]));
} else {
  deck.push({ template: "quiet" });
}
if (HAS_SUMMARY) deck.push({ template: "summary" });
deck.push({ template: "outro" });

/* ---------- player state ---------- */

const stage = document.querySelector(".stage");
const progress = document.querySelector(".progress");
const bg = document.getElementById("story-bg");
const bootLine = document.querySelector(".boot-line");
let index = -1;
let bgMode = null;

const BG = { intro: dotMatrix, quiet: dotMatrix, summary: dotMatrix, comparison: streamViz };

function chapterChrome(card) {
  if (bg) {
    const mode = BG[card.template] ? card.template : "particles";
    if (mode !== bgMode) {
      bgMode = mode;
      (BG[card.template] || particles)(bg);
    }
  }
  if (bootLine) {
    const line =
      card.template === "intro"
        ? "booting recap.engine ......... ok"
        : card.template === "summary"
          ? "render recap.summary ....... done"
          : card.template === "outro"
            ? "render complete — that's a wrap"
            : card.fact
              ? `read ${card.fact} ....... ok`
              : "";
    bootLine.replaceChildren();
    if (line) typeLine(bootLine, [line]);
  }
}

const segs = deck.map((_, i) => {
  const seg = el("button", "seg");
  seg.setAttribute("aria-label", `Go to card ${i + 1} of ${deck.length}`);
  seg.addEventListener("click", () => go(i));
  progress.append(seg);
  return seg;
});

function go(i) {
  if (i < 0 || i >= deck.length || i === index) return;
  index = i;
  segs.forEach((seg, j) => {
    seg.classList.toggle("done", j < i);
    seg.classList.toggle("current", j === i);
  });
  stage.replaceChildren();
  const card = RENDERERS[deck[i].template](deck[i]);
  card.classList.add("card-enter");
  stage.append(card);
  chapterChrome(deck[i]);
  // keep the chapter in the URL so refresh/back land on the same card
  history.replaceState(null, "", i ? `?c=${i}` : location.pathname);
}

const next = () => go(Math.min(index + 1, deck.length - 1));
const prev = () => go(Math.max(index - 1, 0));

document.querySelector(".nav-next").addEventListener("click", next);
document.querySelector(".nav-prev").addEventListener("click", prev);

document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); next(); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
  else if (e.key === "Home") go(0);
  else if (e.key === "End") go(deck.length - 1);
});

/* Tap-anywhere: left 40% of the stage goes back, the rest forward.
   Clicks on real controls (buttons, links) never navigate. */
let swiped = false;
stage.addEventListener("click", (e) => {
  if (swiped || e.target.closest("button, a")) return;
  if (e.clientX < window.innerWidth * 0.4) prev();
  else next();
});

/* Touch swipe: 30px horizontal threshold; suppress the click that follows. */
let touchX = null;
stage.addEventListener("pointerdown", (e) => { touchX = e.clientX; });
stage.addEventListener("pointerup", (e) => {
  if (touchX === null) return;
  const dx = e.clientX - touchX;
  touchX = null;
  swiped = Math.abs(dx) > 30;
  if (dx < -30) next();
  else if (dx > 30) prev();
});

const fromUrl = parseInt(new URLSearchParams(location.search).get("c"), 10);
go(Number.isInteger(fromUrl) && fromUrl > 0 && fromUrl < deck.length ? fromUrl : 0);
