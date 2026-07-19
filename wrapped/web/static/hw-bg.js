/* Shell chrome behaviour: dot-matrix background, data-stream cards,
   terminal typing lines. */

import { dotMatrix, streamViz, typeLine } from "./canvas-bg.js";

const bg = document.getElementById("hw-bg");
if (bg) dotMatrix(bg);
document.querySelectorAll("canvas.hw-stream").forEach(streamViz);
document
  .querySelectorAll(".hw-term[data-lines]")
  .forEach((el) => typeLine(el, JSON.parse(el.dataset.lines || "[]")));
