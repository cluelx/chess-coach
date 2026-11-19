# 内容与数据来源清单

生成时间：2026-11-12 14:22　·　生成方式：`python scripts/build_sources_doc.py`（本文件由脚本读取源数据生成，不手工维护）

这份文档回答一个问题：**网站上每一段文字、每一个局面、每一张图，是从哪来的。**

| 内容 | 来源 | 许可 / 性质 |
|---|---|---|
| 课程讲解、知识点定义、复盘文案 | 本项目原创撰写 | 原创 |
| 练习题（约 3.5 万道） | Lichess Puzzle Database | CC0 1.0（公共领域） |
| 课程「局面演示」中的 11 道题 | 同上，逐题固定 ID | CC0 1.0 |
| 课程「局面演示」中的 9 个技术/战略局面 | 本项目构造 | 教学构造，非题库题 |
| 棋子图形 | lichess lila 仓库 cburnett 棋组 | GPLv2+（Colin M.L. Burnett） |
| 走法合法性 / 棋盘逻辑 | chess.js 0.13.4 | BSD-2-Clause |
| 复盘的评估与更优走法 | Stockfish 17.1（本地二进制） | GPLv3 |

---

## 1. 题库：Lichess Puzzle Database

| 项 | 值 |
|---|---|
| 下载地址 | https://database.lichess.org/lichess_db_puzzle.csv.zst |
| 项目主页 | https://database.lichess.org/#puzzles |
| 许可 | CC0 1.0（作者已放弃版权，可任意使用，无需署名） |
| 下载日期 | 2026-11-12 |
| 原始文件 | `data/raw/lichess_db_puzzle.csv.zst`，约 309 MB |
| 本库收录 | 34,747 道（从 619 万行中按「主题 × 难度段」抽样） |
| 处理脚本 | `scripts/fetch_puzzles.py`（流式解压，不落地中间文件） |
| 入库位置 | `data/chess_coach.db` 的 `puzzle` 与 `puzzle_theme` 表 |

### 字段映射

原始 CSV 的列原样保留，只做了拆分与索引：

| 原始列 | 库里字段 | 说明 |
|---|---|---|
| `PuzzleId` | `puzzle.id` | Lichess 原题编号，可用 `https://lichess.org/training/<id>` 打开 |
| `FEN` | `puzzle.fen` | 题面局面 |
| `Moves` | `puzzle.moves` | 空格分隔的 UCI 着法；第 1 个是**对手的引子着法**，之后交替 |
| `Rating` | `puzzle.rating` | 题目难度分，本库用它划分三个档位 |
| `Themes` | `puzzle.themes` + `puzzle_theme` 表 | 空格分隔的主题标签，拆成多行以便按主题检索 |
| `Popularity` / `NbPlays` | 同名字段 | 用于挑选「没有争议」的演示题 |

### 抽样规则（可复核）

`scripts/fetch_puzzles.py` 只保留 500–2300 分、且带战术主题标签的题，
按「主题 × 难度段」均匀取样，避免出现某个主题几千题、另一个主题几十题的情况。

### 可信度自检

对所有入库题目做过解法合法性抽检：逐题重演 `Moves`，任意一步illegal 即视为坏数据。
复核命令：

```bash
python - <<'EOF'
import sys; sys.path.insert(0, '.')
import chess
from src import db, knowledge
db.init_db()

bad = 0
for r in db.query('SELECT id, fen, moves FROM puzzle ORDER BY RANDOM() LIMIT 300'):
    b = chess.Board(r['fen'])
    for u in r['moves'].split():
        try:
            b.push_uci(u)
        except ValueError:
            bad += 1
            break

for l in knowledge.LESSONS:
    ex = l['example']
    b = chess.Board(ex['fen'])
    assert b.is_valid(), l['id']
    for m in ex['moves']:
        b.push(b.parse_san(m['san']))

print('题库抽检非法数:', bad, '· 课程局面: 全部合法')
EOF
```

---

## 2. 课程「局面演示」逐课来源

规则：**能用真实题目的一律用真题**（有唯一解、可验证、可追溯）；
战略与残局类内容没有唯一答案，改用手工构造的局面，并在页面上明说「不是题库题」。

