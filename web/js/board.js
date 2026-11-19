/* 轻量棋盘组件：点击走子、合法着法提示、箭头标注、最后一步高亮。 */
(function () {
  const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];
  const PIECES = {
    p: "P", n: "N", b: "B", r: "R", q: "Q", k: "K",
  };

  class Board {
    constructor(el, opts = {}) {
      this.el = el;
      this.orientation = opts.orientation || "white";
      this.interactive = !!opts.interactive;
      this.onMove = opts.onMove || null;
      this.pieceBase = opts.pieceBase || "/static/vendor/pieces/";
      this.chess = new Chess(opts.fen || undefined);
      this.selected = null;
      this.lastMove = null;
      this.arrow = null;
      this.arrows = [];
      this.marks = [];
      this.hints = [];
      this.el.classList.add("board-wrap");

      const inner = document.createElement("div");
      inner.className = "board";
      this.inner = inner;
      this.el.innerHTML = "";
      this.el.appendChild(inner);

      this.arrowSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      this.arrowSvg.setAttribute("class", "arrow-layer");
      this.arrowSvg.setAttribute("viewBox", "0 0 100 100");
      this.arrowSvg.setAttribute("preserveAspectRatio", "none");
      inner.appendChild(this.arrowSvg);

      this._build();
      this.render();
    }

    _build() {
      this.squares = [];
      for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
          const sq = document.createElement("div");
          sq.className = "sq";
          sq.dataset.row = row;
          sq.dataset.col = col;
          this.inner.appendChild(sq);
          this.squares.push(sq);
        }
      }
    }

    _sqToRC(sq) {
      const file = FILES.indexOf(sq[0]);
      const rank = parseInt(sq[1], 10) - 1;
      if (this.orientation === "white") return { row: 7 - rank, col: file };
      return { row: rank, col: 7 - file };
    }

    _rcToSq(row, col) {
      const file = this.orientation === "white" ? col : 7 - col;
      const rank = this.orientation === "white" ? 7 - row : row;
      return FILES[file] + (rank + 1);
    }

    setFen(fen, { keepLast = false } = {}) {
      this.chess = new Chess(fen);
      if (!keepLast) this.lastMove = null;
      this.selected = null;
      this.hints = [];
      this.render();
    }

    get fen() { return this.chess.fen(); }
    get turn() { return this.chess.turn(); }

    setOrientation(o) {
      this.orientation = o;
      this.render();
    }

    setInteractive(on) {
      this.interactive = !!on;
      this.selected = null;
      this.hints = [];
      this.render();
    }

    setLastMove(from, to) {
      this.lastMove = from && to ? { from, to } : null;
      this.render();
    }

    setArrow(from, to, color) {
      this.arrow = from && to ? { from, to, color } : null;
      this.arrows = this.arrow ? [this.arrow] : [];
      this._drawArrow();
    }

    /** 多条箭头同时画：实际走法用暖色，建议走法用绿色。 */
    setArrows(list) {
      this.arrows = (list || []).filter((a) => a && a.from && a.to);
      this._drawArrow();
    }

    /** 高亮若干格子（教学局面里标出关键格）。 */
    setMarks(list) {
      this.marks = list || [];
      this.render();
    }

    clearArrow() { this.arrow = null; this.arrows = []; this._drawArrow(); }

    _drawArrow() {
      this.arrowSvg.innerHTML = "";
      const list = this.arrows && this.arrows.length ? this.arrows : (this.arrow ? [this.arrow] : []);
      const cx = (rc) => rc.col * 12.5 + 6.25;
      const cy = (rc) => rc.row * 12.5 + 6.25;
      for (const item of list) {
        const a = this._sqToRC(item.from);
        const b = this._sqToRC(item.to);
        const x1 = cx(a), y1 = cy(a), x2 = cx(b), y2 = cy(b);
        const angle = Math.atan2(y2 - y1, x2 - x1);
        const dist = Math.hypot(x2 - x1, y2 - y1);
        // 一步之内的箭头留短一点，否则整条箭头会被“箭头尖”吃掉
        const shorten = Math.min(5.4, dist * 0.34);
        const ex = x2 - Math.cos(angle) * shorten;
        const ey = y2 - Math.sin(angle) * shorten;
        const stroke = item.color === "red" ? "rgba(179,69,47,.82)" : "rgba(47,111,78,.80)";
        const fill = item.color === "red" ? "rgba(179,69,47,.88)" : "rgba(47,111,78,.86)";
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", x1); line.setAttribute("y1", y1);
        line.setAttribute("x2", ex); line.setAttribute("y2", ey);
        line.setAttribute("stroke", stroke);
        line.setAttribute("stroke-width", "1.9");
        line.setAttribute("stroke-linecap", "round");
        this.arrowSvg.appendChild(line);
        const head = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        const p1 = [x2, y2];
        const p2 = [x2 - Math.cos(angle - 0.42) * 3.4, y2 - Math.sin(angle - 0.42) * 3.4];
        const p3 = [x2 - Math.cos(angle + 0.42) * 3.4, y2 - Math.sin(angle + 0.42) * 3.4];
        head.setAttribute("points", [p1, p2, p3].map((p) => p.join(",")).join(" "));
        head.setAttribute("fill", fill);
        this.arrowSvg.appendChild(head);
      }
    }

    render() {
      const boardArr = this.chess.board();
      const turn = this.chess.turn();
      const kingSq = this._kingInCheckSquare(turn);
      for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
          const el = this.squares[row * 8 + col];
          const sqName = this._rcToSq(row, col);
          const isLight = (row + col) % 2 === 0;
          el.className = "sq " + (isLight ? "light" : "dark");
          el.dataset.sq = sqName;
          el.innerHTML = "";

          const piece = this.chess.get(sqName);
          if (piece) {
            const img = document.createElement("img");
            const color = piece.color === "w" ? "w" : "b";
            img.src = this.pieceBase + color + PIECES[piece.type].toUpperCase() + ".svg";
            img.alt = color + piece.type;
            el.appendChild(img);
          }
          if (this.lastMove && (this.lastMove.from === sqName || this.lastMove.to === sqName)) {
            el.classList.add("last");
          }
          if (this.selected === sqName) el.classList.add("sel");
          if (this.hints.includes(sqName)) {
            el.classList.add("hint");
            if (this.chess.get(sqName)) el.classList.add("cap");
          }
          if (kingSq === sqName) el.classList.add("check");
          if (this.marks && this.marks.includes(sqName)) el.classList.add("mark");

          // 坐标
          const showFile = this.orientation === "white" ? row === 7 : row === 0;
          const showRank = this.orientation === "white" ? col === 0 : col === 7;
          if (showFile) {
            const s = document.createElement("span");
            s.className = "coord f";
            s.textContent = sqName[0];
            el.appendChild(s);
          }
          if (showRank) {
            const s = document.createElement("span");
            s.className = "coord r";
            s.textContent = sqName[1];
            el.appendChild(s);
          }

          el.onclick = () => this._click(sqName);
        }
      }
      this._drawArrow();
    }

    _kingInCheckSquare(color) {
      if (!this.chess.in_check()) return null;
      const rows = this.chess.board();
      for (const r of rows) {
        for (const cell of r) {
          if (cell && cell.type === "k" && cell.color === color) {
            return cell.square;
          }
        }
      }
      return null;
    }

    _click(sqName) {
      if (!this.interactive) return;
      const mover = this.chess.turn();
      const piece = this.chess.get(sqName);
      if (this.selected) {
        if (sqName === this.selected) {
          this.selected = null; this.hints = []; this.render(); return;
        }
        const moved = this._tryMove(this.selected, sqName);
        if (moved) return;
        if (piece && piece.color === mover) {
          this._select(sqName);
          return;
        }
        this.selected = null; this.hints = []; this.render();
        return;
      }
      if (piece && piece.color === mover) this._select(sqName);
    }

    _select(sqName) {
      this.selected = sqName;
      const moves = this.chess.moves({ square: sqName, verbose: true });
      this.hints = moves.map((m) => m.to);
      this.render();
    }

    _tryMove(from, to) {
      const moves = this.chess.moves({ square: from, verbose: true }).filter((m) => m.to === to);
      if (!moves.length) return false;
      const needsPromo = moves.some((m) => m.promotion);
      if (needsPromo) {
        this._askPromotion(from, to);
        return true;
      }
      const mv = this.chess.move({ from, to });
      this.selected = null; this.hints = [];
      this.lastMove = { from, to };
      this.render();
      if (this.onMove) this.onMove(mv, from, to);
      return true;
    }

    _askPromotion(from, to) {
      const color = this.chess.turn() === "w" ? "w" : "b";
      const overlay = document.createElement("div");
      overlay.className = "promo";
      ["q", "r", "b", "n"].forEach((p) => {
        const b = document.createElement("button");
        const img = document.createElement("img");
        img.src = "/static/vendor/pieces/" + color + p.toUpperCase() + ".svg";
        b.appendChild(img);
        b.onclick = (e) => {
          e.stopPropagation();
          overlay.remove();
          const mv = this.chess.move({ from, to, promotion: p });
          this.selected = null; this.hints = [];
          this.lastMove = { from, to };
          this.render();
          if (this.onMove) this.onMove(mv, from, to);
        };
        overlay.appendChild(b);
      });
      this.el.appendChild(overlay);
    }

    undo() {
      const mv = this.chess.undo();
      this.selected = null; this.hints = []; this.lastMove = null;
      this.render();
      return mv;
    }
  }

  window.Board = Board;
})();
