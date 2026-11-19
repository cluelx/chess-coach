(function () {
  const lines = JSON.parse(document.querySelector("#book-data").textContent);
  const replay = document.querySelector("#replay");
  const select = document.createElement("select");
  select.setAttribute("aria-label", "选择棋谱");
  lines.forEach((line, index) => select.append(new Option(line.title, index)));
  const host = document.createElement("div");
  const board = new Board(host, { fen: lines[0].positions[0].fen, pieceBase: "../../vendor/pieces/" });
  const controls = document.createElement("div");
  const previous = document.createElement("button");
  const next = document.createElement("button");
  const status = document.createElement("p");
  status.setAttribute("aria-live", "polite");
  previous.textContent = "上一步";
  next.textContent = "下一步";
  controls.append(previous, next);
  replay.append(select, host, controls, status);
  let selected = 0;
  let step = 0;
  function show(line, index) {
    selected = line;
    step = index;
    select.value = line;
    const positions = lines[line].positions;
    const position = positions[index];
    board.setFen(position.fen);
    board.setLastMove(position.from, position.to);
    previous.disabled = index === 0;
    next.disabled = index === positions.length - 1;
    status.textContent = `${index} / ${positions.length - 1} · ${position.san}`;
  }
  previous.addEventListener("click", () => show(selected, step - 1));
  next.addEventListener("click", () => show(selected, step + 1));
  select.addEventListener("change", () => show(Number(select.value), 0));
  document.querySelectorAll(".figure-replay").forEach(button => {
    button.addEventListener("click", () => {
      show(Number(button.dataset.line), Number(button.dataset.step));
      replay.parentElement.open = true;
      replay.scrollIntoView();
    });
  });
  const nav = document.querySelector("#contents");
  document.querySelectorAll("#chapters h4").forEach((heading, index) => {
    heading.id = "section-" + (index + 1);
    const link = document.createElement("a");
    link.href = "#" + heading.id;
    link.textContent = heading.textContent;
    nav.append(link);
  });
  show(0, 0);
})();
