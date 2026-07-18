/* Shell chrome behaviour: dot-matrix background + terminal typing lines. */

import { dotMatrix, typeLine } from "./canvas-bg.js";

const bg = document.getElementById("hw-bg");
if (bg) dotMatrix(bg);
document
  .querySelectorAll(".hw-term[data-lines]")
  .forEach((el) => typeLine(el, JSON.parse(el.dataset.lines || "[]")));
