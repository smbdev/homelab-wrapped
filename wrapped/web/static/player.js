/* Story player: renders story-spec JSON as swipeable full-screen cards.
   Vanilla ES module, no dependencies, no build step. */

import { downloadCardPNG, isExportable } from "./export.js";

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const story = JSON.parse(document.getElementById("story-data").textContent);

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
  return root;
}

function streak(card) {
  const root = el("article", "card streak");
  const display = el("p", "display", "0");
  root.append(display);
  root.append(el("h2", null, card.headline));
  if (card.sub) root.append(el("p", "sub", card.sub));
  countUp(display, card.value);
  return root;
}

function topList(card) {
  const root = el("article", "card top-list");
  root.append(el("h2", null, card.headline));
  const list = el("ol", "toplist");
  (card.items || []).forEach((item, i) => {
    const li = el("li");
    li.style.setProperty("--i", i);
    li.append(el("span", "label", item.label), el("span", "value", item.value));
    list.append(li);
  });
  root.append(list);
  return root;
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
  return root;
}

function heatmap(card) {
  const root = el("article", "card heatmap-card");
  root.append(el("h2", null, card.headline));
  const scroll = el("div", "heatmap-scroll");
  const grid = el("div", "heatmap");
  grid.setAttribute("role", "img");
  grid.setAttribute("aria-label", `${card.headline}: activity per day`);

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
    for (let d = new Date(start); d <= last; d.setDate(d.getDate() + 1)) {
      const iso = localISO(d); // not toISOString(): that shifts to UTC and misses local dates
      const v = card.data[iso] || 0;
      const cell = el("div", "cell");
      if (v > 0) {
        const level = Math.max(1, Math.ceil((4 * v) / max));
        cell.classList.add(`l${level}`);
        cell.title = `${iso}: ${fmt(v)}`;
      }
      grid.append(cell);
    }
  }
  scroll.append(grid);
  root.append(scroll);
  if (card.sub) root.append(el("p", "sub", card.sub));
  return root;
}

function superlative(card) {
  return bigNumber(card); // same anatomy, different fact flavour
}

function intro() {
  const root = el("article", "card intro");
  root.append(el("p", "kicker", "Homelab Wrapped"));
  root.append(el("p", "display", story.period.label));
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

function outro() {
  const root = el("article", "card outro");
  root.append(el("h2", "big", "That's a wrap"));
  root.append(el("p", "sub", story.period.label));

  const actions = el("div", "actions");
  const replay = el("button", "btn ghost", "Replay");
  replay.addEventListener("click", () => go(0));
  actions.append(replay);

  const exportable = story.cards.filter((c) => isExportable(c) || c.private);
  if (exportable.length) {
    const list = el("ul", "export-list");
    list.setAttribute("aria-label", "Export a card as PNG");
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
  outro,
};

/* ---------- deck assembly ---------- */

const deck = [{ template: "intro" }];
if (story.cards.length) {
  deck.push(...story.cards.filter((c) => RENDERERS[c.template]));
} else {
  deck.push({ template: "quiet" });
}
deck.push({ template: "outro" });

/* ---------- player state ---------- */

const stage = document.querySelector(".stage");
const progress = document.querySelector(".progress");
let index = -1;

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

go(0);
