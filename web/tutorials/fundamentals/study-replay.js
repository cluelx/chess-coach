(function () {
  const studies = JSON.parse(document.querySelector("#study-replays").textContent);
  const symbols = { K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘" };
  const grades = { 1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!" };
  const colors = { G: "#439b55", R: "#d1584b", Y: "#d9ac3d", B: "#5489ce" };

  function el(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text) item.textContent = text;
    return item;
  }

  function button(text, action, className) {
    const item = el("button", className, text);
    item.type = "button";
    item.addEventListener("click", action);
    return item;
  }

  function notation(node) {
    return node.san.replace(/^[KQRBN]/, piece => symbols[piece]) +
      node.nags.map(nag => grades[nag] || "").join("");
  }

  function mount(host) {
    const chapters = studies[host.dataset.study];
    const boardHost = el("div", "study-board");
    const panel = el("div", "study-panel");
    const header = el("div", "study-header");
    const moves = el("div", "study-moves");
    const note = el("div", "study-note");
    const choices = el("div", "study-choices");
    const controls = el("div", "study-controls");
    const source = el("a", "", "Lichess 原章");
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    const title = el("strong");
    header.append(title, source);
    const board = new Board(boardHost, {
      fen: chapters[0].nodes[0].fen,
      pieceBase: "../../vendor/pieces/",
    });
    let nodes, current, selected, buttons, preferred;

    const first = button("⏮", () => show(0));
    const back = button("‹", () => show(nodes[current].parent));
    const next = button("›", () => show(preferred.get(current) ?? nodes[current].children[0]));
    const last = button("⏭", () => {
      let index = current;
      while (nodes[index].children.length) {
        index = preferred.get(index) ?? nodes[index].children[0];
      }
      show(index);
    });
    for (const [item, label] of [[first, "起始局面"], [back, "上一步"], [next, "下一步"], [last, "走到当前变化末尾"]]) {
      item.setAttribute("aria-label", label);
      item.title = label;
      controls.append(item);
    }

    if (chapters.length > 1) {
      const select = el("select");
      select.setAttribute("aria-label", "选择例题版本");
      chapters.forEach((chapter, index) => select.append(new Option(chapter.title, index)));
      select.addEventListener("change", () => load(Number(select.value)));
      header.insertBefore(select, source);
      title.hidden = true;
    }
    panel.append(header, moves, note, choices, controls);
    host.replaceChildren(boardHost, panel);
    host.tabIndex = 0;
    host.addEventListener("keydown", event => {
      if (event.target.closest("select")) return;
      const item = { ArrowLeft: back, ArrowRight: next, Home: first, End: last }[event.key];
      if (!item) return;
      event.preventDefault();
      if (!item.disabled) item.click();
    });

    function moveButton(index, numbered = false) {
      const node = nodes[index];
      const [, turn, , , , number] = nodes[node.parent].fen.split(" ");
      const prefix = numbered ? number + (turn === "w" ? ". " : "… ") : "";
      const item = button(prefix + notation(node), () => show(index), "study-move");
      buttons.set(index, item);
      return item;
    }

    function variation(index) {
      const line = el("div", "study-variation");
      while (index !== undefined) {
        const node = nodes[index];
        line.append(moveButton(index, true));
        for (const alternative of node.children.slice(1)) line.append(variation(alternative));
        index = node.children[0];
      }
      return line;
    }

    function load(chapterIndex) {
      const chapter = chapters[chapterIndex];
      nodes = chapter.nodes;
      buttons = new Map();
      preferred = new Map();
      selected = undefined;
      title.textContent = chapter.title;
      source.href = chapter.url;
      source.hidden = !chapter.url;
      board.setOrientation(chapter.orientation === "black" ? "black" : "white");
      moves.replaceChildren();
      let row;
      for (let parent = 0; nodes[parent].children.length; parent = nodes[parent].children[0]) {
        const [index, ...alternatives] = nodes[parent].children;
        const [, turn, , , , number] = nodes[parent].fen.split(" ");
        if (!row || turn === "w") {
          row = el("div", "study-row");
          row.append(el("span", "", number), el("span"), el("span"));
          moves.append(row);
        }
        row.children[turn === "w" ? 1 : 2].replaceWith(moveButton(index));
        if (alternatives.length) {
          for (const alternative of alternatives) moves.append(variation(alternative));
          row = undefined;
        }
      }
      if (!nodes[0].children.length) moves.append(el("p", "", "此例为起始局面"));
      moves.scrollTop = 0;
      show(0);
    }

    function show(index) {
      const position = nodes[index];
      current = index;
      for (let step = index; nodes[step].parent !== null; step = nodes[step].parent) {
        preferred.set(nodes[step].parent, step);
      }
      board.setFen(position.fen);
      board.setLastMove(position.from, position.to);
      board.setArrows([...position.comment.matchAll(/\[%cal ([^\]]+)\]/g)]
        .flatMap(match => match[1].split(","))
        .filter(mark => /^[GRYB][a-h][1-8][a-h][1-8]$/.test(mark))
        .map(mark => ({ from: mark.slice(1, 3), to: mark.slice(3), color: colors[mark[0]] })));
      const marks = [...position.comment.matchAll(/\[%csl ([^\]]+)\]/g)]
        .flatMap(match => match[1].split(","))
        .filter(mark => /^[GRYB][a-h][1-8]$/.test(mark));
      board.setMarks(marks.map(mark => mark.slice(1)));
      if (selected) selected.removeAttribute("aria-current");
      selected = buttons.get(index);
      if (selected) {
        selected.setAttribute("aria-current", "step");
        const viewport = moves.getBoundingClientRect();
        const target = selected.getBoundingClientRect();
        if (target.top < viewport.top || target.bottom > viewport.bottom) {
          moves.scrollTop += target.top - viewport.top - moves.clientHeight / 3;
        }
      }
      note.textContent = [position.startingComment, position.comment].join(" ")
        .replace(/\[%[^\]]+\]/g, "").trim();
      const continuation = preferred.get(index) ?? position.children[0];
      choices.replaceChildren(...(position.children.length > 1 ? position.children.map(child => {
        const item = button(notation(nodes[child]), () => show(child));
        item.setAttribute("aria-pressed", String(child === continuation));
        return item;
      }) : []));
      first.disabled = back.disabled = index === 0;
      next.disabled = last.disabled = !position.children.length;
    }

    load(0);
  }

  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.unobserve(entry.target);
      mount(entry.target);
    }
  }, { rootMargin: "320px" });
  document.querySelectorAll(".study-replay").forEach(host => observer.observe(host));
})();