| 课程 | 演示类型 | 题号 / 局面 | 难度 | 主题 | 原题链接 |
|---|---|---|---|---|---|
| l1-1 棋盘、棋子与记谱 | 教学构造（静态局面） | `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1` | — | k01 | 无（非题库题） |
| l1-2 将军、应将、将杀 | 题库原题 | `2OZ3G` | 787 | 阿拉伯杀、残局、将杀 | [打开](https://lichess.org/training/2OZ3G) |
| l1-3 单车杀王：唯一必须练熟的技术活 | 教学构造（含走法） | `8/8/8/4k3/8/8/8/R5K1 w - - 0 1` | — | k04 | 无（非题库题） |
| l1-4 白吃子：低分段最大的分差来源 | 题库原题 | `0I4Wr` | 786 | 底线杀、白吃子、将杀 | [打开](https://lichess.org/training/0I4Wr) |
| l1-5 击双（叉子）：一次攻击两个目标 | 题库原题 | `01czg` | 791 | 底线杀、击双、将杀 | [打开](https://lichess.org/training/01czg) |
| l1-6 牵制：被钉住的子动不了 | 题库原题 | `02J2r` | 755 | 残局、将杀、两步杀 | [打开](https://lichess.org/training/02J2r) |
| l1-7 开局三原则：别在第十步就输掉 | 教学构造（含走法） | `r1bqkb1r/pppp1ppp/2n2n2/4p1N1/2B1P3/8/PPPP1PPP/RNBQK2R b KQkq - 5 4` | — | k09 | 无（非题库题） |
| l2-1 闪击与双将：挪开一个子，身后那条线就活了 | 题库原题 | `0b1PI` | 1286 | 闪击、闪将、将杀 | [打开](https://lichess.org/training/0b1PI) |
| l2-2 消除保护：先解决守门的人 | 题库原题 | `0W9ml` | 1422 | 消除保护、将杀、两步杀 | [打开](https://lichess.org/training/0W9ml) |
| l2-3 引离与引入：把子骗到错误的位置 | 题库原题 | `0DukA` | 1310 | 引入、引离、残局 | [打开](https://lichess.org/training/0DukA) |
| l2-4 底线弱点：王前三个兵是你最大的债 | 题库原题 | `0hcSy` | 1289 | 底线杀、残局、将杀 | [打开](https://lichess.org/training/0hcSy) |
| l2-5 过渡着：为什么“白吃一个子”经常不成立 | 题库原题 | `0SjJQ` | 1285 | 残局、过渡着、将杀 | [打开](https://lichess.org/training/0SjJQ) |
| l2-6 开放线与重子入侵 | 教学构造（静态局面） | `rnbqkbnr/ppp2ppp/8/3p4/3P4/8/PP3PPP/RNBQKBNR w KQkq - 0 4` | — | k15、k16 | 无（非题库题） |
| l2-7 开局陷阱：知道对方在想什么 | 教学构造（静态局面） | `rn1qkbnr/ppp2p1p/3p2p1/4p3/2B1P1b1/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 0 5` | — | k18 | 无（非题库题） |
| l3-1 学名杀法：把形状变成直觉 | 题库原题 | `6qt4L` | 1825 | 将杀、两步杀、中局 | [打开](https://lichess.org/training/6qt4L) |
| l3-2 兵形：孤兵、叠兵、落后兵 | 教学构造（含走法） | `rnbqkb1r/pp3ppp/5n2/2pp4/3P4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 6` | — | k20 | 无（非题库题） |
| l3-3 车兵残局：菲利多尔与卢塞纳 | 教学构造（含走法） | `8/8/8/8/8/2K4k/1P6/4R3 w - - 0 1` | — | k23 | 无（非题库题） |
| l3-4 王兵残局：对王与关键格 | 教学构造（含走法） | `8/P7/8/8/8/8/8/K6k w - - 0 1` | — | k22 | 无（非题库题） |
| l3-5 双象与异色格象 | 教学构造（静态局面） | `7k/8/8/8/2B5/8/3B4/4K3 w - - 0 1` | — | k21 | 无（非题库题） |
| l3-6 计算训练：候选着法与强制着 | 题库原题 | `0Hk7S` | 1825 | 将杀、三步杀、中局 | [打开](https://lichess.org/training/0Hk7S) |

### 教学构造局面说明

这些局面是为了讲清「局面特征」而构造的，不是从任何棋书或题库里抄的，也没有唯一正解。
每一条都经过两步校验：

1. **局面合法**：双方都有王、走子方没有被将军、兵不在第一/第八横线（`chess.Board.is_valid()`）
2. **演示走法合法**：逐步执行，任意一步不合法即失败

复核命令：

```bash
python - <<'EOF'
import sys; sys.path.insert(0, '.')
import chess
from src import db, knowledge
db.init_db()

bad = 0
for r in db.query('SELECT id, fen, moves FROM puzzle ORDER BY RANDOM() LIMIT 300'):
    b = chess.Board(r['fen'])
    for u in r['moves'].split():
        try:
            b.push_uci(u)
        except ValueError:
            bad += 1
            break

for l in knowledge.LESSONS:
    ex = l['example']
    b = chess.Board(ex['fen'])
    assert b.is_valid(), l['id']
    for m in ex['moves']:
        b.push(b.parse_san(m['san']))

print('题库抽检非法数:', bad, '· 课程局面: 全部合法')
EOF
```

---

## 3. 文案

**全部讲解文字为本项目原创撰写**，包括：

- 25 个知识点的 `summary / explain / mistake` 字段
- 20 节课的 `intro / sections` 正文
- 复盘页所有判定说明与提示语
- 界面上的所有按钮与提示

写作时**没有复制任何教材、课程、网站正文**。可对照的客观事实只有两类：

1. **Lichess 的主题标签名**（`fork`、`pin`、`backRankMate` 等）。这是公开的标签体系，
   本项目的知识点按它对齐，便于题库检索。中文译名由本项目自行翻译。
2. **国际象棋的公共规则与通用术语**（如「对王」「孤兵」「菲利多尔防守」）。这些属于公共知识。

### 知识点 ↔ Lichess 主题标签 对照表

这张表说明「每节课的题是从哪些标签里取的」，可用于核对课程与题目的匹配是否合理。

| 知识点 | 名称 | 档位 | 取题标签 |
|---|---|---|---|
| k01 | 棋盘、坐标与棋子走法 | 1 | （无，纯讲解） |
| k02 | 将军、应将与将杀 | 1 | （无，纯讲解） |
| k03 | 一步杀（将杀识别） | 1 | `mateIn1` |
| k04 | 单车杀王（基本杀法） | 1 | `mateIn2`、`rookEndgame` |
| k05 | 后车/双车杀王与升变 | 1 | `mateIn2`、`queenRookEndgame`、`promotion`、`advancedPawn` |
| k06 | 击双（叉子） | 1 | `fork` |
| k07 | 牵制 | 1 | `pin` |
| k08 | 吃保护子与白吃 | 1 | `hangingPiece`、`capturingDefender` |
| k09 | 开局三原则与王的安全 | 1 | `opening`、`castling`、`shortCastling`、`longCastling` |
| k10 | 底线弱点与后门 | 2 | `backRankMate` |
| k11 | 闪击与双将 | 2 | `discoveredAttack`、`discoveredCheck` |
| k12 | 消除保护 | 2 | `capturingDefender`、`deflection` |
| k13 | 引离与引入 | 2 | `deflection`、`attraction` |
| k14 | 过渡着（中间着） | 2 | `intermezzo`、`clearance` |
| k15 | 开放线与重子入侵 | 2 | `middlegame` |
| k16 | 弱格与前哨 | 2 | （无，纯讲解） |
| k17 | 困子与边马 | 2 | `fork` |
| k18 | 开局陷阱与常见变例 | 2 | `opening` |
| k19 | 学名杀法集锦 | 3 | `smotheredMate`、`anastasiaMate`、`arabianMate`、`bodenMate`、`dovetailMate`、`hookMate`、`killBoxMate`、`doubleBishopMate`、`supportMate` |
| k20 | 兵形：孤兵、叠兵、落后兵 | 3 | `pawnEndgame` |
| k21 | 双象与异色格象 | 3 | `bishopEndgame` |
| k22 | 王兵残局：对王与关键格 | 3 | `pawnEndgame` |
| k23 | 车兵残局：菲利多尔与卢塞纳 | 3 | `rookEndgame` |
| k24 | 后兵残局与逼和陷阱 | 3 | `queenEndgame`、`perpetualCheck`、`zugzwang` |
| k25 | 计算训练：候选着法与强制着 | 3 | `oneMove`、`mateIn3`、`veryLong` |

---

## 4. 复盘里「判定」的来源

复盘有两条独立链路，各自负责能负责的部分。

### 4.1 引擎（评估曲线 + 更优走法）

| 项 | 值 |
|---|---|
| 引擎 | Stockfish 17.1（官方 release，AVX2 构建） |
| 获取方式 | https://github.com/official-stockfish/Stockfish/releases |
| 许可 | GPLv3 |
| 运行方式 | 本地进程，UCI 协议，不联网 |
| 默认深度 | 16 层（可在界面上选 12 / 16 / 20） |

**它不是语言模型**：Stockfish 是 alpha-beta 搜索 + 小型局面评估网络（NNUE，几 MB），
输出的是确定性的分数与着法，不生成任何自然语言。所有中文解释都由本项目按模板写出。

失误分级（按评估损失，单位厘兵）：

| 级别 | 阈值 |
|---|---|
| 重大失误 | ≥ 250 |
| 明显失误 | ≥ 120 |
| 不够精确 | ≥ 50 |
| 好棋 | ≤ -120 |

### 4.2 规则检测（把失误对到知识点）

这部分完全不依赖引擎，用 python-chess 的局面推理实现。每条规则都能用具体局面复核：

| 检测项 | 判定方式 | 对应知识点 |
|---|---|---|
| 错过一步杀 | 枚举我方所有合法着法，看是否有一手直接 `is_checkmate()` | k03 |
| 让对方形成一步杀 | 走完后枚举对方着法 | k02 |
| 送子 / 丢交换 | 深度 2 的强制吃子链，算「我方子力变化 − 对方可取得的收益」 | k08 |
| 漏掉免费子 | 同上，但发生在走子之前 | k08 |
| 对方可叉子 | 走完后枚举落子点的攻击目标，要求至少两个「值钱且被保护」的目标 | k06 |
| 被牵制 | 走完后重新计算被钉住的子集合，取新增 | k07 |
| 底线后门 | 王在底排、前三个兵未动、对方重子已在同一横线 | k10 |
| 开局重复动子 | 相邻两手 from_square 相同，且发生在 8 回合内 | k09 |
| 马走边线 | 马落在 a/b/g/h 列或 1/8 横线 | k17 |

注意「送子」的判定为什么要做双步核算：只看一步吃子会把 `Bxe6 fxe6` 这种正常兑子误报成丢子。
改成「我方子力变化 + 对方强制吃子链的净收益」后，实测三盘样例棋的误报清零。

**明确不判定的内容**：兵形好坏、空间优势、子力协调、计划是否合理。
这些没有可靠的程序判据，界面上也已经写明。

---

## 5. 第三方代码与图形

| 资源 | 版本 | 许可 | 来源 |
|---|---|---|---|
| chess.js | 0.13.4 | BSD-2-Clause | https://github.com/jhlywa/chess.js |
| cburnett 棋子 SVG | lila master | GPLv2+（Colin M.L. Burnett） | https://github.com/lichess-org/lila/tree/master/public/piece/cburnett |
| Stockfish | 17.1 | GPLv3 | https://github.com/official-stockfish/Stockfish |
| python-chess | ≥1.999 | GPLv3 | https://github.com/niklasf/python-chess |
| FastAPI / uvicorn | — | MIT / BSD | — |

棋子 SVG 的许可声明：`web/vendor/pieces/*.svg` 来自 lila 的 `public/piece/cburnett`，
作者 Colin M.L. Burnett，GPLv2+。本项目直接引用原文件，未做修改。

---

## 6. 怎么自己核一遍

```bash
# 1) 随便挑一道演示题，看它在库里的原始记录
python - <<'EOF'
import sys; sys.path.insert(0, '.')
from src import puzzles
print(puzzles.by_id('01czg'))
EOF

# 2) 用同一个 ID 打开 Lichess 原题，对照棋盘与解法
#    https://lichess.org/training/01czg
```

```bash
# 3) 检查课程演示局面是否合法、走法是否可执行
python - <<'EOF'
import sys; sys.path.insert(0, '.')
import chess
from src import knowledge

for l in knowledge.LESSONS:
    ex = l['example']
    b = chess.Board(ex['fen'])
    assert b.is_valid(), l['id']
    for m in ex['moves']:
        b.push(b.parse_san(m['san']))
print('ok')
EOF
```

```bash
# 4) 数据变化后重新生成这份文档
python scripts/build_sources_doc.py
```