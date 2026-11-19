(function () {
  const lines = JSON.parse(document.querySelector("#replay-data").textContent);
  const replay = document.querySelector("#replay");
  let lineIndex = 0;
  let ply = 0;

  function element(tag, text) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    return node;
  }

  const select = element("select");
  select.setAttribute("aria-label", "选择棋谱");
  lines.forEach((line, index) => select.append(new Option(line.title, index)));
  const boardHost = element("div");
  const board = new Board(boardHost, {
    fen: lines[0].positions[0].fen,
    pieceBase: "../../../vendor/pieces/",
  });
  const controls = element("div");
  controls.className = "board-tools";
  const previous = element("button", "上一步");
  const next = element("button", "下一步");
  const reset = element("button", "回到开头");
  const caption = element("p");
  caption.setAttribute("aria-live", "polite");
  controls.append(reset, previous, next);
  replay.append(element("h2", "棋谱回放"), select, boardHost, controls, caption);

  function show(index, step) {
    lineIndex = index;
    select.value = index;
    const positions = lines[index].positions;
    ply = step;
    const position = positions[ply];
    board.setFen(position.fen);
    board.setLastMove(position.from, position.to);
    previous.disabled = reset.disabled = ply === 0;
    next.disabled = ply === positions.length - 1;
    caption.textContent = `${ply} / ${positions.length - 1} · ${position.san}`;
  }

  select.addEventListener("change", () => show(Number(select.value), 0));
  reset.addEventListener("click", () => show(lineIndex, 0));
  previous.addEventListener("click", () => show(lineIndex, ply - 1));
  next.addEventListener("click", () => show(lineIndex, ply + 1));
  document.querySelectorAll("[data-placement]").forEach((marker) => {
    for (const [index, line] of lines.entries()) {
      const step = line.positions.findIndex(position => position.fen.split(" ")[0] === marker.dataset.placement);
      if (step < 0) continue;
      const jump = element("button", "从此局面回放");
      jump.className = "replay-jump";
      jump.addEventListener("click", () => {
        show(index, step);
        replay.scrollIntoView();
        select.focus({ preventScroll: true });
      });
      marker.replaceWith(jump);
      break;
    }
  });
  const shortcut = element("a", "打开棋谱回放");
  shortcut.href = "#replay";
  document.querySelector("main > h1").after(shortcut);
  show(0, 0);
})();
