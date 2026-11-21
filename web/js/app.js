/* 应用主逻辑：选档、课程、题库、复盘播放器。 */
(function () {
  const $ = (sel, root = document) => root.querySelector(sel);
  const app = $("#app");
  const toastEl = $("#toast");

  const state = { boot: null };

  function toast(msg, ms = 2400) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("show"), ms);
  }

  function requestError(message, payload, status) {
    const error = new Error(message || payload?.message || "请求失败");
    if (payload) error.payload = payload;
    if (status) error.status = status;
    return error;
  }

  async function responseError(res) {
    let payload = null;
    let message = res.statusText;
    try {
      const body = await res.json();
      if (body.detail && typeof body.detail === "object") {
        payload = body.detail;
        message = payload.message || message;
      } else if (body.detail) {
        message = body.detail;
        payload = { message };
      }
    } catch (e) {}
    return requestError(message, payload, res.status);
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw await responseError(res);
    return res.json();
  }

  const apiPost = (path, body) =>
    api(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

  // 流式接口：进度用 stage 事件，结果在 done 事件里。
  async function apiStream(path, body, { signal, onEvent } = {}) {
    const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(body), signal });
    if (!res.ok) throw await responseError(res);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result = null;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const line = chunk.split("\n").find(part => part.startsWith("data: "));
        if (!line) continue;
        let event;
        try { event = JSON.parse(line.slice(6)); } catch { continue; }
        if (event.type === "stage") onEvent?.(event.text);
        else if (event.type === "done") result = event.data;
        else if (event.type === "error") throw requestError(event.message, event.error);
      }
    }
    if (!result) throw requestError("没有收到可用的回复，请重试",
      {message: "没有收到可用的回复，请重试", code: "empty_stream", stage: "stream", retryable: true});
    return result;
  }

  function el(tag, cls, html) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  const LEVEL_NAMES = { 1: "入门", 2: "进阶", 3: "高级" };
  const SEV_CLASS = (s) => (s >= 90 ? "s90" : s >= 60 ? "s60" : s >= 40 ? "s40" : "s0");
  const PIECE_CN = { p: "兵", n: "马", b: "象", r: "车", q: "后", k: "王" };

  // ------------------------------------------------------------------
  // 启动
  // ------------------------------------------------------------------
  async function boot() {
    state.boot = await api("/api/bootstrap");
    renderWho();
    for (const item of document.querySelectorAll('[data-nav="coach"]')) {
      item.style.display = state.boot.tutorials_published ? "" : "none";
    }
    $("#dbinfo").textContent = `题库 ${state.boot.puzzle_total.toLocaleString()} 题`;
  }

  function renderWho() {
    if (!state.boot) return;
    $("#who").innerHTML =
      `<span class="pill green">${LEVEL_NAMES[state.boot.learner.level]}</span>` +
      `<span>今日 <b>${state.boot.stats.today_attempts}</b> 题</span>`;
  }

  const routes = [
    [/^#\/home$/, viewHome],
    [/^#\/learning$/, viewLearning],
    [/^#\/settings$/, viewLearningSettings],
    [/^#\/favorites$/, viewFavorites],
    [/^#\/material\/([\w-]+)$/, viewMaterial],
    [/^#\/coach(?:\?.*)?$/, viewCoach],
    [/^#\/library(?:\?.*)?$/, viewLibrary],
    [/^#\/openings(?:\/([a-z]+))?$/, viewOpenings],
    [/^#\/courses(?:\/(\d))?$/, viewCourses],
    [/^#\/lesson\/([\w-]+)$/, viewLesson],
    [/^#\/practice(?:\?.*)?$/, viewPractice],
    [/^#\/review$/, viewReview],
  ];

  async function route() {
    const hash = location.hash || "#/home";
    document.body.classList.remove("learning-mode");
    if (rvCloser) { rvCloser(); rvCloser = null; }
    document.querySelectorAll(".nav a").forEach((a) => a.classList.remove("active"));
    if (!state.boot.tutorials_published && /^#\/(?:lesson|coach)(?:[/?]|$)/.test(hash)) {
      app.replaceChildren(label("p", "empty", "教程正在校对，暂时下架。"), link("去题库", "#/library"));
      return;
    }
    for (const [re, fn] of routes) {
      const m = hash.match(re);
      if (m) {
        const key = hash.split("/")[1].split("?")[0];
        const nav = document.querySelector(`.nav a[data-nav="${key}"]`);
        if (nav) nav.classList.add("active");
        app.innerHTML = "";
        try {
          await fn(...m.slice(1));
        } catch (e) {
          document.body.classList.remove("learning-mode");
          if (location.hash === hash || (!location.hash && hash === "#/home")) {
            app.replaceChildren(label("div", "empty", "出错了：" + e.message));
          }
        }
        window.scrollTo(0, 0);
        return;
      }
    }
    location.hash = "#/home";
  }

  // ------------------------------------------------------------------
  // 界面组件
  // ------------------------------------------------------------------
  function label(tag, cls, value) {
    const n = el(tag, cls);
    n.textContent = value;
    return n;
  }

  function link(value, href) {
    const n = label("a", "btn sm", value);
    n.href = href;
    return n;
  }

  function player(examples) {
    const wrap = el("div", "card learning-player");
    const chooser = el("select");
    chooser.setAttribute("aria-label", "选择变化");
    examples.forEach((ex, i) => chooser.add(new Option(ex.title, i)));
    const boardHost = el("div");
    const note = label("p", "muted", "");
    const controls = el("div", "board-tools");
    const prev = label("button", "btn sm", "上一步");
    const next = label("button", "btn sm primary", "下一步");
    const reset = label("button", "btn sm", "重头看");
    const count = label("span", "muted", "");
    const sequence = el("div", "board-tools");
    const source = el("p", "muted");
    let i = 0;
    let ex = examples[0];
    const board = new Board(boardHost, {fen: ex.fen});
    function render(step) {
      i = step;
      board.setFen(ex.fen);
      board.setMarks(ex.marks || []);
      let last = null;
      for (const m of ex.moves.slice(0, i)) {
        last = m.uci ? board.chess.move({from:m.uci.slice(0,2),to:m.uci.slice(2,4),promotion:m.uci[4]}) : board.chess.move(m.san);
      }
      if (last) board.setLastMove(last.from,last.to);
      count.textContent = i + " / " + ex.moves.length;
      note.textContent = (ex.moves[i-1] && ex.moves[i-1].comment) || ex.note;
      prev.disabled = i === 0;
      next.disabled = i >= ex.moves.length;
      Array.from(sequence.children).forEach((b,k) => b.classList.toggle("primary",k+1===i));
    }
    function change() {
      ex = examples[Number(chooser.value)];
      sequence.replaceChildren();
      ex.moves.forEach((m,k) => {
        const b = label("button","btn sm",m.san);
        b.onclick = () => render(k+1);
        sequence.append(b);
      });
      source.replaceChildren();
      if (ex.source && ex.source.url) {
        const a = link(ex.source.label || "查看来源", ex.source.url);
        a.target = "_blank"; a.rel = "noopener";
        source.append(a);
      } else source.textContent = "教学构造局面";
      render(0);
    }
    chooser.onchange = change;
    controls.append(prev,next,reset,count);
    wrap.append(chooser,boardHost,controls,sequence,note,source);
    prev.onclick=()=>render(i-1); next.onclick=()=>render(i+1); reset.onclick=()=>render(0);
    change();
    return wrap;
  }

  function positionExamples(items) {
    return (items || []).filter(item => item && (item.fen || item.placement)).map((item, index) => ({
      title: item.title || "图示 " + (index + 1),
      fen: item.fen || item.placement + " w - - 0 1",
      moves: Array.isArray(item.moves) ? item.moves : [],
      note: item.note || (!item.fen && item.placement ? "仅棋子摆放，行棋方与历史未确认。" : ""),
      source: item.source,
    }));
  }

  function learningBoardGallery(examples) {
    const wrap = el("div", "learning-board-browser");
    if (!examples.length) return wrap;
    const head = el("div", "learning-board-head");
    const title = label("h3", "learning-board-title", "");
    const pager = el("div", "learning-board-pager");
    const prevDiagram = label("button", "btn sm", "上一图");
    const nextDiagram = label("button", "btn sm", "下一图");
    const diagramCount = label("span", "learning-page-count", "");
    prevDiagram.type = nextDiagram.type = "button";
    pager.append(prevDiagram, diagramCount, nextDiagram);
    head.append(title, pager);

    const boardHost = el("div", "learning-board-host");
    const controls = el("div", "board-tools learning-move-controls");
    const prev = label("button", "btn sm", "上一步");
    const next = label("button", "btn sm primary", "下一步");
    const reset = label("button", "btn sm", "重头看");
    const count = label("span", "learning-step-count", "");
    const sequence = el("div", "learning-san-list");
    const note = label("p", "learning-board-note", "");
    const source = el("p", "muted");
    controls.append(prev, reset, next, count);
    wrap.append(head, boardHost, controls, sequence, note, source);

    let current = 0;
    const steps = examples.map(() => 0);
    const board = new Board(boardHost, {fen: examples[0].fen});

    function currentExample() {
      return examples[current];
    }

    function render() {
      const ex = currentExample();
      const step = steps[current];
      board.setFen(ex.fen);
      board.setMarks(ex.marks || []);
      let last = null;
      for (const move of ex.moves.slice(0, step)) {
        try {
          last = move.uci
            ? board.chess.move({from: move.uci.slice(0, 2), to: move.uci.slice(2, 4), promotion: move.uci[4]})
            : board.chess.move(typeof move === "string" ? move : move.san);
        } catch (error) {
          break;
        }
      }
      if (last) board.setLastMove(last.from, last.to);
      count.textContent = step + " / " + ex.moves.length + " 步";
      const move = ex.moves[step - 1];
      note.textContent = (move && move.comment) || ex.note || ex.title;
      prev.disabled = step === 0;
      next.disabled = step >= ex.moves.length;
      Array.from(sequence.children).forEach((button, index) =>
        button.classList.toggle("primary", index + 1 === step));
    }

    function buildSequence() {
      const ex = currentExample();
      sequence.replaceChildren();
      ex.moves.forEach((move, index) => {
        const button = label("button", "san-chip", typeof move === "string" ? move : move.san);
        button.type = "button";
        button.onclick = () => {
          steps[current] = index + 1;
          render();
        };
        sequence.append(button);
      });
      sequence.hidden = ex.moves.length === 0;
    }

    function show(index) {
      current = Math.max(0, Math.min(examples.length - 1, index));
      const ex = currentExample();
      title.textContent = ex.title;
      diagramCount.textContent = "图示 " + (current + 1) + " / " + examples.length;
      prevDiagram.disabled = current === 0;
      nextDiagram.disabled = current === examples.length - 1;
      source.replaceChildren();
      if (ex.source && ex.source.url) {
        const anchor = link(ex.source.label || "查看来源", ex.source.url);
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        source.append(anchor);
      } else {
        source.textContent = ex.moves.length ? "来源局面，可逐步回放" : "来源局面";
      }
      buildSequence();
      render();
    }

    prevDiagram.onclick = () => show(current - 1);
    nextDiagram.onclick = () => show(current + 1);
    prev.onclick = () => {
      steps[current] = Math.max(0, steps[current] - 1);
      render();
    };
    next.onclick = () => {
      steps[current] = Math.min(examples[current].moves.length, steps[current] + 1);
      render();
    };
    reset.onclick = () => {
      steps[current] = 0;
      render();
    };
    pager.hidden = examples.length < 2;
    wrap.goTo = show;
    show(0);
    return wrap;
  }

  function sourceCacheBadge(cache, onRefresh) {
    if (!cache) return null;
    const row = el("div", "learning-cache");
    const fetched = new Date(cache.fetched_at || "");
    const when = Number.isNaN(fetched.getTime()) ? "" :
      fetched.toLocaleString("zh-CN", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"});
    const text = label("span", "", (cache.hit ? "已使用缓存" : "已解析并缓存") + (when ? " · " + when : ""));
    row.append(text);
    if (onRefresh) {
      const refresh = label("button", "btn sm ghost", "重新解析");
      refresh.type = "button";
      refresh.onclick = async () => {
        refresh.disabled = true;
        refresh.textContent = "解析中…";
        try {
          await onRefresh();
        } finally {
          refresh.disabled = false;
          refresh.textContent = "重新解析";
        }
      };
      row.append(refresh);
    }
    return row;
  }

  function errorInfo(error) {
    const payload = error?.payload || {};
    return {
      message: error?.message || payload.message || "执行失败",
      code: payload.code || "request_error",
      stage: payload.stage || "request",
      operation: payload.operation || "",
      retryable: payload.retryable !== false,
      request_id: payload.request_id || "",
      elapsed_ms: payload.elapsed_ms,
      details: payload.details || "",
      status: error?.status || "",
    };
  }

  function learningErrorPanel(info, onRetry) {
    const wrap = el("div", "learning-error");
    const heading = el("div", "learning-error-head");
    heading.append(label("span", "learning-error-mark", "!"),
                   label("h3", "", "执行失败"));
    wrap.append(heading, label("p", "learning-error-message", info.message));
    const actions = el("div", "learning-error-actions");
    if (onRetry && info.retryable) {
      const retry = label("button", "btn sm primary", "重试");
      retry.type = "button";
      retry.onclick = onRetry;
      actions.append(retry);
    }
    if (info.request_id) {
      const copy = label("button", "btn sm ghost", "复制请求 ID");
      copy.type = "button";
      copy.onclick = async () => {
        try { await navigator.clipboard.writeText(info.request_id); copy.textContent = "已复制"; }
        catch { copy.textContent = info.request_id; }
      };
      actions.append(copy);
    }
    const details = el("details", "learning-error-details");
    details.append(label("summary", "", "查看技术详情"));
    const facts = el("dl", "learning-error-facts");
    for (const [name, value] of [
      ["错误码", info.code],
      ["失败阶段", info.stage],
      ["操作", info.operation || "—"],
      ["请求 ID", info.request_id || "—"],
      ["耗时", info.elapsed_ms != null ? info.elapsed_ms + " ms" : "—"],
      ["HTTP 状态", info.status || "—"],
      ["可重试", info.retryable ? "是" : "否"],
    ]) {
      facts.append(label("dt", "", name), label("dd", "", String(value)));
    }
    details.append(facts);
    if (info.details) {
      const raw = el("pre", "learning-error-log");
      raw.textContent = info.details;
      details.append(label("p", "learning-error-log-label", "模型 / CLI 原始诊断"), raw);
    }
    wrap.append(actions, details);
    return wrap;
  }

  async function viewOpenings(id) {
    const page = el("section");
    app.append(page);
    const data = await api("/api/openings");
    const o = data.find(x=>x.id===id);
    page.append(label("h1","",o ? o.name : "经典开局与变化"));
    if (!o) {
      const list = el("div","learning-grid");
      for (const item of data) {
        const card = el("article","card learning-card");
        card.append(label("h3","",item.name),label("p","muted",item.summary),
                    link(item.branches.length+" 条变化","#/openings/"+item.id));
        list.append(card);
      }
      page.append(list);
      return;
    }
    page.append(label("p","lead",o.summary),link("全部开局","#/openings"),player(o.branches),
                label("p","muted","逐手回放时，试着指出双方控制了哪些中心格、哪些棋子已经出动。"),
                link("这个开局的实战战术题", "#/library?opening=" + encodeURIComponent(o.practice_tag)));
  }

  async function viewLibrary() {
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    const page = el("section");
    page.append(label("h1", "", state.boot.tutorials_published ? "知识点与题库" : "练习题库"));
    if (state.boot.tutorials_published) page.append(link("经典开局与变化", "#/openings"));
    app.append(page);
    const requestedKp = params.get("kp");
    const kp = state.boot.kps.some(k => k.id === requestedKp) ? requestedKp : "";
    if (kp) {
      const r = await api("/api/knowledge/"+encodeURIComponent(kp));
      const detail = el("div","card learning-card");
      detail.append(label("h2","",r.kp.name), label("p","lead",r.kp.summary));
      for (const p of r.kp.explain || []) detail.append(label("p","",p));
      if (r.kp.mistake) detail.append(label("p","muted",r.kp.mistake));
      r.lessons.forEach(l=>detail.append(link(l.title,l.href)));
      page.append(detail,link("全部知识点","#/library"));
    } else if (state.boot.tutorials_published) {
      const grid=el("div","learning-grid");
      state.boot.kps.forEach(k=>{
        const card=el("div","card learning-card");
        card.append(link(k.name,"#/library?kp="+encodeURIComponent(k.id)),label("p","muted",k.summary));
        grid.append(card);
      });
      page.append(grid);
    }
    const filters=el("form","board-tools");
    const theme=el("select"); theme.setAttribute("aria-label","战术主题");
    theme.add(new Option("全部主题",""));
    const themeNames=new Set(state.boot.practice_themes);
    for(const t of [...themeNames].sort()) theme.add(new Option(themeCN(t),t));
    const requestedTheme = params.get("theme");
    if (themeNames.has(requestedTheme)) theme.value = requestedTheme;
    const studied=el("select"); studied.setAttribute("aria-label","做题状态");
    [["全部进度",""],["未做","new"],["做过","seen"]].forEach(([n,v])=>studied.add(new Option(n,v)));
    const opening=el("input"); opening.placeholder="开局标签，如 French";
    opening.value = params.get("opening") || "";
    const low=el("input"), high=el("input");
    low.type=high.type="number"; low.placeholder="最低难度"; high.placeholder="最高难度";
    const submit=label("button","btn sm primary","筛选"); submit.type="submit";
    filters.append(theme,studied,opening,low,high,submit);
    const status=label("p","muted","");
    const result=el("div","learning-grid");
    const more=label("button","btn sm","下一批");
    page.append(label("h2","","题库"),filters,status,result,more);
    let cursor="", token=0;
    async function fetchPage(reset) {
      const request=++token;
      if(reset){cursor="";result.replaceChildren();}
      more.disabled=true;
      const q=new URLSearchParams({kp,theme:theme.value,studied:studied.value,
        opening:opening.value,lo:low.value||"0",hi:high.value||"4000",after:cursor});
      try {
        const data=await api("/api/library?"+q);
        if(request!==token)return;
        status.textContent=data.total ? "共 "+data.total+" 道题" : "没有符合当前筛选的题目";
        for(const item of data.items){
          const b=label("button","btn sm","#"+item.id+" · "+item.rating+" · "+item.themes.split(" ").map(themeCN).join("、"));
          b.onclick=async()=>{try{openPuzzleModal(await api("/api/puzzles/"+encodeURIComponent(item.id)),{kpIds:kp?[kp]:[]});}catch(e){toast(e.message);}};
          result.append(b);
        }
        cursor=data.next||""; more.hidden=!cursor;
      } catch(e){if(request===token) status.textContent=e.message;}
      finally {if(request===token)more.disabled=false;}
    }
    filters.onsubmit=e=>{e.preventDefault();fetchPage(true);};
    more.onclick=()=>fetchPage(false);
    await fetchPage(true);
  }

  function learningItems() {
    try {
      return JSON.parse(localStorage.getItem("chess-coach-learning-v1") || "{}");
    } catch {
      return {};
    }
  }

  function saveLearningItem(item) {
    const items = learningItems();
    items[item.id] = item;
    localStorage.setItem("chess-coach-learning-v1", JSON.stringify(items));
  }

  function learningCards(host, items) {
    for (const item of items) {
      const card = el("article", "card learning-card");
      card.append(label("h3", "", item.title));
      if (item.summary) card.append(label("p", "muted", item.summary));
      const open = label("button", "btn sm primary", "打开学习");
      open.onclick = () => {
        state.material = item;
        location.hash = "#/material/" + item.id;
      };
      card.append(open);
      if (item.practice) card.append(link("本站练习", item.practice));
      host.append(card);
    }
  }

  async function viewLearning() {
    const page = el("section");
    const review = state.learningReview;
    state.learningReview = null;
    const form = el("form", "learning-composer");
    const input = el("textarea");
    input.placeholder = "例如：我想学怎么识别牵制";
    input.setAttribute("aria-label", "学习需求");
    input.maxLength = 500;
    const submit = label("button", "btn primary", "找学习资料");
    const results = el("div", "learning-grid");
    const status = label("p", "learning-composer-status", "");
    status.setAttribute("role", "status");
    const photo = el("input");
    photo.type = "file";
    photo.accept = "image/png,image/jpeg,image/webp,.pgn,.fen";
    photo.setAttribute("aria-label", "添加学习附件");
    const attachmentName = label("span", "", "添加附件");
    const attachment = el("label", "learning-attachment");
    attachment.append(attachmentName, photo);
    page.append(label("h1", "", "学习助手"),
                label("p", "lead", "输入想学的知识点，先找本站资料，再补充网络来源。"));
    app.append(page);
    if (review) {
      const item = {id: crypto.randomUUID(), title: "复盘 · 第 " + review.move_no + " 回合",
                    fen: review.fen, moves: [], review: {played: review.uci, recommended: review.best?.uci}};
      learningCards(results, [item]);
      status.textContent = "已带入这步复盘。";
      page.append(status, results);
      page.append(link("返回复盘", "#/review"));
      if (item.review.recommended && item.review.recommended !== item.review.played) {
        status.textContent = "正在核对本地历史复盘…";
        try {
          const matches = await apiPost("/api/learning/review-matches",
            {fen: item.fen, ...item.review, review_id: review.reviewId});
          status.textContent = matches.length ? "找到局面和错误走法均一致的历史复盘。" :
            "本地历史复盘里未找到局面和错误走法均一致的案例。";
          learningCards(results, matches.map(match => ({...match, id: crypto.randomUUID()})));
        } catch (error) {
          status.textContent = error.message;
        }
      }
      return;
    }

    document.body.classList.add("learning-mode");
    page.classList.add("learning-workspace");
    const head = el("header", "learning-head");
    const heading = el("div");
    heading.append(label("h1", "", "学习助手"),
                   label("p", "learning-head-sub", "先查本站资料，再按需读取网页。棋盘与解释会并排显示。"));
    head.append(heading, link("模型与搜索设置", "#/settings"));
    const conversation = el("div", "learning-conversation");
    conversation.setAttribute("role", "log");
    conversation.setAttribute("aria-live", "polite");
    if (!state.learningTurns) {
      try { state.learningTurns = JSON.parse(sessionStorage.getItem("chess-learning-turns") || "[]"); }
      catch { state.learningTurns = []; }
    }
    const turns = state.learningTurns;
    const stop = label("button", "btn", "停止");
    stop.type = "button";
    stop.hidden = true;
    let activeRequest;
    stop.onclick = () => activeRequest?.abort();
    const composerFoot = el("div", "learning-composer-foot");
    input.placeholder = "说说你想学什么，也可以粘贴网页链接、PGN 或 FEN";
    input.maxLength = 100000;
    submit.textContent = "发送 ↑";
    photo.addEventListener("change", () => {
      attachmentName.textContent = photo.files[0]?.name || "添加附件";
    });
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 150) + "px";
    });
    composerFoot.append(attachment, status, stop, submit);
    form.append(input, composerFoot);
    page.replaceChildren(head, conversation, form);
    if (!turns.length) {
      const empty = el("div", "learning-empty");
      empty.append(label("p", "learning-empty-title", "从一个问题开始"),
                   label("p", "", "例如：解释牵制怎么识别，或粘贴一个开局课程网页。"));
      conversation.append(empty);
    }

    function persistTurns() {
      try {
        sessionStorage.setItem("chess-learning-turns", JSON.stringify(turns.slice(-8).map(entry => ({
          ...entry, items: (entry.items || []).map(({original, ...item}) => item)
        }))));
      } catch { /* The conversation remains available in memory. */ }
    }

    function scrollToLatest() {
      requestAnimationFrame(() => {
        conversation.scrollTop = conversation.scrollHeight;
      });
    }

    function retryQuestion(question) {
      input.value = question;
      input.focus();
      form.requestSubmit();
    }

    function showTurn(turn, options = {}) {
      conversation.querySelector(".learning-empty")?.remove();
      const block = el("section", "learning-turn");
      const question = el("div", "learning-question");
      question.append(label("span", "learning-question-mark", "你"),
                      label("p", "", turn.question));
      block.append(question);

      if (turn.error) {
        block.append(learningErrorPanel(turn.error,
          options.onRetry || (() => retryQuestion(turn.question))));
        conversation.append(block);
        scrollToLatest();
        return block;
      }

      const items = turn.items || [];
      const positionItems = items.filter(item => item?.kind === "position" ||
        /^棋盘\s*\d/.test(item?.title || ""));
      const resources = items.filter(item => !positionItems.includes(item));
      const answer = el("div", "learning-answer");
      const copy = el("div", "learning-result-copy");
      const split = el("div", positionItems.length ? "learning-result-split" : "learning-result-single");

      if (positionItems.length) {
        const boardPane = el("div", "learning-board-pane");
        const gallery = learningBoardGallery(positionExamples(positionItems));
        boardPane.append(gallery);
        split.append(boardPane);
      }
      if (turn.cache) copy.append(sourceCacheBadge(turn.cache));
      if (turn.reply) copy.append(label("p", "learning-reply", turn.reply));
      if (turn.notice) copy.append(label("p", "learning-notice", turn.notice));
      if (positionItems.length > 1) {
        const index = el("div", "learning-board-index");
        index.append(label("p", "learning-block-title", "本页图示"));
        positionItems.forEach((item, i) => {
          const jump = label("button", "learning-board-jump",
            (i + 1) + " · " + (positionExamples([item])[0]?.title || "图示"));
          jump.type = "button";
          jump.onclick = () => {
            split.querySelector(".learning-board-browser")?.goTo?.(i);
          };
          index.append(jump);
        });
        copy.append(index);
      }
      if (resources.length) {
        const resourceList = el("div", "learning-resources");
        learningCards(resourceList, resources);
        copy.append(resourceList);
      }
      split.append(copy);
      answer.append(split);
      block.append(answer);
      conversation.append(block);
      scrollToLatest();
      return block;
    }

    turns.forEach(turn => showTurn(turn));
    scrollToLatest();
    input.addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    form.onsubmit = async event => {
      event.preventDefault();
      const question = input.value.trim();
      const file = photo.files[0];
      if (!question && !file) return;
      if (file?.size > 5000000) {
        status.textContent = "请选择 5 MB 以下的附件。";
        return;
      }
      submit.disabled = true;
      stop.hidden = false;
      activeRequest = new AbortController();
      status.textContent = "正在理解需求…";
      try {
        const catalog = new Map(Object.values(learningItems()).map(item => [item.id, item]));
        for (const [topic, topics] of SOURCE_TOPICS) {
          for (const [title, url, theme, source] of topics) {
            const id = "topic-" + encodeURIComponent(title).replaceAll("%", "");
            catalog.set(id, catalog.get(id) || {id, title, url, topic, summary: source,
              practice: state.boot.practice_themes.includes(theme) ? "#/library?theme=" + encodeURIComponent(theme) : null});
          }
        }
        if (!file && !/^https?:/.test(question)) {
          const openings = await api("/api/openings").catch(() => []);
          for (const opening of openings) {
            const id = "opening-" + opening.id;
            catalog.set(id, catalog.get(id) || {id, title: opening.name, topic: "开局",
              summary: opening.summary, fen: opening.branches[0]?.fen, moves: opening.branches[0]?.moves,
              practice: "#/openings/" + opening.id});
          }
        }
        let message = question;
        let original;
        if (file) {
          if (/\.(pgn|fen)$/i.test(file.name)) message = (await file.text()).trim();
          else original = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
          });
        }
        const url = /^https?:\/\/\S+$/.test(message) ? message : undefined;
        const data = await apiStream("/api/learning/chat/stream", {
          message: message || file?.name, image: original?.split(",")[1],
          history: turns.filter(turn => !turn.error).slice(-8).map(turn => ({user: turn.question, assistant: turn.reply})),
          catalog: [...catalog.values()].slice(0, 120).map(({id,title,topic}) => ({id,title,topic}))
        }, {signal: activeRequest.signal, onEvent: text => { status.textContent = text; }});
        const items = (data.ids || []).map(id => catalog.get(id)).filter(Boolean);
        items.push(...(data.sources || []).map(item => ({...item, id: crypto.randomUUID(), remote: true})));
        if (url) {
          items.push({id: crypto.randomUUID(), title: "来源资料", url, summary: data.reply});
        }
        items.push(...(data.positions || []).map((item, index) => ({...item, kind: "position", original,
          id: crypto.randomUUID(), title: "棋盘 " + (index + 1), url})));
        const turn = {question: question || file.name, reply: data.reply, items,
          notice: data.notice, cache: data.cache, sourceUrl: url};
        turns.push(turn);
        persistTurns();
        showTurn(turn);
        input.value = "";
        photo.value = "";
        attachmentName.textContent = "添加附件";
        input.style.height = "";
        status.textContent = "";
      } catch (error) {
        if (error.name === "AbortError") {
          status.textContent = "已停止等待。";
        } else {
          const turn = {question: question || file?.name || "本次请求", reply: "", items: [],
                        error: errorInfo(error)};
          turns.push(turn);
          persistTurns();
          showTurn(turn, {onRetry: () => retryQuestion(turn.question)});
          status.textContent = "";
        }
      } finally {
        submit.disabled = false;
        stop.hidden = true;
      }
    };
  }

  async function viewLearningSettings() {
    const page = el("section");
    page.append(label("h1", "", "学习助手设置"));
    app.append(page);
    const config = await api("/api/learning/settings");
    const form = el("form", "card learning-settings");
    const provider = el("select");
    provider.add(new Option("CodeBuddy CLI", "codebuddy"));
    provider.add(new Option("自定义 API", "api"));
    provider.value = config.provider;
    function field(parent, title, value = "", password = false, placeholder = "") {
      const wrapper = label("label", "", title);
      const input = el("input");
      input.value = value;
      input.type = password ? "password" : "text";
      input.placeholder = placeholder;
      if (password) input.autocomplete = "new-password";
      wrapper.append(input);
      parent.append(wrapper);
      return input;
    }
    const providerLabel = label("label", "", "接入方式");
    providerLabel.append(provider);
    const cli = el("fieldset");
    cli.append(label("legend", "", "CodeBuddy CLI"));
    const cliModel = field(cli, "模型", config.cli_model);
    const effortLabel = label("label", "", "推理档位");
    const cliEffort = el("select");
    for (const level of ["minimal", "low", "medium", "high", "xhigh", "max"]) cliEffort.add(new Option(level, level));
    cliEffort.value = config.cli_effort || "high";
    effortLabel.append(cliEffort);
    cli.append(effortLabel,
      label("p", "muted", config.cli_detected ? "已检测到本机 CLI。一次运行里可联网搜索、读取网页、查本地资料并核验棋谱。" : "未检测到 CodeBuddy CLI。"),
      label("p", "muted", "模型 ID 需与 CLI 支持列表一致，如 deepseek-v4.1-flash、deepseek-v4-pro。"));
    const custom = el("fieldset");
    custom.append(label("legend", "", "自定义 API"));
    const base = field(custom, "API Base URL", config.api_base);
    const model = field(custom, "模型", config.api_model);
    const apiKey = field(custom, "模型 API Key", "", true, config.has_api_key ? "已配置，留空保留" : "请输入密钥");
    const brave = field(custom, "Brave Search API Key", "", true, config.has_brave_key ? "已配置，留空保留" : "需要联网时填写");
    const status = label("p", "muted", "");
    status.setAttribute("role", "status");
    function update() {
      cli.hidden = provider.value !== "codebuddy";
      custom.hidden = provider.value !== "api";
    }
    provider.onchange = update;
    update();
    async function save() {
      await apiPost("/api/learning/settings", {provider: provider.value, cli_model: cliModel.value.trim(),
        cli_effort: cliEffort.value,
        api_base: base.value.trim(), api_model: model.value.trim(),
        api_key: apiKey.value || null, brave_key: brave.value || null});
      if (apiKey.value) apiKey.placeholder = "已配置，留空保留";
      if (brave.value) brave.placeholder = "已配置，留空保留";
      apiKey.value = brave.value = "";
    }
    const saveButton = label("button", "btn primary", "保存设置");
    form.onsubmit = async event => {
      event.preventDefault();
      try { await save(); status.textContent = "已保存，新请求立即生效。"; }
      catch (error) { status.textContent = error.message; }
    };
    form.append(providerLabel, cli, custom, saveButton);
    for (const [name, title] of [["model", "保存并测试模型"], ["search", "保存并测试搜索"]]) {
      const button = label("button", "btn", title);
      button.type = "button";
      button.onclick = async () => {
        button.disabled = true;
        status.textContent = "正在测试…";
        try { await save(); status.textContent = (await apiPost("/api/learning/test/" + name, {})).message; }
        catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; }
      };
      form.append(button);
    }
    form.append(status);
    page.append(form);
  }

  function viewFavorites() {
    app.append(label("h1", "", "我的收藏"));
    const items = Object.values(learningItems());
    const grid = el("div", "learning-grid");
    if (!items.length) grid.append(label("p", "muted", "在资料页收藏内容后，可以在这里重新打开。"));
    learningCards(grid, items);
    app.append(grid);
  }

  function viewMaterial(id) {
    const saved = learningItems()[id];
    const item = state.material?.id === id ? {...saved, ...state.material} : saved;
    if (!item) {
      app.append(label("p", "empty", "这份资料目前无法打开。"), link("返回学习助手", "#/learning"));
      return;
    }
    const page = el("section");
    const header = el("div", "board-tools");
    const bookmark = label("button", "btn sm", saved ? "已收藏" : "收藏资料");
    bookmark.onclick = () => {
      saveLearningItem({...item, original: undefined});
      bookmark.textContent = "已收藏";
    };
    header.append(link("学习助手", "#/learning"), link("我的收藏", "#/favorites"), bookmark);
    page.append(header, label("h1", "", item.title));
    const grid = el("div", "learning-material");
    const boardPanel = el("div");
    const sourceBoards = el("div", "learning-source-boards");
    const reading = el("div", "card");
    page.append(grid);
    grid.append(boardPanel, reading);
    boardPanel.append(sourceBoards);
    if (item.fen || item.placement) {
      boardPanel.append(player([{title: "来源局面", fen: item.fen || item.placement + " w - - 0 1",
                                moves: item.moves || [], note: item.fen ? "" : "仅棋子摆放，行棋方与历史未确认。"}]));
    }
    if (item.original) {
      const preview = el("img", "learning-original");
      preview.src = item.original;
      preview.alt = "识别前的原图";
      boardPanel.append(preview);
    }
    if (item.placement) {
      const placement = el("input");
      placement.value = item.placement;
      placement.setAttribute("aria-label", "棋子摆放字段");
      const flip = label("button", "btn sm", "校正方向");
      flip.onclick = () => {
        placement.value = placement.value.split("/").reverse().map(row => [...row].reverse().join("")).join("/");
      };
      const apply = label("button", "btn sm", "更新摆放");
      apply.onclick = () => {
        const rows = placement.value.trim().split("/");
        if (rows.length !== 8 || rows.some(row => !/^[prnbqkPRNBQK1-8]+$/.test(row) ||
            [...row].reduce((sum, char) => sum + (Number(char) || 1), 0) !== 8)) {
          toast("请输入有效的 8 行棋子摆放字段");
          return;
        }
        item.placement = rows.join("/");
        viewMaterialRefresh();
      };
      function viewMaterialRefresh() {
        state.material = item;
        if (learningItems()[id]) saveLearningItem({...item, original: undefined});
        page.remove();
        viewMaterial(id);
      }
      reading.append(label("h2", "", "核对识图结果"), placement, flip, apply);
    }
    if (item.summary) reading.append(label("p", "lead", item.summary));
    if (item.remote && item.url) {
      const progress = label("p", "muted", "正在读取来源…");
      const cacheHost = el("div");
      const errorHost = el("div");
      reading.append(progress, cacheHost, errorHost);
      const loadSource = async (refresh = false) => {
        progress.hidden = false;
        progress.textContent = refresh ? "正在重新解析来源…" : "正在读取来源…";
        errorHost.replaceChildren();
        try {
          const data = await apiPost("/api/learning/source", {query: item.url, refresh});
          if (!page.isConnected) return;
          item.agentSummary = data.reply;
          item.positions = data.positions || [];
          item.remote = false;
          item.cache = data.cache;
          progress.textContent = item.agentSummary;
          cacheHost.replaceChildren();
          const badge = sourceCacheBadge(data.cache, () => loadSource(true));
          if (badge) cacheHost.append(badge);
          showSourcePositions();
        } catch (error) {
          progress.hidden = true;
          cacheHost.replaceChildren();
          errorHost.append(learningErrorPanel(errorInfo(error), () => loadSource(refresh)));
        }
      };
      loadSource(false);
    } else {
      if (item.agentSummary) reading.append(label("p", "lead", item.agentSummary));
      if (item.cache) {
        const badge = sourceCacheBadge(item.cache);
        if (badge) reading.append(badge);
      }
      showSourcePositions();
    }
    function showSourcePositions() {
      const positions = positionExamples((item.positions || []).map((position, index) => ({
        title: "来源棋盘 " + (index + 1),
        fen: position.fen,
        placement: position.placement,
        moves: position.moves || [],
        note: position.placement ? "仅棋子摆放，方向和行棋方待核对。" : ""
      })));
      sourceBoards.replaceChildren();
      if (positions.length) sourceBoards.append(learningBoardGallery(positions));
    }
    if (item.url) {
      const source = link("打开原始来源 ↗", item.url);
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      reading.append(source);
      const translation = label("p", "lead", item.translation || "");
      translation.style.whiteSpace = "pre-wrap";
      const excerpt = el("textarea");
      excerpt.placeholder = "粘贴你想读的英文段落";
      excerpt.setAttribute("aria-label", excerpt.placeholder);
      excerpt.maxLength = 6000;
      const translate = label("button", "btn sm", "翻译成中文");
      const status = label("p", "muted", "");
      translate.onclick = async () => {
        if (!excerpt.value.trim()) return;
        translate.disabled = true;
        status.textContent = "正在翻译…";
        try {
          const data = await apiPost("/api/learning/translate", {content: excerpt.value.trim()});
          item.translation = data.translation;
          translation.textContent = data.translation;
          status.textContent = "中文译文";
          bookmark.textContent = "保存到收藏";
        } catch (error) {
          status.textContent = error.message;
        } finally {
          translate.disabled = false;
        }
      };
      reading.append(excerpt, translate, status, translation);
    }
    if (item.practice) reading.append(link("打开本站练习或课程", item.practice));
    if (item.review?.played && item.review.recommended && item.review.played !== item.review.recommended) {
      const generate = label("button", "btn sm primary", "生成讲解 · Beta");
      const draft = el("textarea");
      draft.setAttribute("aria-label", "可编辑讲解草稿");
      draft.value = item.draft || "";
      draft.hidden = !item.draft;
      const evidence = label("p", "muted", item.evidence || "");
      const saveDraft = label("button", "btn sm", "保存文案");
      saveDraft.hidden = !item.draft;
      generate.onclick = async () => {
        generate.disabled = true;
        evidence.textContent = "正在对照引擎变化…";
        try {
          const data = await apiPost("/api/learning/explain", {fen: item.fen, ...item.review});
          draft.value = data.draft;
          draft.hidden = saveDraft.hidden = false;
          evidence.textContent = "推荐变化：" + data.evidence.positive_example + "｜实战变化：" + data.evidence.negative_example;
        } catch (error) {
          evidence.textContent = error.message;
        } finally {
          generate.disabled = false;
        }
      };
      saveDraft.onclick = () => {
        if (!draft.value.trim()) return;
        item.draft = draft.value.trim();
        item.evidence = evidence.textContent;
        saveLearningItem(item);
        bookmark.textContent = "已收藏";
        toast("文案已保存到收藏");
      };
      reading.append(generate, evidence, draft, saveDraft);
    }
    app.append(page);
  }

  async function viewCoach() {
    const page=el("section");
    page.append(label("h1","","我的学习教练"));
    const form=el("form","card learning-card");
    const input=el("textarea");
    const request=new URLSearchParams(location.hash.split("?")[1]||"").get("ask");
    if(request) input.value=request.slice(0,1500);
    input.rows=3; input.maxLength=1500; input.required=true;
    input.placeholder="例如：我在 Lichess 快棋约 1400 分，想用四周学开局和残局，每天 20 分钟";
    const send=label("button","btn primary","发送给教练");
    const mode=label("p","muted","");
    const result=el("div","learning-coach");
    form.append(input,send,mode); page.append(form,result); app.append(page);
    const data=await api("/api/coach");
    mode.textContent=data.ai_available?(data.ai_provider==="codebuddy"?"WorkBuddy / CodeBuddy · DeepSeek":"已配置 AI 教练"):"本地规划模式 · 可在服务端配置 AI 教练";
    function render(data) {
      result.replaceChildren();
      const memory=el("details","card learning-card");
      memory.append(label("summary","","教练记忆与对话"));
      const goal=data.goals||{};
      if(goal.request) memory.append(label("p","","学习要求："+goal.request));
      if(goal.rating_note) memory.append(label("p","","水平说明："+goal.rating_note));
      const reads=(data.read_lessons||[]).map(id=>state.boot.levels.flatMap(l=>l.lessons).find(l=>l.id===id)?.title||id);
      memory.append(label("p","muted","已读课程："+(reads.join("、")||"暂无")));
      for(const r of data.review_observations||[]) memory.append(label("p","muted",r.topic+"：最近 "+r.sample+" 局中有 "+r.games+" 局出现已验证的关联事件"));
      for(const r of data.opening_observations||[]) memory.append(label("p","muted","执"+(r.side==="white"?"白":"黑")+"时，近期导入棋局有 "+r.games+" 局匹配 "+r.opening));
      for(const row of data.conversation||[]) memory.append(label("p","","你："+row.request),label("p","muted","教练："+row.reply));
      const clear=label("button","btn sm","清除教练对话、目标与计划");
      clear.onclick=async()=>{try{await api("/api/coach/memory",{method:"DELETE"});render(await api("/api/coach"));}catch(e){toast(e.message);}};
      memory.append(clear); result.append(memory);
      if(!data.plan)return;
      function showPlan(plan, editable, title) {
        const list=el("div","learning-coach");
        list.append(label("h2","",title),label("p","muted",plan.reply));
        if(plan.source==="fallback") list.append(label("p","muted",plan.provider_status==="login_required"?"CodeBuddy CLI 尚未登录，本次使用本地规划。":"AI 暂不可用，本次使用本地规划。"));
        for(const t of plan.tasks){
          const row=el("div","card learning-card");
          row.append(label("strong","",(plan.mode==="plan"?"第 "+t.day+" 天 · ":"")+t.minutes+" 分钟 · "+(t.done?"已完成":"待学习")),
            label("p","muted",t.activity),link(t.title,t.href), ...t.kps.slice(0,1).map(k=>link("相关题目","#/library?kp="+k)));
          if(editable){
            const done=label("button","btn sm",t.done?"撤销完成":"标记完成");
            done.onclick=async()=>{done.disabled=true;try{render(await apiPost("/api/coach/task",{task_id:t.task_id,done:!t.done}));}
              catch(e){toast(e.message);done.disabled=false;}};
            row.append(done);
          }
          list.append(row);
        }
        return list;
      }
      result.append(showPlan(data.plan,true,data.plan.mode==="plan"?"我的长期计划":"本次学习"));
      if(data.plan.mode==="single"&&data.long_plan){
        const prior=el("details","card learning-card");
        const resume=label("button","btn sm primary","继续长期计划");
        resume.onclick=async()=>{try{render(await apiPost("/api/coach/resume",{level:state.boot.learner.level}));}catch(e){toast(e.message);}};
        prior.append(label("summary","","保留的长期计划"),resume,showPlan(data.long_plan,false,"长期计划"));result.append(prior);
      }
      if(data.versions?.length){
        const history=el("details","card learning-card");
        history.append(label("summary","","历史计划"));
        data.versions.slice().reverse().forEach((p,i)=>history.append(showPlan(p,false,"历史版本 "+(i+1))));
        result.append(history);
      }
    }
    render(data);
    form.onsubmit=async e=>{
      e.preventDefault();
      if(!input.value.trim())return;
      send.disabled=true;send.textContent="正在规划…";
      try{render(await apiPost("/api/coach",{message:input.value}));input.value="";}
      catch(e){toast(e.message);}
      finally{send.disabled=false;send.textContent="发送给教练";}
    };
  }

  function viewHome() {
    const bd = state.boot;
    const lv = bd.learner.level;
    const wrap = el("div");
    const entry = el("section", "learning-entry");
    const title = el("div");
    title.append(label("div", "eyebrow", "棋课 · 学习助手"),
                 label("h1", "", "今天想学什么？"),
                 label("p", "", "找知识点、整理棋盘，或围绕复盘里的失误继续学习。"));
    const start = link("打开学习助手 →", "#/learning");
    start.className = "btn";
    entry.append(title, start);
    app.append(entry);

    const hero = el("section", "hero");
    hero.innerHTML = `
      <div class="eyebrow">三个档位 · 各自的题</div>
      <h1>按档练题，导入棋谱复盘。</h1>
      <p class="lead">用 Lichess 题库练习，或导入自己的棋谱查看本地 Stockfish 分析。</p>
      <div class="hero-stats">
        <div class="stat"><b>${bd.puzzle_total.toLocaleString()}</b><span>题库总题数</span></div>
        <div class="stat"><b>${Object.keys(bd.progress).length}</b><span>练过的主题</span></div>
      </div>`;

    const grid = el("div", "level-grid");
    bd.levels.forEach((level) => {
      const card = el("div", "level" + (level.id === lv ? " on" : ""));
      card.innerHTML = `
        ${level.id === lv ? '<div class="tick">● 当前档</div>' : ""}
        <div class="lvl-no">第 ${level.id} 档</div>
        <div class="lvl-name">${level.name}</div>
        <div class="lvl-sub">${level.sub}</div>
        <div class="lvl-desc">${level.desc}</div>
        <div style="margin-top:14px" class="muted">题目难度 ${level.rating[0]}–${level.rating[1]}</div>`;
      card.onclick = async () => {
        await apiPost("/api/level", {  level: level.id });
        await boot();
        route();
        toast(`已切换到「${level.name}」档，题目难度同步调整`);
      };
      grid.appendChild(card);
    });

    const head = el("div", "section-head");
    head.innerHTML = `<h2>今天从哪儿开始</h2>`;
    const actions = el("div");
    actions.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px";
    [
      ["#/courses", "教程", "查看知识点和原始练习", "primary"],
      ["#/practice", "按题练", "按知识点抽题，做错的会进复习队列", ""],
      ["#/review", "导入棋谱复盘", "逐步回放，标出关键转折和更优走法", ""],
    ].forEach(([href, t, d, cls]) => {
      const c = el("div", "card");
      c.innerHTML = `<h3>${t}</h3><p style="font-size:13.5px;margin-bottom:16px">${d}</p>
        <a class="btn ${cls}" href="${href}">进入</a>`;
      actions.appendChild(c);
    });

    wrap.append(hero, grid, head, actions);
    app.appendChild(wrap);
  }

  // ------------------------------------------------------------------
  // 课程列表
  // ------------------------------------------------------------------
  const PRACTICE = "https://lichess.org/practice/";
  const TRAINING = "https://lichess.org/training/";
  const CHECKMATES = PRACTICE + "checkmates/piece-checkmates-i/BJy6fEDf/";
  const ROOK_ENDGAMES = PRACTICE + "rook-endgames/practicestnambasicrookendgames/pqUSUw8Y";
  const BASIC_RULES = "https://lichess.org/study/HhrD9dbE";
  const FIDE_RULES = "https://handbook.fide.com/chapter/E012023";

  const SOURCE_TOPICS = [
    ["基本规则", [
      ["应将", BASIC_RULES, null, "应将例局 · 第 1–6 章", "§3.9"],
      ["逼和", BASIC_RULES, null, "逼和例局 · 第 14–18 章", "§5.2.1"],
      ["兵的升变", TRAINING + "promotion", "promotion", "Lichess 升变题库", "§3.7.3.3–3.7.3.5"],
    ]],
    ["杀王", [
      ["单后杀王", CHECKMATES + "U3r4wkFn", null, "Lichess 单后杀王"],
      ["单车杀王", CHECKMATES + "VeKiltmx", null, "Lichess 单车杀王"],
      ["双车阶梯杀王", CHECKMATES + "8K8FdT6P", null, "Lichess 双车杀王"],
      ["一步杀", TRAINING + "mateIn1", "mateIn1", "Lichess 一步杀专题"],
      ["底线杀", TRAINING + "backRankMate", "backRankMate", "Lichess 底线杀专题"],
      ["阿拉伯杀", TRAINING + "arabianMate", "arabianMate", "Lichess 阿拉伯杀专题"],
      ["闷杀", TRAINING + "smotheredMate", "smotheredMate", "Lichess 闷杀专题"],
    ]],
    ["基础战术", [
      ["白吃子", TRAINING + "hangingPiece", "hangingPiece", "Lichess 白吃子专题"],
      ["牵制", PRACTICE + "fundamental-tactics/practicestnamthepin/9ogFv8Ac", "pin"],
      ["串击", PRACTICE + "fundamental-tactics/practicestnamtheskewer/tuoBxVE5", "skewer"],
      ["叉子", PRACTICE + "fundamental-tactics/practicestnamthefork/Qj281y1p", "fork"],
      ["闪击", PRACTICE + "fundamental-tactics/practicestnamdiscoveredattacks/MnsJEWnI", "discoveredAttack"],
      ["双将", PRACTICE + "fundamental-tactics/practicestnamdoublecheck/RUQASaZm", "doubleCheck"],
      ["过载", PRACTICE + "fundamental-tactics/practicestnamoverloadedpieces/o734CNqp", "overloading"],
      ["过渡着", PRACTICE + "fundamental-tactics/practicestnamzwischenzug/ITWY4GN2", "intermezzo"],
    ]],
    ["进阶战术", [
      ["消除保护", PRACTICE + "advanced-tactics/practicestnamundermining/udx042D6", "capturingDefender"],
      ["引离", PRACTICE + "advanced-tactics/practicestnamdeflection/kdKpaYLW", "deflection"],
      ["引入", PRACTICE + "advanced-tactics/practicestnamattraction/jOZejFWk", "attraction"],
      ["低升变", PRACTICE + "advanced-tactics/practicestnamunderpromotion/49fDW0wP", "underPromotion"],
    ]],
    ["基础残局", [
      ["关键格", PRACTICE + "pawn-endgames/practicestnamkeysquares/xebrDvFe"],
      ["对王", PRACTICE + "pawn-endgames/practicestnamopposition/A4ujYOer"],
      ["后对七横线边兵", PRACTICE + "pawn-endgames/practicestnam7thrankrookpawn/pt20yRkT"],
      ["卢塞纳局面", ROOK_ENDGAMES],
      ["菲利多尔防守", ROOK_ENDGAMES + "/CvqYotss"],
    ]],
  ];

  async function viewCourses(levelArg) {
    const topics = el("section");
    topics.append(label("h1", "", "国际象棋教程"));
    const availableThemes = new Set(state.boot.practice_themes);
    function sourceLink(title, url) {
      const source = link(title, url);
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      return source;
    }
    const videoCourse = el("article", "card learning-card");
    videoCourse.append(
      label("h2", "", "大师入门课 · 24 集"),
      label("p", "muted", "Jeremy Silman · 分集图文、原片时间戳和部分可回放棋谱"),
      link("打开分集目录", "/static/tutorials/silman/index.html")
    );
    topics.append(videoCourse);
    const bookCourse = el("article", "card learning-card");
    bookCourse.append(
      label("h2", "", "卡帕布兰卡《国际象棋基础》"),
      label("p", "muted", "中文译本 · 棋图"),
      link("阅读中文译本", "/static/tutorials/fundamentals/translation.html"),
      link("中文导读与回放", "/static/tutorials/fundamentals/index.html")
    );
    topics.append(bookCourse);
    for (const [sectionTitle, items] of SOURCE_TOPICS) {
      const section = el("section");
      section.append(label("h2", "", sectionTitle));
      const grid = el("div", "learning-grid");
      for (const [name, url, theme, sourceTitle = "Lichess 原课", rule] of items) {
        const card = el("article", "card learning-card");
        card.append(label("h3", "", name), sourceLink(sourceTitle, url));
        if (rule) card.append(sourceLink("FIDE 棋规 " + rule, FIDE_RULES));
        if (availableThemes.has(theme)) {
          card.append(link("本站练习", "#/library?theme=" + encodeURIComponent(theme)));
        }
        grid.append(card);
      }
      section.append(grid);
      topics.append(section);
    }
    app.append(topics);
    const openingSection = el("section");
    openingSection.append(label("h2", "", "开局"));
    topics.append(openingSection);
    try {
      const openings = await api("/api/openings");
      const grid = el("div", "learning-grid");
      for (const item of openings) {
        const card = el("article", "card learning-card");
        card.append(label("h3", "", item.name), label("p", "muted", item.summary),
                    link("本站开局课", "#/openings/" + item.id));
        grid.append(card);
      }
      openingSection.append(grid);
    } catch (e) {
      openingSection.append(label("p", "muted", e.message));
    }
    if (!state.boot.tutorials_published || !topics.isConnected) return;
    const bd = state.boot;
    const lv = levelArg ? parseInt(levelArg, 10) : bd.learner.level;
    const level = bd.levels.find((l) => l.id === lv);
    const wrap = el("div");
    wrap.innerHTML = `<div class="eyebrow">第 ${level.id} 档 · ${level.sub}</div>
      <h1>${level.name}课程</h1><p class="lead">${level.desc}</p>
      <p class="muted" style="margin-top:8px">每课的验收题是固定的同一批，方便你隔几天回来重做对照。</p>`;
    const levels = el("div","board-tools");
    bd.levels.forEach(l=>{
      const a=link(l.name,"#/courses/"+l.id);
      if(l.id===lv)a.classList.add("primary");
      levels.append(a);
    });
    wrap.append(levels);
    const list = el("div");
    list.style.marginTop = "26px";
    level.lessons.forEach((l) => {
      const row = el("div", "course-row");
      row.innerHTML = `
        <div class="no">${String(l.order).padStart(2, "0")}</div>
        <div class="body">
          <div class="t">${l.title} ${l.done ? '<span class="pill green" style="margin-left:6px">已读</span>' : ""}</div>
          <div class="d">${l.intro}</div>
        </div>
        <div class="go">→</div>`;
      row.onclick = () => (location.hash = "#/lesson/" + l.id);
      list.appendChild(row);
    });
    wrap.appendChild(list);
    app.appendChild(wrap);
  }

  // ------------------------------------------------------------------
  // 单课
  // ------------------------------------------------------------------
  async function viewLesson(lessonId) {
    const data = await api(`/api/lessons/${lessonId}`);
    const lesson = data.lesson;

    const wrap = el("div");
    const head = el("div", "lesson-head");
    head.innerHTML = `
      <div class="eyebrow">第 ${lesson.level} 档 · 第 ${lesson.order} 课</div>
      <h1>${lesson.title}</h1>
      <p class="lead">${lesson.intro}</p>
      <div style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap">
        ${data.kps.map((k) => `<span class="pill">${k.name}</span>`).join("")}
      </div>`;

    const example = lesson.example;
    const ex = example?.source?.kind === "puzzle" ? example : null;
    const grid = el("div", "lesson-grid");
    const left = el("div", "lesson-body");
    lesson.sections.forEach((s) => {
      left.appendChild(el("h3", null, s.h));
      left.appendChild(el("p", null, s.p));
    });

    const kp = data.kps[0];
    if (kp && kp.mistake) {
      const box = el("div", "card");
      box.style.cssText = "margin:22px 0;background:var(--amber-soft);border-color:#ecdcbf";
      box.innerHTML = `<div class="eyebrow" style="color:var(--amber)">常见误区</div>
        <p style="margin:0;color:#6d4d16">${kp.mistake}</p>`;
      left.appendChild(box);
    }

    if (data.quiz.length) {
      left.appendChild(el("h3", null, "验收题"));
      left.appendChild(el("p", "muted", `这 ${data.quiz.length} 道题固定用于本课，难度匹配你当前档位。练习记录保存在本机。`));
      const qlist = el("div", "quiz-list");
      data.quiz.forEach((p, i) => {
        const item = el("div", "quiz-item");
        item.innerHTML = `
          <div class="idx">${i + 1}</div>
          <div class="meta"><b>难度 ${p.rating}</b>${p.themes.slice(0, 3).map((t) => themeCN(t)).join(" · ")}</div>
          <button class="btn sm">开始</button>`;
        item.querySelector("button").onclick = () => {
          openPuzzleModal(p, { onDone: (ok) => item.classList.toggle("done", ok) });
        };
        qlist.appendChild(item);
      });
      left.appendChild(qlist);
    }

    const right = el("div");
    if (ex && (ex.branches || (ex.source && ex.source.label))) {
      right.append(player(ex.branches || [ex]));
    } else if (ex) {
      right.appendChild(el("div", "eyebrow", "局面演示"));
      const boardCard = el("div", "card");
      boardCard.style.padding = "16px";
      const boardHost = el("div");
      const caption = el("div", "board-caption", "");
      const tools = el("div", "board-tools");
      const btnNext = el("button", "btn sm primary", "下一步");
      const btnReset = el("button", "btn sm", "重置");
      tools.append(btnNext, btnReset);
      boardCard.append(boardHost, tools, caption);
      right.appendChild(boardCard);

      const moves = ex.moves || [];
      let idx = 0;
      const board = new Board(boardHost, {
        fen: ex.fen,
        orientation: ex.orientation || "white",
        interactive: false,
      });
      if (ex.marks && ex.marks.length) board.setMarks(ex.marks);

      const startText = ex.note || "";
      const say = (txt) => (caption.textContent = txt || startText);
      say(startText);

      const applyMove = (m) => {
        let mv = null;
        let from = null, to = null;
        try {
          if (m.uci) {
            from = m.uci.slice(0, 2);
            to = m.uci.slice(2, 4);
            mv = board.chess.move({ from, to, promotion: m.uci[4] || "q" });
          }
        } catch (e) {
          mv = null;
        }
        if (!mv && m.san) {
          // 手写的教学局面只给了 SAN，没有 UCI
          try {
            mv = board.chess.move(m.san);
          } catch (e) {
            try { mv = board.chess.move((m.san || "").replace(/[+#]$/, "")); } catch (e2) { mv = null; }
          }
        }
        if (!mv) return null;
        from = mv.from;
        to = mv.to;
        board.lastMove = { from, to };
        board.render();
        return mv;
      };

      btnNext.onclick = () => {
        if (idx >= moves.length) { toast("演示已经走完了"); return; }
        const m = moves[idx++];
        if (!applyMove(m)) { toast("这一步无法在当前局面上执行：" + (m.san || m.uci)); return; }
        say(m.comment || m.san);
        if (idx >= moves.length) btnNext.disabled = true;
      };
      btnReset.onclick = () => {
        idx = 0;
        board.setFen(ex.fen);
        board.setMarks(ex.marks || []);
        btnNext.disabled = moves.length === 0;
        say(startText);
      };
      if (!moves.length) btnNext.disabled = true;

      // 来源说明：真实题目给原题链接，教学构造局面明说不是题库题
      const src = el("div", "card");
      src.style.cssText = "margin-top:12px;padding:16px;font-size:13px";
      if (ex.source && ex.source.kind === "puzzle") {
        src.innerHTML = `<div class="eyebrow">演示来源</div>
          <div>题库原题 <b>#${ex.source.puzzle_id}</b> · 难度 ${ex.source.rating}</div>
          <div class="muted" style="margin-top:4px">主题：${ex.source.themes_cn.join("、")}</div>
          <a class="btn sm ghost" style="margin-top:10px" target="_blank" rel="noopener"
             href="${ex.source.url}">在 Lichess 上核对这道题 →</a>`;
      } else {
        const hasMoves = (ex.moves || []).length > 0;
        src.innerHTML = `<div class="eyebrow">演示来源</div>
          <div>教学构造局面（不是题库题）。${
            hasMoves
              ? "演示走法是这类技术的标准次序，不是唯一解；重点是看形状和次序，不是背招。"
              : "这类内容没有唯一答案，所以只标出关键格和判断要点，不假装有“正确走法”。"
          }</div>`;
      }
      right.appendChild(src);
    }

    const nav = el("div");
    nav.style.cssText = "margin-top:28px;display:flex;gap:10px";
    const coursesBtn = el("a", "btn ghost", "← 返回课程列表");
    coursesBtn.href = "#/courses";
    const nextBtn = el("a", "btn primary", "去题库练这一课");
    nextBtn.href = "#/practice?kp=" + lesson.kps.join(",");
    const read = label("button", "btn sm", state.boot.levels.flatMap(l=>l.lessons).find(l=>l.id===lessonId)?.done ? "已标记读完" : "标记已读");
    read.onclick = async () => {
      try {
        await apiPost("/api/lessons/"+lessonId+"/read",{level:lesson.level});
        read.textContent="已标记读完"; read.disabled=true;
        const meta=state.boot.levels.flatMap(l=>l.lessons).find(l=>l.id===lessonId);
        if(meta)meta.done=true;
      } catch(e){toast(e.message);}
    };
    nav.append(coursesBtn, read, nextBtn);

    wrap.append(head, grid, nav);
    grid.append(left);
    if (ex) grid.append(right);
    app.appendChild(wrap);
  }

  // ------------------------------------------------------------------
  // 题目弹层
  // ------------------------------------------------------------------
  function openPuzzleModal(puzzle, opts = {}) {
    const overlay = el("div");
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:60;background:rgba(29,31,28,.42);display:flex;align-items:center;justify-content:center;padding:24px";
    const card = el("div", "card");
    card.style.cssText = "width:min(560px,100%);max-height:92vh;overflow:auto;padding:20px";
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.onclick = (e) => { if (e.target === overlay) close(); };

    const head = el("div", "puzzle-head");
    head.innerHTML = `<h3 style="margin:0">难度 ${puzzle.rating}</h3>
      <div class="puzzle-meta">
        <span class="pill">${puzzle.fen.split(" ")[1] === "w" ? "白方走" : "黑方走"}</span>
        ${puzzle.themes.slice(0, 3).map((t) => `<span class="pill">${themeCN(t)}</span>`).join("")}
      </div>`;
    const boardHost = el("div");
    const fb = el("div", "feedback");
    const tools = el("div", "board-tools");
    const btnHint = el("button", "btn sm", "提示");
    const btnClose = el("button", "btn sm ghost", "关闭");
    tools.append(btnHint, btnClose);
    card.append(head, boardHost, fb, tools);

    const board = new Board(boardHost, { fen: puzzle.fen, interactive: false });
    if (puzzle.pre) {
      const from = puzzle.pre.slice(0, 2), to = puzzle.pre.slice(2, 4);
      try {
        board.chess.move({ from, to, promotion: puzzle.pre[4] || "q" });
        board.render();
        board.setLastMove(from, to);
      } catch (e) {}
    }
    board.setOrientation(board.chess.turn() === "w" ? "white" : "black");
    const startFen = board.fen;
    let idx = 0;
    let solved = false;
    let errors = 0;
    const t0 = Date.now();

    const kpIds = [...(opts.kpIds || [])];
    for (const t of puzzle.themes) {
      (state.boot.kps || []).forEach((k) => {
        if ((k.themes || []).includes(t) && !kpIds.includes(k.id)) kpIds.push(k.id);
      });
    }

    function finish() {
      solved = true;
      fb.className = "feedback show ok";
      fb.textContent = "正确。这一步走对了。";
      board.setInteractive(false);
      const ms = Date.now() - t0;
      apiPost("/api/attempt", {

        puzzle_id: puzzle.id,
        correct: true,
        ms,
        kp_ids: kpIds,
      }).then((r) => {
        state.boot.stats = r.stats;
        state.boot.progress = r.progress;
        renderWho();
      }).catch(() => {});
      if (opts.onDone) opts.onDone(true);
      setTimeout(close, 1100);
    }

    board.onMove = (mv) => {
      if (solved) return;
      const expect = puzzle.solution[idx];
      const uci = mv.from + mv.to + (mv.promotion || "");
      if (uci === expect) {
        idx++;
        errors = 0;
        fb.className = "feedback show ok";
        fb.textContent = "对。";
        if (idx >= puzzle.solution.length) { finish(); return; }
        setTimeout(() => {
          const reply = puzzle.solution[idx];
          const f = reply.slice(0, 2), t = reply.slice(2, 4);
          try {
            board.chess.move({ from: f, to: t, promotion: reply[4] || "q" });
            board.render();
            board.setLastMove(f, t);
          } catch (e) {}
          idx++;
          if (idx >= puzzle.solution.length) finish();
        }, 380);
      } else {
        errors++;
        board.undo();
        board.render();
        fb.className = "feedback show bad";
        fb.textContent = errors >= 2 ? "还是不对。点「提示」看第一手。" : "不是这一步，再想想。";
        if (errors >= 3) {
          fb.className = "feedback show tip";
          fb.textContent = "答案是 " + uciToSan(startFen, puzzle.solution[0]) + "。这题算没做出来，已记入待复习。";
          const ms = Date.now() - t0;
          apiPost("/api/attempt", {

            puzzle_id: puzzle.id,
            correct: false,
            ms,
            kp_ids: kpIds,
          }).then((r) => { state.boot.stats = r.stats; renderWho(); }).catch(() => {});
          if (opts.onDone) opts.onDone(false);
          board.setInteractive(false);
        }
      }
    };

    btnHint.onclick = () => {
      fb.className = "feedback show tip";
      fb.textContent = "第一手是 " + uciToSan(startFen, puzzle.solution[0]) + "（点一下棋盘再走）。";
    };
    btnClose.onclick = close;
    board.setInteractive(true);
    window.__cc = {
      id: puzzle.id,
      fen: () => board.fen(),
      expect: () => puzzle.solution[idx],
      idx: () => idx,
      solved: () => solved,
    };
    if (puzzle.solution.length === 0) finish();
  }

  // ------------------------------------------------------------------
  // 变化演示弹层：转折点的更优走法、推荐着 / 实战着对比共用
  // ------------------------------------------------------------------
  let rvModalOpen = 0;
  let rvCloser = null;

  /** 把 SAN 数组展开成可逐手回放的步骤（每步都存 FEN，切步只换局面）。 */
  function openStaticVisualization(fen) {
    const dialog = el("dialog", "card");
    dialog.style.cssText = "width:min(1100px,95vw);height:90vh;padding:12px";
    const close = label("button", "btn sm", "关闭可视化");
    const frame = document.createElement("iframe");
    frame.title = "双方静态特征可视化";
    frame.src = "/static/review-lab/index.html?featureFen=" + encodeURIComponent(fen);
    frame.style.cssText = "width:100%;height:calc(100% - 45px);border:0";
    close.onclick = () => dialog.close();
    dialog.append(close, frame);document.body.append(dialog);
    dialog.addEventListener('close',()=>dialog.remove());dialog.showModal();
  }

  async function renderConceptVisualization(host, board, fen, concepts) {
    if (board._reviewEvidenceDispose) board._reviewEvidenceDispose();
    host.replaceChildren(label("p", "muted", "正在读取概念的完整可视化证据…"));
    if (!concepts.length) { host.replaceChildren(label("p", "muted", "当前变化没有最终展示的概念。")); return; }
    const requestToken = {};
    host._evidenceRequest = requestToken;
    try {
      const payload = await apiPost("/api/static-features", {fen});
      if (!host.isConnected || board.fen !== fen || host._evidenceRequest !== requestToken) return;
      host.innerHTML = "<div data-evidence=\"evidence-panel\"><div class=\"section-head\"><h2>静态特征可视化</h2><button data-evidence=\"feature-show\">显示</button></div>\n<p class=\"muted\">21项静态概念已接入；8、14、17、18、23、24、25、28、30尚未可视化。蓝圈表示白方项目，橙框表示黑方项目；项目所属视角不等于格上棋子的颜色。总判定未成立时仍可检查静态诊断。</p>\n<div class=\"evidence-controls\"><label>概念<select data-evidence=\"feature-rule\"></select></label><label>标记双方<select data-evidence=\"feature-side\"><option value=\"both\">双方</option><option value=\"white\">只看白方项目</option><option value=\"black\">只看黑方项目</option></select></label><label>标记类别<select data-evidence=\"feature-type\"><option value=\"all\">全部类别</option></select></label><label class=\"feature-checkbox\"><input type=\"checkbox\" data-evidence=\"feature-aux\">包含背景/正常项目</label></div>\n<p data-evidence=\"feature-status\" role=\"status\"></p><p data-evidence=\"feature-scores\"></p>\n<div class=\"evidence-tabs\"><button data-evidence=\"feature-show-all\" class=\"secondary\">标记全部目标</button><button data-evidence=\"feature-show-relations\" class=\"secondary\">同时显示攻防关系</button></div>\n<p class=\"muted\">实线为攻击/控制，虚线为同方保护。点击下方项目可单独显示坐标、关系和计分依据；点击棋盘格可检查该格关联项目。特征分采用各规则自己的单位。</p>\n<p data-evidence=\"feature-square-info\" aria-live=\"polite\"></p><div data-evidence=\"feature-items\"></div><div data-evidence=\"feature-detail\"></div>\n<details><summary>固定格式返回信息（测试打印）</summary><pre data-evidence=\"feature-text\"></pre></details>\n<details><summary>原始返回JSON（测试打印）</summary><label class=\"feature-checkbox\"><input type=\"checkbox\" data-evidence=\"feature-print-all\">打印全部返回概念数据</label><pre data-evidence=\"feature-raw\"></pre></details>\n<p data-evidence=\"feature-board-status\" aria-live=\"polite\"></p></div>";
      const names = concepts.map(c=>c.name);
      const labels = new Map(concepts.map(c=>[c.name,c.text]));
      const evidence = createReviewEvidence(host, {allowedNames:names, payload});
      evidence.init(board, payload.rules, name=>labels.get(name)||name, null);
      const dispose = () => { evidence.dispose(); if(board._reviewEvidenceDispose === dispose) board._reviewEvidenceDispose=null; };
      board._reviewEvidenceDispose = dispose;
      const clear = label("button", "btn sm", "退出可视化，恢复走棋");
      clear.onclick = () => { dispose(); host.replaceChildren(); };
      host.prepend(clear);
      await evidence.update(fen, board.orientation, "当前概念证据局面");
    } catch (e) { if(host.isConnected && host._evidenceRequest === requestToken) host.replaceChildren(label("p", "muted", e.message || "可视化读取失败，请重试。")); }
  }

  function lineSteps(fen, sans) {
    const steps = [{ fen, last: null, token: "" }];
    let chess;
    try { chess = new Chess(fen); } catch (e) { return steps; }
    const list = sans || [];
    for (let i = 0; i < list.length; i++) {
      const parts = chess.fen().split(" ");
      const no = parts[5] || "1";
      const black = parts[1] === "b";
      let mv = null;
      try { mv = chess.move(list[i], { sloppy: true }); } catch (e) { mv = null; }
      if (!mv) break;
      const prefix = black ? (i === 0 ? no + "…" : "") : no + ".";
      steps.push({
        fen: chess.fen(),
        last: { from: mv.from, to: mv.to },
        token: (prefix ? prefix + " " : "") + mv.san,
      });
    }
    return steps;
  }

  /** 优先回放本次解说使用的主变化，尚未请求解说时用整盘复盘的推荐线。 */
  function variationLines(t, result) {
    const pv = (t.best && t.best.pv) || [];
    const pos = (result && result.positive_example) || [];
    const neg = (result && result.negative_example) || [];
    const best = pos.length ? pos : pv.length ? pv : (t.best && t.best.san ? [t.best.san] : []);
    const lines = [];
    if (best.length) lines.push({ label: "推荐着变化", san: best });
    if (neg.length) lines.push({ label: "实战着变化", san: neg });
    return lines;
  }

  function openVariationPlayer(opts) {
    const { title, subtitle, fen, lines, orientation = "white", onBoard, startIndex = 1 } = opts;
    if (!fen || !lines || !lines.length) return;

    const overlay = el("div", "var-overlay");
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:70;background:rgba(29,31,28,.45);display:flex;"
      + "align-items:center;justify-content:center;padding:18px";
    const card = el("div", "card var-modal");
    card.style.cssText =
      "width:min(400px,100%);max-width:400px;max-height:92vh;overflow:auto;"
      + "padding:16px 18px 14px;display:grid;gap:10px";
    overlay.appendChild(card);
    (opts.modalHost || document.body).appendChild(overlay);
    rvModalOpen++;

    const head = el("div", "var-head");
    head.style.cssText = "display:flex;align-items:flex-start;justify-content:space-between;gap:10px";
    const headText = el("div");
    headText.innerHTML = `<div class="eyebrow">变化演示</div><h3>${title || "引擎变化"}</h3>`;
    if (subtitle) headText.appendChild(label("div", "muted", subtitle));
    const btnClose = label("button", "btn sm ghost", "关闭");
    btnClose.style.flex = "0 0 auto";
    head.append(headText, btnClose);

    const tabs = el("div", "var-tabs");
    tabs.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";
    const boardHost = el("div", "var-board");
    boardHost.style.cssText = "width:min(300px,62vw,46vh);max-width:300px;margin:0 auto";
    const nav = el("div", "rv-steps var-nav");
    const bFirst = label("button", "", "⏮");
    const bPrev = label("button", "", "◀");
    const posText = el("span", "pos", "0 / 0");
    const bNext = label("button", "", "▶");
    const bLast = label("button", "", "⏭");
    const bPlay = label("button", "var-play", "自动");
    const sanRow = el("div", "var-san");
    sanRow.style.cssText =
      "display:flex;flex-wrap:wrap;gap:4px;font-size:12.5px;line-height:1.7;"
      + "max-height:78px;overflow:auto";
    const foot = el("div", "board-tools var-foot");
    nav.append(bFirst, bPrev, posText, bNext, bLast, bPlay);
    card.append(head, tabs, boardHost, nav, sanRow, foot);

    const board = new Board(boardHost, { fen, orientation, interactive: false });
    const cache = new Map();
    let lineIdx = 0;
    let idx = startIndex;

    function stepsFor(i) {
      if (!cache.has(i)) cache.set(i, lineSteps(fen, lines[i].san));
      return cache.get(i);
    }

    function renderTabs() {
      tabs.innerHTML = "";
      tabs.hidden = lines.length < 2;
      if (lines.length < 2) return;
      lines.forEach((ln, i) => {
        const b = el("button", "var-tab" + (i === lineIdx ? " on" : ""), ln.label);
        b.style.cssText = "font:inherit;font-size:12.5px;padding:5px 12px;border-radius:999px;cursor:pointer;"
          + (i === lineIdx
            ? "border:1px solid #2f6f4e;background:#2f6f4e;color:#fff"
            : "border:1px solid #d8d2c4;background:#fff;color:#4a4d47");
        b.onclick = () => {
          lineIdx = i;
          idx = Math.min(startIndex, stepsFor(i).length - 1);
          renderTabs();
          render();
        };
        tabs.appendChild(b);
      });
    }

    function render() {
      const steps = stepsFor(lineIdx);
      idx = Math.max(0, Math.min(steps.length - 1, idx));
      const st = steps[idx];
      if (board._reviewEvidenceDispose) board._reviewEvidenceDispose();
      if (typeof visualization !== "undefined") visualization.replaceChildren();
      board.setMarks([]);
      board.setFen(st.fen);
      board.setLastMove(st.last ? st.last.from : null, st.last ? st.last.to : null);
      if (lines[lineIdx].showArrow && st.last) board.setArrow(st.last.from, st.last.to, "green");
      else board.clearArrow();
      posText.textContent = `${idx} / ${steps.length - 1}`;
      bFirst.disabled = bPrev.disabled = idx === 0;
      bNext.disabled = bLast.disabled = idx >= steps.length - 1;
      sanRow.innerHTML = "";
      steps.forEach((s, i) => {
        if (i === 0) return;
        const marks = lines[lineIdx].conceptMarks?.[i] || [];
        const tok = el("button", "san" + (i === idx ? " on" : ""), s.token + (marks.length ? " ◆" : ""));
        if (marks.length) { tok.title = marks.join("；"); tok.classList.add("concept-true"); }
        tok.type = "button";
        tok.style.cssText = "font:inherit;border:0;background:transparent;padding:2px 6px;border-radius:6px;cursor:pointer;white-space:nowrap;"
          + (i === idx ? "background:#1d1f1c;color:#fff" : "color:#4a4d47");
        tok.onclick = () => { stopPlay(); idx = i; render(); };
        sanRow.appendChild(tok);
      });
      const on = sanRow.querySelector(".san.on");
      if (on) on.scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    let timer = null;
    function stopPlay() {
      clearInterval(timer);
      timer = null;
      bPlay.textContent = "自动";
      bPlay.classList.remove("on");
    }
    bPlay.onclick = () => {
      if (timer) { stopPlay(); return; }
      const steps = stepsFor(lineIdx);
      if (idx >= steps.length - 1) { idx = 0; render(); }
      bPlay.textContent = "暂停";
      bPlay.classList.add("on");
      timer = setInterval(() => {
        if (idx >= stepsFor(lineIdx).length - 1) { stopPlay(); return; }
        idx++;
        render();
      }, 800);
    };

    bFirst.onclick = () => { stopPlay(); idx = 0; render(); };
    bPrev.onclick = () => { stopPlay(); idx--; render(); };
    bNext.onclick = () => { stopPlay(); idx++; render(); };
    bLast.onclick = () => { stopPlay(); idx = stepsFor(lineIdx).length - 1; render(); };

    if (onBoard) {
      const btn = label("button", "btn sm", "在大棋盘上试走这条线");
      btn.onclick = () => {
        const sans = lines[lineIdx].san || [];
        close();
        onBoard(sans, idx);
      };
      foot.appendChild(btn);
    }
    const visualization = el("div", "concept-visualization");
    card.append(visualization);
    const visualize = label("button", "btn sm", "可视化当前展示概念");
    visualize.onclick = () => renderConceptVisualization(visualization, board, stepsFor(lineIdx)[idx].fen, lines[lineIdx].concepts || []);
    foot.append(visualize);
    foot.appendChild(label("span", "muted", "红色着法：当前概念连续验证通过的起点 n · 方向键翻步 · Esc 关闭"));

    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      if (e.key === "ArrowLeft") { e.preventDefault(); stopPlay(); idx--; render(); }
      if (e.key === "ArrowRight") { e.preventDefault(); stopPlay(); idx++; render(); }
    }

    let closed = false;
    function close() {
      if (closed) return;
      closed = true;
      if (board._reviewEvidenceDispose) board._reviewEvidenceDispose();
      stopPlay();
      document.removeEventListener("keydown", onKey);
      overlay.remove();
      rvModalOpen = Math.max(0, rvModalOpen - 1);
      if (rvCloser === close) rvCloser = null;
    }

    rvCloser = close;
    document.addEventListener("keydown", onKey);
    btnClose.onclick = close;
    overlay.onclick = (e) => { if (e.target === overlay) close(); };

    renderTabs();
    render();
  }

  function uciToSan(fen, uci) {
    try {
      const c = new Chess(fen);
      const mv = c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || "q" });
      return mv.san;
    } catch (e) { return uci; }
  }

  function themeCN(t) {
    const map = {
      mate: "将杀", fork: "叉子", pin: "牵制", skewer: "串击", mateIn1: "一步杀", mateIn2: "两步杀",
      mateIn3: "三步杀", backRankMate: "底线杀", hangingPiece: "白吃子", discoveredAttack: "闪击",
      discoveredCheck: "闪将", deflection: "引离", attraction: "引入", sacrifice: "弃子",
      endgame: "残局", middlegame: "中局", opening: "开局", promotion: "升变",
      advancedPawn: "通路兵", smotheredMate: "闷杀", rookEndgame: "车残局",
      pawnEndgame: "兵残局", queenEndgame: "后残局", bishopEndgame: "象残局",
      knightEndgame: "马残局", capturingDefender: "消除保护", interference: "拦截",
      intermezzo: "中间着", clearance: "腾挪", xRayAttack: "X 光", zugzwang: "楚茨旺格",
      perpetualCheck: "长将", doubleBishopMate: "双象杀", arabianMate: "阿拉伯杀",
      anastasiaMate: "阿纳斯塔西娅杀", bodenMate: "博登杀", dovetailMate: "燕尾杀",
      hookMate: "钩子杀", killBoxMate: "杀箱", supportMate: "支撑杀", oneMove: "一手题",
      collinearMove: "同线", castling: "易位", enPassant: "吃过路兵", equality: "均势",
      advantage: "优势", crushing: "碾压", master: "高手对局", masterVsMaster: "高手对局",
      superGM: "超级棋手", veryLong: "长计算", longCastling: "长易位", shortCastling: "短易位",
      queensideCastling: "后翼易位", kingsideAttack: "王翼进攻", attackingF2F7: "攻 f2/f7",
      exposedKing: "暴露的王", doubleCheck: "双将", underPromotion: "低升变",
      quietMove: "静着", defensiveMove: "防守着", trappedPiece: "困子", overloading: "过载",
    };
    return map[t] || t;
  }

  // ------------------------------------------------------------------
  // 题库练习
  // ------------------------------------------------------------------
  async function viewPractice() {
    const params = new URLSearchParams((location.hash.split("?")[1]) || "");
    const kpParam = params.get("kp") || "";
    const level = state.boot.learner.level;
    const data = await api(
      `/api/practice?level=${level}&kp=${encodeURIComponent(kpParam)}&count=10`
    );

    const wrap = el("div");
    wrap.innerHTML = `<div class="eyebrow">第 ${level} 档 · ${LEVEL_NAMES[level]}</div>
      <h1>题库练习</h1>
      <p class="lead">按当前档位的难度区间抽题。做对的会延后复习，做错的会回到队列里。</p>`;

    const bar = el("div", "card");
    bar.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin:20px 0;padding:16px 20px";
    bar.innerHTML = `<div><b>${data.puzzles.length}</b> 道待做
        <span class="muted">· 知识点：${kpParam ? kpParam.split(",").map((k) => (state.boot.kps.find((x) => x.id === k) || {}).name || k).join("、") : "全部"}</span></div>`;
    const reload = el("button", "btn sm", "换一批");
    reload.onclick = () => {
      location.hash = "#/practice?kp=" + kpParam + "&t=" + Date.now();
      route();
    };
    bar.appendChild(reload);

    const list = el("div", "quiz-list");
    if (!data.puzzles.length) {
      list.appendChild(el("div", "empty", "这个知识点暂时没有匹配的题目。试试换一个知识点或提高档位。"));
    }
    data.puzzles.forEach((p, i) => {
      const item = el("div", "quiz-item");
      item.innerHTML = `<div class="idx">${i + 1}</div>
        <div class="meta"><b>难度 ${p.rating}</b>${p.themes.slice(0, 3).map(themeCN).join(" · ")}</div>
        <button class="btn sm">开始</button>`;
      item.querySelector("button").onclick = () =>
        openPuzzleModal(p, { onDone: (ok) => item.classList.toggle("done", ok) });
      list.appendChild(item);
    });

    wrap.append(bar, list);
    app.appendChild(wrap);
  }

  // ------------------------------------------------------------------
  // 复盘
  // ------------------------------------------------------------------
  const DEMO_PGN = `[Event "示例：贪吃一个兵"]
[Site "?"]
[White "学员"]
[Black "对手"]
[Result "0-1"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 5. exd5 Nxd5 6. Nxf7 Kxf7
7. Qf3+ Ke6 8. Nc3 Ncb4 9. a3 Nxc2+ 10. Kd1 Nxa1 0-1`;

  async function viewReview() {
    const wrap = el("div");
    wrap.innerHTML = `<div class="eyebrow">PGN · 逐步复盘</div>
      <h1>导入一盘棋，逐步看关键转折</h1>
      <p class="lead">每一步都可以点。棋盘上红色箭头是你实际走的那一手，绿色箭头是引擎认为更好的一手；
      下面那条曲线是整盘的评估走势，往下掉的地方就是转折点。</p>`;

    const box = el("div", "card");
    box.style.marginTop = "24px";
    box.innerHTML = `<h3>粘贴棋谱</h3>`;
    const ta = el("textarea", "pgn");
    ta.style.minHeight = "150px";
    ta.placeholder = `[Event "训练对局"]
[White "你"]
[Black "对手"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 ...`;
    const row = el("div", "board-tools");
    row.style.marginTop = "12px";
    const sel = el("select", "btn sm");
    sel.style.paddingRight = "8px";
    sel.innerHTML = `<option value="auto">执子：自动判断</option><option value="white">我执白</option><option value="black">我执黑</option>`;
    const depth = reviewSearchDepth(19);
    const btn = el("button", "btn primary", "开始复盘");
    const btnDemo = el("button", "btn sm ghost", "填入示例");
    row.append(sel, depth, btn, btnDemo);
    box.append(ta, row);

    btnDemo.onclick = () => { ta.value = DEMO_PGN; };

    const out = el("div");
    out.style.marginTop = "20px";

    const history = el("div", "card rv-restore");
    history.style.marginTop = "24px";
    const games = el("select", "btn sm");
    games.setAttribute("aria-label", "已保存的复盘");
    const remove = label("button", "btn sm ghost", "删除所选复盘");
    const newGame = label("button", "btn sm", "导入新棋谱");
    const seePgn = label("button", "btn sm", "查看已保存棋谱");
    history.append(label("h3", "", "本地复盘"), games, seePgn, newGame, remove);
    let activeId = null;
    let selection = 0;

    function showGame(entry) {
      activeId = entry.res.id;
      games.value = String(activeId);
      remove.disabled = false;
      seePgn.disabled = !entry.pgn;
      seePgn.onclick = () => {
        ta.value = entry.pgn;
        sel.value = entry.color;
        depth.value = String(clampReviewDepth(entry.depth));
        box.hidden = false;
        ta.focus();
      };
      box.hidden = true;
      const player = el("div");
      out.replaceChildren(player);
      renderReviewResult(player, entry.res, { startPly: entry.ply || 0, depth: entry.depth });
    }

    async function openGame(id) {
      const version = ++selection;
      const entry = await api("/api/review/saved/" + id);
      if (version === selection && wrap.isConnected) showGame(entry);
    }

    async function refreshGames() {
      const { items } = await api("/api/review/saved");
      games.replaceChildren(new Option("选择一盘", ""));
      for (const item of items) {
        const h = item.headers;
        const date = new Date(item.created_at * 1000).toLocaleString("zh-CN");
        games.add(new Option(
          `${h.White || "白方"} vs ${h.Black || "黑方"} · ${date} · 停在第 ${item.ply} 手`,
          String(item.id),
        ));
      }
      history.hidden = !items.length;
      return items;
    }

    games.onchange = async () => {
      if (!games.value) { games.value = activeId || ""; return; }
      try { await openGame(games.value); }
      catch (e) { games.value = activeId || ""; toast(e.message); }
    };

    newGame.onclick = () => {
      ++selection;
      ta.value = "";
      box.hidden = false;
      ta.focus();
    };

    remove.onclick = async () => {
      if (!activeId || !window.confirm("删除这盘棋的复盘记录？")) return;
      ++selection;
      remove.disabled = true;
      try {
        await api("/api/review/saved/" + activeId, { method: "DELETE" });
        activeId = null;
        seePgn.disabled = true;
        out.replaceChildren();
        box.hidden = false;
        await refreshGames();
      } catch (e) {
        remove.disabled = !activeId;
        toast(e.message);
      }
    };
    remove.disabled = true;
    seePgn.disabled = true;
    history.hidden = true;

    try {
      const legacy = JSON.parse(localStorage.getItem("cc_review_last") || "null");
      if (legacy?.pgn && typeof legacy.pgn === "string") {
        const importOld = label("button", "btn sm", "载入旧版缓存棋谱");
        importOld.onclick = () => {
          ta.value = legacy.pgn;
          if (["auto", "white", "black"].includes(legacy.color)) sel.value = legacy.color;
          if (legacy.depth != null) depth.value = String(clampReviewDepth(legacy.depth));
          ta.focus();
        };
        row.append(importOld);
      }
    } catch {
      // A malformed legacy cache does not affect SQLite history.
    }

    btn.onclick = async () => {
      if (!ta.value.trim()) { toast("先粘贴一段 PGN"); return; }
      const version = ++selection;
      const pgn = ta.value;
      const color = sel.value;
      const engineDepth = parseInt(depth.value, 10);
      btn.disabled = true;
      btn.innerHTML = '<span class="spin"></span> 引擎分析中';
      out.innerHTML = "";
      try {
        const res = await apiPost("/api/review", {

          pgn,
          color,
          depth: engineDepth,
        });
        if (!wrap.isConnected) return;
        await refreshGames();
        if (version === selection) showGame({ res, ply: 0, pgn, color, depth: engineDepth });
        else games.value = activeId || "";
      } catch (e) {
        out.replaceChildren(label("div", "empty", e.message));
      } finally {
        btn.disabled = false;
        btn.textContent = "开始复盘";
      }
    };

    const note = el("div", "card");
    note.style.marginTop = "14px";
    note.innerHTML = `<div class="eyebrow">判定范围</div>
      <p style="font-size:13.5px;margin-bottom:10px">复盘由两部分组成，各自负责能负责的事：</p>
      <ul style="font-size:13.5px;color:var(--ink-2);padding-left:18px;margin:0">
        <li><b>引擎</b>：每一步的评估、整盘走势、更优走法（本地 Stockfish）</li>
        <li><b>规则</b>：把失误对到知识点（送子、漏杀、叉子、牵制、底线）</li>
      </ul>
      <p class="muted" style="margin-top:12px">兵形好坏、空间、计划是否合理这类需要判断的东西，仍然不做自动关联。</p>`;

    wrap.append(history, box, out, note);
    app.appendChild(wrap);
    try {
      const version = selection;
      const items = await refreshGames();
      if (items.length && selection === version && wrap.isConnected) await openGame(items[0].id);
    } catch (e) {
      toast(e.message);
    }
  }

  function fmtEval(cp, mate) {
    if (cp == null) return "—";
    if (mate != null) return (mate > 0 ? "+M" : "-M") + Math.abs(mate);
    if (Math.abs(cp) >= 9000) return cp > 0 ? "胜势" : "败势";
    return (cp > 0 ? "+" : "") + (cp / 100).toFixed(1);
  }

  function confirmedConceptStartMarks(rows, names) {
    const first = new Map();
    for (const row of rows) for (const concept of row.concepts || []) {
      if (!names.includes(concept.text)) continue;
      for (const round of concept.rounds || []) {
        if (Number.isInteger(round) && round > 0 && (!first.has(concept.text) || round < first.get(concept.text)))
          first.set(concept.text, round);
      }
    }
    const marks = {};
    for (const [text, round] of first) (marks[round * 2] ||= []).push(text);
    return marks;
  }

  function renderDecodeTree(turn, groups, openLines, selectedConcepts = new Set()) {
    const root = { children: new Map(), notes: new Map(), lines: new Set() };
    const inputs = [
      ["推荐着主变化", (groups.main || []).slice(0, 1)],
      ["实战着主变化", (groups.main || []).slice(1)],
      ["推荐着分支", groups.positive || []],
      ["实战着分支", groups.negative || []],
    ];
    for (const [title, rows] of inputs) {
      rows.forEach((row, index) => {
        const line = {
          label: rows.length === 1 ? title : `${title} ${index + 1}`,
          san: row.san, showArrow: true,
        };
        const path = [root];
        let node = root;
        for (const step of lineSteps(turn.fen, row.san).slice(1)) {
          if (!node.children.has(step.token)) {
            node.children.set(step.token, {
              token: step.token, children: new Map(), notes: new Map(), lines: new Set(),
              line, ply: path.length,
            });
          }
          node = node.children.get(step.token);
          node.lines.add(line);
          path.push(node);
        }
        function annotate(ply, text) {
          const target = path[ply];
          if (!target) return;
          if (!target.notes.has(text)) target.notes.set(text, []);
          target.notes.get(text).push({ line, ply });
        }
        for (const event of row.events || []) {
          const side = event.side === "white" ? "白方" : "黑方";
          const effect = {
            check: "将军", mate: "将死",
            capture_gain: `吃${event.target}，净赚 ${event.gain} 子力（后续 3 回合已确认）`,
          }[event.kind];
          if (effect) annotate(event.ply, side + effect);
        }
        for (const concept of row.concepts || []) {
          for (const round of (concept.rounds || []).slice(0, 1)) {
            annotate(round * 2, concept.text + "（连续验证通过的起点）");
          }
        }
      });
    }

    const trace = el("details", "explanation-concept decode-tree");
    trace.open = true;
    trace.append(label("summary", "", "逐回合事件与概念"));
    const start = el("div", "decode-tree-root");
    start.append(label("strong", "", `第 ${turn.move_no} 回合 · 行棋前局面`));
    const reset = label("button", "btn sm", "查看起始局面");
    reset.type = "button";
    reset.onclick = () => {
      const first = root.children.values().next().value;
      if (first) openLines([first.line], 0);
    };
    start.append(reset);
    trace.append(start);

    const nodes = {root:{san:"起点",ply:0,parentId:null,children:[],isMainline:true}};
    const sources = new Map();
    function collect(parent, parentId) {
      let index=0;
      for(const node of parent.children.values()) {
        const id = parentId + "/" + index;
        nodes[parentId].children.push(id);
        nodes[id]={san:node.token,ply:node.ply,parentId,children:[],isMainline:index===0,
          conceptMarks:[...node.notes.keys()].filter(text=>selectedConcepts.has(text.replace(/（.*$/, "")))};
        sources.set(id,node);
        collect(node,id);index++;
      }
    }
    collect(root,"root");
    trace.append(VariationTree({nodes,currentNodeId:"root",onSelect(id){
      const node=sources.get(id);
      if(node)openLines([node.line],node.ply);
      else {const first=root.children.values().next().value;if(first)openLines([first.line],0);}
    }}));
    return trace;
  }

  function clampReviewDepth(value) {
    const level = Number.parseInt(value, 10);
    return Number.isFinite(level) ? Math.max(10, Math.min(19, level)) : 19;
  }

  function reviewSearchDepth(value) {
    const select = el("select", "btn sm");
    select.setAttribute("aria-label", "Stockfish 搜索深度");
    for (let level = 10; level <= 19; level++) {
      select.add(new Option(`深度 ${level}`, String(level)));
    }
    select.value = String(clampReviewDepth(value));
    return select;
  }

  function renderReviewResult(host, res, opts = {}) {
    const moves = res.moves || [];
    let savedPly = opts.startPly || 0;
    if (!moves.length) {
      host.appendChild(el("div", "empty", "这盘棋没有可回放的着法。"));
      return;
    }
    const playerIsWhite = res.player === "white";
    const orientation = playerIsWhite ? "white" : "black";
    const curve = res.eval_curve || [];
    const tps = res.turning_points || [];
    const tpByPly = {};
    tps.forEach((t, i) => { tpByPly[t.ply] = i; });

    // ---------- 左侧：棋盘 + 步进 + 曲线 + 着法列表 ----------
    const leftCol = el("div");
    leftCol.style.cssText = "display:grid;gap:14px;min-width:0;width:100%";

    const boardCard = el("div", "card rv-board-card");
    const topLine = el("div", "rv-eval-top");
    const posLabel = el("div", "muted");
    const evalBadge = el("span", "badge", "0.0");
    const tagBadge = el("span", "");
    topLine.append(posLabel, evalBadge, tagBadge);

    const boardHost = el("div");
    const steps = el("div", "rv-steps");
    const bFirst = el("button", "", "⏮");
    const bPrev = el("button", "", "◀");
    const posText = el("span", "pos", "0 / 0");
    const bNext = el("button", "", "▶");
    const bLast = el("button", "", "⏭");
    steps.append(bFirst, bPrev, posText, bNext, bLast);

    const movelist = el("div", "rv-moves");
    boardCard.append(topLine, boardHost, steps, movelist);

    // 曲线
    const chartCard = el("div", "card");
    chartCard.style.padding = "12px 14px";
    const chart = el("div", "rv-chart");
    chartCard.appendChild(chart);

    leftCol.append(boardCard, chartCard);

    const branchBar=el("div","board-tools");
    const searchDepth = reviewSearchDepth(opts.depth);
    searchDepth.onchange = () => {
      revision++;
      reply.disabled = false;
    };
    const reply=label("button","btn sm primary","引擎应手");
    const undo=label("button","btn sm","撤回变化一步");
    const back=label("button","btn sm","返回主线");
    const choose=el("select"); choose.setAttribute("aria-label","选择试走变化");
    const branchInfo=label("div","muted","");
    const exportFen = label("button", "btn sm", "导出 FEN");
    exportFen.type = "button";
    exportFen.onclick = () => {
      // Snapshot the displayed board, including any user-created variation.
      const fen = board.fen;
      const dialog = el("dialog", "card");
      dialog.style.cssText = "width:min(620px,calc(100% - 32px));max-height:85vh;overflow:auto";
      dialog.setAttribute("aria-label", "导出当前棋盘 FEN");
      const title = label("h3", "", "导出当前棋盘 FEN");
      const field = el("textarea", "pgn");
      field.value = fen;
      field.readOnly = true;
      field.style.minHeight = "85px";
      field.setAttribute("aria-label", "当前局面完整 FEN");
      const status = label("p", "muted", "包含行棋方、易位权、吃过路兵及回合计数。此处为打开时的局面快照。");
      status.setAttribute("aria-live", "polite");
      const tools = el("div", "board-tools");
      const copy = label("button", "btn sm primary", "复制 FEN");
      copy.onclick = async () => {
        try {
          await navigator.clipboard.writeText(fen);
          status.textContent = "FEN 已复制。";
        } catch {
          field.focus(); field.select();
          status.textContent = "自动复制不可用，已选中 FEN，请按 Ctrl+C 复制。";
        }
      };
      const download = label("button", "btn sm", "下载 .fen");
      download.onclick = () => {
        const url = URL.createObjectURL(new Blob([fen + "\n"], {type:"text/plain;charset=utf-8"}));
        const link = document.createElement("a");
        link.href = url; link.download = "chess-position.fen";
        dialog.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      const close = label("button", "btn sm", "关闭");
      close.onclick = () => dialog.close();
      tools.append(copy, download, close);
      dialog.append(title, field, status, tools);
      dialog.addEventListener("close", () => { rvModalOpen = Math.max(0, rvModalOpen - 1); dialog.remove(); }, {once:true});
      document.body.append(dialog);
      dialog.showModal();
      rvModalOpen++;
    };
    branchBar.append(reply,undo,back,exportFen,choose);
    boardCard.insertBefore(branchBar,movelist);
    boardCard.insertBefore(branchInfo,movelist);
    const roots=new Map();
    let branch=null, revision=0;
    const board = new Board(boardHost, {
      fen: moves[0].fen,
      orientation,
      interactive: true,
      onMove(mv) { addBranch(mv); },
    });

    function chain(node) {
      const path=[];
      for(let n=node;n&&n.parent;n=n.parent)path.unshift(n);
      return path;
    }
    function root() {
      if(!roots.has(cur)) roots.set(cur,{fen:fenAt(cur),parent:null,children:[]});
      return roots.get(cur);
    }
    function updateBranch() {
      revision++;
      reply.disabled=false;
      undo.disabled=!branch;
      back.disabled=!branch;
      const current=branch||root();
      const all=[];
      function visit(n) { for(const child of n.children){all.push(child);visit(child);} }
      visit(root());
      choose.replaceChildren(new Option("查看已试走的变化",""));
      all.forEach((n,i)=>choose.add(new Option(chain(n).map(x=>x.san).join(" "),String(i))));
      choose.value=branch ? String(all.indexOf(branch)) : "";
      choose.hidden=!all.length;
      choose.onchange=()=>{if(choose.value!=="") showBranch(all[Number(choose.value)]);else renderPly(cur);};
      branchInfo.textContent=branch ? "变化 · "+chain(branch).map(n=>n.san).join(" ") : "可直接在棋盘试走，主线保持不变。";
    }
    function showBranch(node) {
      if(!node.parent){renderPly(cur);return;}
      branch=node;
      if (board._reviewEvidenceDispose) board._reviewEvidenceDispose();
      board.setMarks([]);
      board.setFen(node.fen);
      board.setLastMove(node.uci.slice(0,2),node.uci.slice(2,4));
      board.setArrows([]);
      posLabel.textContent="变化 · 从主线第 "+cur+" 半回合分叉";
      evalBadge.textContent="变化盘面";
      tagBadge.textContent="";
      updateBranch();
      renderTurn();
    }
    function addBranch(mv) {
      const parent=branch||root(), uci=mv.from+mv.to+(mv.promotion||"");
      let node=parent.children.find(x=>x.uci===uci);
      if(!node){node={parent,uci,san:mv.san,fen:board.fen,children:[]};parent.children.push(node);}
      showBranch(node);
    }
    undo.onclick=()=>{if(branch)showBranch(branch.parent);};
    back.onclick=()=>renderPly(cur);
    reply.onclick=async()=>{
      const version=++revision;
      reply.disabled=true;
      try {
        const result=await apiPost("/api/analysis/position", {
          initial:moves[0].fen, history:moves.slice(0,cur).map(m=>m.uci).concat(chain(branch).map(m=>m.uci)),
          depth: Number(searchDepth.value)
        });
        if(version!==revision||!boardHost.isConnected)return;
        if(result.status!=="ok"){toast(result.status==="finished"?"这条变化已经结束":"引擎暂不可用");return;}
        const u=result.uci;
        const mv=board.chess.move({from:u.slice(0,2),to:u.slice(2,4),promotion:u[4]});
        if(mv){addBranch(mv);branchInfo.textContent+=" · 引擎："+result.san;}
      }catch(e){if(version===revision)toast(e.message);}
      finally{if(version===revision)reply.disabled=false;}
    };

    // 把一条 SAN 变化灌进大棋盘的变化树，接着就能用现有按钮继续试走
    function playLineOnBoard(startPly, sans, step) {
      if (!sans || !sans.length) return;
      renderPly(startPly, { keepTp: true, noArrows: true });
      let selected = root();
      for (const [i, san] of sans.entries()) {
        let mv = null;
        try { mv = board.chess.move(san, { sloppy: true }); } catch (e) { mv = null; }
        if (!mv) break;
        addBranch(mv);
        if (i < step) selected = branch;
      }
      showBranch(selected);
      boardCard.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    // 初始局面（第 0 个半回合之前）
    function fenAt(ply) {
      if (ply <= 0) return moves[0].fen;
      const m = moves[ply - 1];
      try {
        const c = new Chess(m.fen);
        const from = m.uci.slice(0, 2), to = m.uci.slice(2, 4);
        const mv = c.move({ from, to, promotion: m.uci[4] || "q" });
        if (!mv) return m.fen;
        return c.fen();
      } catch (e) {
        return m.fen;
      }
    }

    let cur = 0;

    function renderPly(ply, opts2 = {}) {
      cur = Math.max(0, Math.min(moves.length, ply));
      branch=null;
      updateBranch();
      if (board._reviewEvidenceDispose) board._reviewEvidenceDispose();
      board.setMarks([]);
      board.setFen(fenAt(cur));

      if (cur > 0) {
        const m = moves[cur - 1];
        board.setLastMove(m.from, m.to);
      }
      board.setArrows([]);

      // 位置与评估
      const node = curve[cur];
      const m = cur > 0 ? moves[cur - 1] : null;
      if (m) {
        posLabel.innerHTML = `第 ${m.move_no} 回合 · ${m.side === "white" ? "白" : "黑"} · <b>${m.san}</b>`;
      } else {
        posLabel.innerHTML = `开局 · ${playerIsWhite ? "你执白" : "你执黑"}`;
      }
      const cp = node?.cp == null ? null : node.cp * (playerIsWhite ? 1 : -1);
      const mate = node && node.mate != null ? node.mate * (playerIsWhite ? 1 : -1) : null;
      evalBadge.textContent = cp === null ? "待分析" : fmtEval(cp, mate);
      evalBadge.className = "badge " + (cp >= 60 ? "good" : cp <= -60 ? "bad" : "");

      const tag = m ? m.tag : null;
      const tagText = { blunder: "重大失误", mistake: "明显失误", inaccuracy: "不够精确", great: "好棋" }[tag] || "";
      tagBadge.className = "tag " + (tag || "");
      tagBadge.textContent = tagText;

      // 如果是转折点，画两条箭头
      if (m && tpByPly[cur] != null && !opts2.noArrows) {
        const t = tps[tpByPly[cur]];
        const list = [{ from: t.from, to: t.to, color: "red" }];
        if (t.best && t.best.uci && !t.best_is_played) {
          list.push({ from: t.best.uci.slice(0, 2), to: t.best.uci.slice(2, 4), color: "green" });
        }
        board.setArrows(list);
      }

      posText.textContent = `${cur} / ${moves.length}`;
      bFirst.disabled = bPrev.disabled = cur === 0;
      bNext.disabled = bLast.disabled = cur === moves.length;

      // 着法列表高亮
      movelist.querySelectorAll(".mv").forEach((n) => {
        n.classList.toggle("on", parseInt(n.dataset.ply, 10) === cur);
      });

      // 更新右侧选中态
      if (cur > 0 && tpByPly[cur] != null) selectTp(tpByPly[cur], false);
      else if (!opts2.keepTp) {
        document.querySelectorAll(".tp").forEach((n) => n.classList.remove("on"));
      }
      renderTurn();
      moveCursor();
      if (res.id && cur !== savedPly) {
        savedPly = cur;
        api("/api/review/saved/" + res.id + "/position", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ ply: cur }),
          keepalive: true,
        }).catch(() => toast("棋步位置保存失败"));
      }
    }

    bFirst.onclick = () => renderPly(0);
    bPrev.onclick = () => renderPly(cur - 1);
    bNext.onclick = () => renderPly(cur + 1);
    bLast.onclick = () => renderPly(moves.length);

    // 着法列表
    const rows = Math.ceil(moves.length / 2);
    for (let i = 0; i < rows; i++) {
      const no = el("div", "no", String(moves[i * 2].move_no));
      movelist.appendChild(no);
      for (let k = 0; k < 2; k++) {
        const m = moves[i * 2 + k];
        if (!m) { movelist.appendChild(el("div")); continue; }
        const cls = "mv" + (m.tag === "blunder" ? " bad" : m.tag === "mistake" || m.tag === "inaccuracy" ? " warn" : "");
        const span = el("div", cls, m.san);
        span.dataset.ply = m.ply;
        span.onclick = () => renderPly(m.ply);
        movelist.appendChild(span);
      }
    }

    // ---------- 评估曲线 ----------
    function drawChart() {
      chart.innerHTML = "";
      if (!curve.length) return;
      const W = 1000, H = 200, MID = H / 2;
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      svg.setAttribute("preserveAspectRatio", "none");
      const peak = curve.reduce((m, p) => Math.max(m, Math.min(900, Math.abs(p.cp))), 120);
      const span = Math.max(180, peak * 1.15);
      const clamp = (cp) => Math.max(-span, Math.min(span, cp));
      const y = (cp) => MID - (clamp(cp) / span) * (MID - 8) * (playerIsWhite ? 1 : -1);
      const x = (ply) => (curve.length === 1 ? 0 : (ply / (curve.length - 1)) * W);

      const mid = document.createElementNS("http://www.w3.org/2000/svg", "line");
      mid.setAttribute("x1", 0); mid.setAttribute("x2", W);
      mid.setAttribute("y1", MID); mid.setAttribute("y2", MID);
      mid.setAttribute("stroke", "#ddd6c7"); mid.setAttribute("stroke-width", "1");
      svg.appendChild(mid);

      let d = "";
      curve.forEach((p, i) => { if (p.cp != null) d += (i && curve[i-1].cp != null ? " L" : " M") + x(i) + " " + y(p.cp); });
      const area = document.createElementNS("http://www.w3.org/2000/svg", "path");
      area.setAttribute("d", d + ` L${W} ${MID} L0 ${MID} Z`);
      area.setAttribute("fill", "rgba(47,111,78,.10)");
      svg.appendChild(area);

      const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
      line.setAttribute("d", d);
      line.setAttribute("fill", "none");
      line.setAttribute("stroke", "#2f6f4e");
      line.setAttribute("stroke-width", "2");
      line.setAttribute("stroke-linejoin", "round");
      svg.appendChild(line);

      tps.forEach((t) => {
        const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("cx", x(t.ply));
        c.setAttribute("cy", y((curve[t.ply] || {}).cp || 0));
        c.setAttribute("r", t.tag === "blunder" ? 6 : 4.5);
        c.setAttribute("fill", t.tag === "blunder" ? "#b3452f" : "#b8791d");
        c.setAttribute("stroke", "#fff");
        c.setAttribute("stroke-width", "1.5");
        svg.appendChild(c);
      });

      const cursor = document.createElementNS("http://www.w3.org/2000/svg", "line");
      cursor.setAttribute("id", "rvCursor");
      cursor.setAttribute("y1", 0); cursor.setAttribute("y2", H);
      cursor.setAttribute("stroke", "#1d1f1c"); cursor.setAttribute("stroke-width", "1.5");
      cursor.setAttribute("stroke-dasharray", "4 3");
      cursor.setAttribute("x1", x(cur)); cursor.setAttribute("x2", x(cur));
      svg.appendChild(cursor);

      svg.onclick = (e) => {
        const r = svg.getBoundingClientRect();
        const ratio = (e.clientX - r.left) / r.width;
        const ply = Math.round(ratio * (curve.length - 1));
        renderPly(ply);
        moveCursor();
      };
      chart.appendChild(svg);
      chart.appendChild(el("div", "cap", `${playerIsWhite ? "白" : "黑"}方视角 · 曲线往上是你更好，往下掉的地方就是转折点`));
    }

    function moveCursor() {
      const svg = chart.querySelector("svg");
      if (!svg) return;
      const line = svg.querySelector("#rvCursor");
      if (!line) return;
      const x = curve.length === 1 ? 0 : (cur / (curve.length - 1)) * 1000;
      line.setAttribute("x1", x);
      line.setAttribute("x2", x);
    }

    // ---------- 右侧：概览 + 转折点 + 学习动作 ----------
    const s = res.stats || {};
    const rightCol = el("div", "rv-side");
    rightCol.style.minWidth = "0";
    const sum = el("div", "rv-sum");
    sum.innerHTML = `
      <div class="s"><b>${res.plies}</b><span>半回合</span></div>
      <div class="s"><b style="color:var(--red)">${s.blunders || 0}</b><span>重大失误</span></div>
      <div class="s"><b style="color:var(--amber)">${s.mistakes || 0}</b><span>明显失误</span></div>
      <div class="s"><b style="color:var(--ink-2)">${s.inaccuracies || 0}</b><span>不够精确</span></div>
      <div class="s"><b>${res.avg_loss == null ? "—" : res.avg_loss}</b><span>平均每步损失（厘兵）</span></div>
      <div class="s"><b>${res.engine && res.engine.used ? "引擎" : "规则"}</b><span>分析来源</span></div>`;
    rightCol.appendChild(sum);

    let activeTp = -1;
    let activeTab = 'explanation';
    const pendingExplanations = new Set();
    const turnCard = el("section", "card rv-turn-card");
    const turnHead = el("div", "rv-turn-head");
    const turnTitle = label("h2", "", "转折点分析");
    const turnSelect = el("select", "btn sm");
    turnSelect.setAttribute("aria-label", "选择转折点");
    tps.forEach((t, i) => turnSelect.add(new Option(`${i + 1}. ${t.move_no}${t.side === "white" ? "." : "…"} ${t.san}`, String(i))));
    turnSelect.onchange = () => jumpTurn(Number(turnSelect.value));
    turnHead.append(turnTitle, turnSelect);
    const turnMeta = el("div", "rv-turn-meta");
    const turnTabs = el("div", "rv-turn-tabs");
    turnTabs.setAttribute("role", "tablist");
    const turnBody = el("div", "rv-turn-body");
    const turnNav = el("div", "rv-turn-nav");
    const prevTurn = label("button", "btn sm", "↑ 上个转折点");
    const nextTurn = label("button", "btn sm", "下个转折点 ↓");
    prevTurn.onclick = () => jumpTurn(activeTp - 1);
    nextTurn.onclick = () => jumpTurn(activeTp + 1);
    turnNav.append(prevTurn, nextTurn);
    for (const [id, text] of [["explanation", "本步讲解"], ["features", "局面特征"], ["learning", "学习"]]) {
      const button = label("button", "", text);
      button.type = "button";
      button.setAttribute("role", "tab");
      button.dataset.tab = id;
      button.onclick = () => { activeTab = id; renderTurn(); };
      turnTabs.append(button);
    }
    turnCard.append(turnHead, turnMeta, turnTabs, turnBody, turnNav);
    rightCol.append(turnCard);
    if (!tps.length) turnCard.replaceChildren(label("p", "muted", "这盘棋没有找到明显的转折点。"));

    const moveExplanations = new Map();
    const decodeDialog = el("dialog", "card");
    decodeDialog.style.cssText = "width:min(760px,calc(100% - 32px));max-height:85vh;overflow:auto;";
    decodeDialog.setAttribute("aria-label", "转折点解说");
    const closeDecode = label("button", "btn sm", "关闭");
    closeDecode.type = "button";
    closeDecode.onclick = () => decodeDialog.close();
    const decodeHead = el("div", "board-tools");
    decodeHead.append(label("strong", "", "转折点解说"), closeDecode);
    const decodeStatus = el("p", "muted");
    decodeStatus.setAttribute("aria-live", "polite");
    const decodeResults = el("div");
    decodeDialog.append(decodeHead, decodeStatus, decodeResults);

    function renderMoveExplanation(panel, t, result) {
      const selectedConcepts = new Set((result.motifs || []).map(m => m.text));
      function decorated(lines) {
        return lines.map(line => {
          const concepts = line.concepts || result.motifs || [];
          const rows = Object.values(result.round_events || {}).flat().filter(row => row.san.join(" ") === line.san.join(" "));
          return {...line, concepts, conceptMarks: confirmedConceptStartMarks(rows, concepts.map(c=>c.text))};
        });
      }

      function openLines(lines, startIndex = 1) {
        openVariationPlayer({
          title: "推荐着 vs 实战着",
          subtitle: `第 ${t.move_no} 回合${t.side === "white" ? "（白）" : "（黑）"} · 实战 ${t.san}`
            + ` · 推荐 ${t.best.san}`,
          fen: t.fen,
          orientation,
          lines: decorated(lines),
          modalHost: decodeDialog.open ? decodeDialog : undefined,
          onBoard: (sans, step) => {
            decodeDialog.close();
            if (t.onBoard) t.onBoard(sans, step);
            else playLineOnBoard(t.ply - 1, sans, step);
          },
          startIndex,
        });
      }

      function appendLine(parent, title, san, concept = null) {
        const row = el("p", "explanation-line");
        row.append(label("strong", "", title + " "));
        const line = { label: title, san, showArrow: true, ...(concept ? {concepts:[concept]} : {}) };
        lineSteps(t.fen, san).slice(1).forEach((step, i) => {
          const move = label("button", "btn sm", step.token);
          move.type = "button";
          move.onclick = () => openLines([line], i + 1);
          const marks = decorated([line])[0].conceptMarks[i + 1] || [];
          if (marks.length) { move.classList.add("concept-true"); move.title = marks.join("；"); }
          row.append(move, " ");
        });
        parent.append(row);
      }

      if (result.same_move) panel.append(label("p", "", "候选着就是引擎推荐着，展示这一步的变化与概念。"));
      if (result.status !== "ok") {
        panel.append(label("p", "", {
          insufficient: "可比较的分支太少，暂时无法提取稳定的棋理。",
          no_match: "在已分析的分支中，没有找到能稳定区分两手棋的概念。",
          unavailable: "棋理解说暂不可用。",
        }[result.status] || "棋理解说暂不可用。"));
      }
      if (result.mate_outcome) {
        const text = {
          both_win: "两步都能强制将死对方，这里视为等价。",
          both_lose: "两步都会被对方强制将死，这里视为等价。",
          played_win: "实战着可以强制将死对方。",
          recommended_lose: "推荐着会被对方强制将死。",
        }[result.mate_outcome];
        panel.append(label("p", "", text));
        appendLine(panel, "推荐着主变化", result.positive_example);
        appendLine(panel, "实战着主变化", result.negative_example);
      }
      if (result.opponent_reply) {
        const reply = result.opponent_reply;
        const effect = reply.kind === "mate"
          ? "引擎判断我方最佳防守也会被将死。"
          : `沿双方的引擎主变化，对方吃掉我方的${reply.target}后仍净赚子力。`;
        const title = el("p");
        title.append(label("strong", "", "实战着允许对方做什么"), " · ", effect);
        panel.append(title);
        const line = reply.branches[0];
        const mateLabel = line.at(-1)?.endsWith("#") ? "最佳防守下的将杀" : "强制将杀的主变化节选";
        appendLine(panel, reply.forced ? mateLabel : "实战着主变化", line);
      }
      if (result.material_gain) {
        const gain = result.material_gain;
        panel.append(label("p", "", `沿双方的引擎主变化，推荐着能吃掉对方的${gain.target}并保住净收益。`));
        appendLine(panel, "推荐着得子", gain.branches[0]);
      }
      if (result.mate) {
        const mate = result.mate;
        const title = el("p");
        if (mate.forced) {
          title.append(label("strong", "", "强制将杀"), " · 引擎判断对方最佳防守也无法避免被将死。");
        } else {
          title.append("这么走的", label("strong", "", "意图"), "是将死对方。");
        }
        panel.append(title);
        if (!mate.forced) {
          panel.append(label("p", "", `推荐着 ${mate.branches.length}/${result.positive_count} 条采样分支走到将死，实战着 ${mate.played_hits}/${result.negative_count} 条。`));
        }
        if (mate.main.length) {
          const mateLabel = mate.main.at(-1).endsWith("#") ? "最佳防守下的将杀" : "强制将杀的主变化节选";
          appendLine(panel, mate.forced ? mateLabel
            : mate.main.at(-1).endsWith("#") ? "引擎主变化"
            : "引擎最佳防守（未发现强制将杀）", mate.main);
        }
        mate.branches.forEach((san, i) => {
          if (san.join(" ") !== mate.main.join(" ")) appendLine(panel, `将杀变化 ${i + 1}`, san);
        });
      }
      for (const motif of result.motifs || []) {
        const details = el("details", "explanation-concept");
        const summary = el("summary");
        const tier = motif.tier || "strict";
        if (tier === "mainline") summary.append(label("strong", "", "主变化说明"));
        else if (tier === "branch_gap") summary.append(label("strong", "", "部分分支中的意图"));
        else if (motif.stable) summary.append(label("strong", "", "跨分支支持 · 推荐主变化"));
        else summary.append(label("strong", "", "跨分支支持的意图"));
        summary.append(" · ");
        if (motif.maintained) {
          const maintain = label("strong", "", "维持");
          maintain.style.color = "#1d1f1c";
          summary.append(maintain, " ");
        }
        summary.append(motif.text);
        if (motif.description) summary.title = motif.description;
        summary.append(`（采样分支：推荐着 ${motif.positive_hits}/${result.positive_count} 条，实战着 ${motif.negative_hits}/${result.negative_count} 条）`);
        details.append(summary);
        if (motif.description) {
          const help = el("details", "concept-rule-help");
          help.append(label("summary", "muted", "判定说明"), label("p", "", motif.description));
          details.append(help);
        }
        if (tier === "mainline") details.append(label("p", "muted", "沿本次双方最佳应对主线，推荐着后确认出现该概念，实战着主线未确认出现；这不代表所有采样分支都支持。"));
        if (tier === "branch_gap") details.append(label("p", "muted", "推荐采样分支的确认命中数比实战至少多2条；这是部分分支中的意图，不代表多数分支或最佳应对主线都能实现。"));
        if (motif.negative_pending) details.append(label("p", "muted", `实战组还有 ${motif.negative_pending} 条分支待确认。`));
        motif.branches.forEach((san, i) => appendLine(details, `变化 ${i + 1}`, san, motif));
        panel.append(details);
      }
      if (result.concept_descriptions) {
        const help = el("details", "concept-rule-help");
        help.append(label("summary", "muted", "全部 30 个概念的判定说明"));
        for (const [name, description] of Object.entries(result.concept_descriptions)) {
          const item = el("details");
          const title = label("summary", "", result.concept_names?.[name] || name);
          title.title = description;
          item.append(title, label("p", "", description));
          help.append(item);
        }
        panel.append(help);
      }
      if (result.round_events) {
        const tree = renderDecodeTree(t, result.round_events, openLines, selectedConcepts);
        for (const note of tree.querySelectorAll('.decode-tree-note')) {
          if ([...selectedConcepts].some(text => note.textContent.startsWith(text))) {
            note.textContent = '◆ ' + note.textContent;
            note.style.borderLeftColor = '#b8791d';
            note.style.fontWeight = 'bold';
          }
        }
        panel.append(tree);
      }
      const lines = variationLines(t, result);
      if (!lines.length) return;
      const view = label("button", "btn sm", lines.length > 1 ? "对比两条变化" : "查看推荐着变化");
      view.onclick = () => openLines(lines);
      const tools = el("div", "board-tools");
      tools.append(view);
      panel.append(tools);
    }

    const decodeTools = el("div", "board-tools");
    decodeTools.append(searchDepth);
    rightCol.prepend(decodeTools);
    rightCol.append(decodeDialog);
    const previousDepthChange = searchDepth.onchange;
    searchDepth.onchange = () => {
      if (previousDepthChange) previousDepthChange();
      renderTurn();
    };

    function jumpTurn(i) {
      if (i < 0 || i >= tps.length) return;
      renderPly(tps[i].ply);
      selectTp(i, false);
    }

    function selectTp(i) {
      if (!tps[i]) return;
      activeTp = i;
      renderTurn();
    }

    function renderTurn() {
      if (board._reviewEvidenceDispose) board._reviewEvidenceDispose();
      const t = tps[activeTp];
      if (!t) return;
      turnSelect.value = String(activeTp);
      turnTitle.textContent = `${t.move_no}${t.side === "white" ? "." : "…"} ${t.san} · ${t.title || "转折点"}`;
      prevTurn.disabled = activeTp <= 0;
      nextTurn.disabled = activeTp >= tps.length - 1;
      const tag = {blunder:"重大失误",mistake:"明显失误",inaccuracy:"不够精确",rule:"规则检测"}[t.tag] || "转折点";
      turnMeta.replaceChildren(label("span", "pill", tag));
      if (t.eval_before != null && t.eval_after != null)
        turnMeta.append(label("span", "muted", `${t.eval_before} → ${t.eval_after}`));
      if (t.best?.san) turnMeta.append(label("span", "best-line", `更好：${t.best.san}`));
      if (branch || cur !== t.ply) turnMeta.append(label("p", "muted rv-turn-context", `当前棋盘${branch ? "正在试走变化" : "停在其他棋步"}；本卡片分析第 ${t.move_no} 回合 ${t.san}。`));
      for (const button of turnTabs.children) {
        const selected = button.dataset.tab === activeTab;
        button.classList.toggle("on", selected);
        button.setAttribute("aria-selected", String(selected));
      }
      turnBody.replaceChildren();
      const selectedDepth = Number(searchDepth.value);
      const cacheKey = `${selectedDepth}:${t.ply}`;
      if (activeTab === "explanation") {
        const tools = el("div", "board-tools");
        const decode = label("button", "btn sm primary", pendingExplanations.has(cacheKey) ? "Decode 分析中…" : "Decode 这个转折点");
        decode.disabled = pendingExplanations.has(cacheKey) || !t.best?.uci || t.best.uci === t.uci;
        tools.append(decode);
        if (t.best?.san) {
          const view = label("button", "btn sm", "查看完整变化");
          view.onclick = () => openVariationPlayer({title: `更优走法 ${t.best.san}`, subtitle: `第 ${t.move_no} 回合 · 实战 ${t.san}`, fen:t.fen, orientation,
            lines:variationLines(t), onBoard:(sans, step)=>playLineOnBoard(t.ply - 1, sans, step)});
          tools.append(view);
        }
        const tryMove = label("button", "btn sm", "自己试走");
        tryMove.onclick = () => { renderPly(t.ply - 1, {keepTp:true, noArrows:true}); boardCard.scrollIntoView({block:"nearest", behavior:"smooth"}); };
        tools.append(tryMove);
        turnBody.append(tools);
        const result = moveExplanations.get(cacheKey);
        if (result) renderMoveExplanation(turnBody, t, result);
        else turnBody.append(label("p", "muted rv-decode-hint", pendingExplanations.has(cacheKey) ? "正在分析这个转折点，可以切换查看其他转折点。" : "点击 Decode 这个转折点后显示解析。"));
        decode.onclick = async () => {
          if (pendingExplanations.has(cacheKey)) return;
          pendingExplanations.add(cacheKey);
          renderTurn();
          let error = null;
          try {
            const result = await apiPost("/api/analysis/explain-move", {
              fen:t.fen, recommended:t.best.uci, played:t.uci,
              initial:moves[0].fen, history:moves.slice(0,t.ply - 1).map(m=>m.uci), depth:selectedDepth,
            });
            if (result.status === "unavailable") error = "棋理解说暂不可用，请重试。";
            else moveExplanations.set(cacheKey,result);
          } catch (e) { error = e.message || "分析失败，请重试。"; }
          finally {
            pendingExplanations.delete(cacheKey);
            if (turnCard.isConnected && tps[activeTp] === t && Number(searchDepth.value) === selectedDepth) {
              renderTurn();
              if (error && activeTab === "explanation") turnBody.append(label("p", "muted", error));
            }
          }
        };
      } else if (activeTab === "features") {
        const result = moveExplanations.get(cacheKey);
        const concepts = result?.motifs || [];
        if (!concepts.length) turnBody.append(label("p", "muted", "请先 Decode 这个转折点；这里仅展示最终解析中实际出现的概念。"));
        else {
          for (const concept of concepts) {
            const show = label("button", "btn sm", "可视化：" + concept.text);
            show.onclick = () => {
              const rows = Object.values(result.round_events || {}).flat();
              const row = rows.find(row => (row.concepts || []).some(c => c.text === concept.text && (c.true_rounds || c.rounds).length));
              const evidence = row?.concepts.find(c=>c.text===concept.text);
              if (!row || !evidence) { toast("没有该概念为 true 的局面证据。"); return; }
              const step = (evidence.true_rounds || evidence.rounds)[0] * 2;
              playLineOnBoard(t.ply - 1, row.san, step);
              const target = el("div", "concept-visualization");
              turnBody.append(target);
              renderConceptVisualization(target, board, board.fen, [concept]);
            };
            turnBody.append(show);
          }
        }
      } else {
        if (t.kp_name) turnBody.append(label("h3", "", t.kp_name));
        const matches = t.similar_puzzles || [];
        turnBody.append(label("p", "muted", matches.length ? `高度相似题：${matches.length} 道` : "暂未找到足够相似的题"));
        for (const p of matches) {
          const practice = label("button", "btn sm", "练习 #" + p.id);
          practice.onclick = () => openPuzzleModal(p);
          turnBody.append(practice);
        }
        const learn = label("button", "btn sm", "围绕这步学习");
        learn.onclick = () => { state.learningReview = {...t, reviewId:res.id}; location.hash = "#/learning"; };
        turnBody.append(learn);
      }
    }

    // 学习动作（知识点 → 题目）
    const focus = res.focus || {};
    if (focus.review || focus.new) {
      const head = el("div");
      head.innerHTML = `<h2 style="margin:14px 0 10px">从这盘棋练什么</h2>`;
      rightCol.appendChild(head);
      const actions = el("div");
      actions.style.cssText = "display:grid;grid-template-columns:1fr;gap:14px";
      const mk = (f, kind) => {
        if (!f) return el("div");
        const c = el("div", "focus-card" + (kind === "new" ? " new" : ""));
        const kp = f.kp || { name: f.title, summary: "" };
        c.innerHTML = `<div class="eyebrow">${kind === "new" ? "新知识点" : "复习"}</div>
          <div class="focus-kp">${kp.name}</div>
          <div class="focus-why">${state.boot.tutorials_published ? kp.summary || "" : ""}</div>
          <div class="muted" style="margin-bottom:10px">${f.count ? "本局已核验的关联失误 "+f.count+" 次" : "拓展学习 · 与本局失误无关"}</div>`;
        const list = el("div", "quiz-list");
        const pz = (f.puzzles && f.puzzles.review && f.puzzles.review.length ? f.puzzles.review : (f.puzzles && f.puzzles.new) || []);
        pz.slice(0, 2).forEach((p) => {
          const it = el("div", "quiz-item");
          it.innerHTML = `<div class="idx">题</div><div class="meta"><b>难度 ${p.rating}</b>
            ${p.themes.slice(0, 2).map(themeCN).join(" · ")}</div><button class="btn sm">做</button>`;
          it.querySelector("button").onclick = () => openPuzzleModal(p);
          list.appendChild(it);
        });
        if (!pz.length) list.appendChild(el("div", "muted", "这个知识点下暂时没有匹配难度的题。"));
        c.appendChild(list);
        const lessonId = lessonForKp(kp.id || f.kp_id);
        if (lessonId) c.appendChild(link("看这一课", "#/lesson/" + lessonId));
        return c;
      };
      actions.append(mk(focus.review, "review"), mk(focus.new, "new"));
      rightCol.appendChild(actions);
    }

    // 规则检测的完整列表（保留可查）
    if (res.findings && res.findings.length) {
      const det = el("details");
      det.style.cssText = "margin-top:16px;font-size:13px";
      det.innerHTML = `<summary class="muted" style="cursor:pointer">规则检测明细（${res.findings.length} 条）</summary>`;
      const box = el("div");
      box.style.cssText = "margin-top:10px;display:grid;gap:8px";
      res.findings.slice(0, 20).forEach((f) => {
        const row = el("div", "finding");
        row.style.cursor = "default";
        row.innerHTML = `<div class="sev ${SEV_CLASS(f.severity)}"></div>
          <div class="fbody">
            <div class="ftitle">${f.title} <span class="muted" style="font-weight:400">第 ${f.move_no} 回合 ${f.san}</span></div>
            <div class="fdetail">${f.detail}</div>
            <div class="fmeta"><span class="pill">${f.level}</span><span class="pill blue">${f.kp_name}</span></div>
          </div>`;
        box.appendChild(row);
      });
      det.appendChild(box);
      rightCol.appendChild(det);
    }

    host.append(leftCol, rightCol);
    host.style.display = "grid";
    host.style.gridTemplateColumns = "minmax(0, 430px) minmax(0, 1fr)";
    host.style.gap = "24px";
    host.style.alignItems = "start";
    if (window.innerWidth < 940) host.style.gridTemplateColumns = "1fr";

    drawChart();
    const startPly = Number.isFinite(opts.startPly)
      ? Math.max(0, Math.min(moves.length, Math.round(opts.startPly)))
      : 0;
    renderPly(startPly, startPly ? {} : { noArrows: true });
    if (tps.length && activeTp < 0) selectTp(0);

    // 键盘左右翻步（切到别的页面后自动解绑）
    const onKey = (e) => {
      if (!document.body.contains(host)) {
        document.removeEventListener("keydown", onKey);
        return;
      }
      if (rvModalOpen || decodeDialog.open) return;
      const t = e.target;
      if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || t.tagName === "SELECT")) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); renderPly(cur - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); renderPly(cur + 1); }
    };
    document.addEventListener("keydown", onKey);
  }

  function lessonForKp(kpId) {
    const levels = state.boot.levels;
    for (const lv of levels) {
      for (const l of lv.lessons) {
        if ((l.kps || []).includes(kpId)) return l.id;
      }
    }
    return null;
  }

  // ------------------------------------------------------------------
  // 启动
  // ------------------------------------------------------------------
  window.addEventListener("hashchange", route);
  $("#brand").onclick = () => (location.hash = "#/home");

  (async function start() {
    app.innerHTML = `<div class="empty"><span class="spin" style="display:inline-block;vertical-align:-2px"></span> 正在加载题库…</div>`;
    try {
      await boot();
      if (!location.hash) location.hash = "#/home";
      await route();
    } catch (e) {
      app.innerHTML = `<div class="empty">启动失败：${e.message}<br><span class="muted">确认后端已启动（python run.py）且题库已建好。</span></div>`;
    }
  })();
})();
