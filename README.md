# 棋课 · chess-coach

一个本地跑的国际象棋教程与复盘网站。前后端 + 本地引擎；默认离线，可配置 AI 教练。

- 三档水平（入门 / 进阶 / 高级），每档六到七节课，题目难度跟着档位走
- 课程讲解原创撰写；**演示局面全部来自题库真实题目**（逐题标注题号，可点回 Lichess 核对），
  战略类内容用手工构造局面并明确标注
- 题库来自 Lichess Puzzle Database（CC0），按主题和难度筛选入库 3.4 万题
- 每课的验收题是**固定**的同一批，隔几天回来重做才可比
- 下载安装后打开即用。练习记录、学习计划、完整复盘和上次停留的棋步保存在本机 SQLite。
- 导入 PGN 后**逐步回放**：棋盘可点、评估曲线、转折点标出「你走的」与「引擎认为更好的」两条箭头，
  同时把失误映射到知识点并给出对应练习题

## 跑起来

```bash
cd D:/py/chess-projects/chess-coach
python -m pip install -r requirements.txt
python scripts/fetch_puzzles.py   # 第一次：下载 + 建题库（约 5 分钟）
python run.py                     # http://127.0.0.1:8765
```

`data/chess_coach.db` 保存题库和个人数据。已有题库时直接运行 `python run.py`。复盘页的「本地复盘」可以打开多盘已保存的棋局。原浏览器还有旧版缓存时，可以用「载入旧版缓存棋谱」填入 PGN，再点「开始复盘」入库。旧数据库里只有摘要的复盘需要原 PGN 才能重新回放。

### 学习助手

从首页进入「学习助手」，描述学情或知识点，也可从复盘转折点点击「围绕这步学习」。对话会给出建议，优先选取现有收藏、教程与开局课，再按需搜索。

- **CodeBuddy CLI**：在「设置」选 CodeBuddy，沿用本机 CLI 登录状态。默认模型 `deepseek-v4.1-flash`、推理档位 `high`，模型 ID 必须在该账号的 CLI 支持列表内。分别点击「保存并测试模型」「保存并测试搜索」；测试模型会回显实际使用的模型名。
- **自定义 API**：填写支持 Chat Completions 的服务地址、模型名和密钥。联网搜索另填 Brave Search 密钥。配置保存在本机 SQLite，设置接口不回传密钥。

一次学习请求就是一次完整的 CodeBuddy Agent 运行：同一轮里它可以先用 `search_local_materials` 查站内资料，缺什么再用 `WebSearch`/`WebFetch` 找网络来源，读到棋谱就调用 `parse_pgn_or_fen`，需要判断局面就调用 `analyse_position`（Stockfish），最后据此给建议。工具只开放网页和棋课自带的这四项 MCP 能力，默认最多 10 轮、120 秒（实测一次「查资料+解析棋谱+引擎核验」约 80 秒）；页面显示当前是在搜索、读取还是分析，可随时点「停止」。模型返回的资料 ID、来源链接和棋谱都会在本地再核验一遍，再交给棋盘回放。

对话支持直接粘贴来源链接、PGN、完整 FEN，或附上棋盘图、PGN、FEN 文件。识图使用同级 `chess-video-lab` 中的 Fenshot，图片结果仅表示棋子摆放。Lichess 对局链接可尝试导出棋谱，CodeBuddy 模式可通过网页读取整理其他来源。复盘讲解 Beta 复用 Stockfish 和 BinProp。收藏与主动保存的文案保存在当前浏览器。

### 旧档案与备份

停止服务后在项目根目录运行下面的命令。用 `list` 找到旧账号或游客档案的 ID，再用 `adopt` 将它选为个人版档案。现有记录留在原档案下，切换前会自动备份。要切回默认档案，执行 `adopt local`。

```powershell
python scripts/local_data.py list
python scripts/local_data.py adopt 旧档案ID
python scripts/local_data.py backup data/my-backup.db
python scripts/local_data.py restore data/my-backup.db
```

### 关于引擎

复盘的评估与「更优走法」由本地 **Stockfish 17.1** 提供，放在 `engine/stockfish/`。
它是传统的 alpha-beta 搜索引擎（不是语言模型），离线运行。

没放引擎仍可浏览课程和回放棋谱；评估、引擎应手与转折点需要引擎。
引擎二进制不入库（77 MB），需要的话从
https://github.com/official-stockfish/Stockfish/releases 下载
`stockfish-windows-x86-64-avx2.zip`，解压到 `engine/`。

## 目录

```
src/knowledge.py    知识点（25 个）+ 课程（20 节）的全部文案
src/demos.py        把题库里的真实题目组装成课程演示
src/motifs.py       确定性战术检测器（python-chess，无引擎、无模型）
src/engine.py       Stockfish 封装（可缺省）
src/review.py       PGN → 评估曲线 → 转折点 → 知识点
scripts/local_data.py  选用旧档案、备份和恢复 SQLite
src/puzzles.py      题库检索与固定/随机抽样
src/app.py          FastAPI 接口
web/                前端（原生 JS + 自制棋盘 + chess.js 走法校验）
scripts/            建库、选题、生成来源文档
docs/SOURCES.md     文案与棋谱的来源审查清单（由脚本生成）
```

## 复盘怎么判定

两条独立链路：

| 链路 | 负责 | 依据 |
| --- | --- | --- |
| 引擎 | 每步评估、整盘曲线、更优走法 | Stockfish 17.1，本地，默认 16 层 |
| 棋规核验 | 把有直接证据的失误对到知识点 | 漏掉一步杀、允许对手一步杀、经核验的直接得子 |

复盘结果默认显示经棋规核验的战术解释，其他转折点显示评价变化与更优走法。

选中有替代着法的转折点后，点击「为什么推荐这步」，可以按需比较推荐着和实战着的后续局面。
Stockfish 为两手棋各取最多 4 条变化，BinProp 的 Claude Opus 5 函数库从中找出可区分的棋理。
界面显示棋理在两组变化中的出现次数和双方变化示例。这些结果是对所采样局面的描述。
功能在本地运行，依赖现有的 Stockfish 和 python-chess。

[BinProp](https://github.com/oripress/BinProp/tree/6c3e1a709dae51adef00b4abd17a1cc2ce90b7ed) 的国际象棋函数库及所用运行代码位于
`vendor/binprop/`，使用 MIT 许可。

## 数据与版权

| 内容 | 来源 | 许可 |
| --- | --- | --- |
| 题库 | Lichess Puzzle Database | CC0 1.0 |
| 课程文案 | 本项目原创 | — |
| 棋子图形（cburnett） | lichess-org/lila | GPLv2+ |
| chess.js | jhlywa/chess.js | BSD-2-Clause |
| Stockfish | official-stockfish | GPLv3 |

完整的逐课题目编号、每条规则、每处引用的核对方法：见 [`docs/SOURCES.md`](docs/SOURCES.md)。

## 教学教练与变化分析

- **AI 推荐**：输入学习主题、水平、时长和周期，生成一次学习或逐日计划；可修改计划、标记完成、继续之前的长期计划。
- **通用三档**：保留原课程，并可标记已读。
- **全部内容**：浏览知识点、经典开局及变化，或按主题、难度、开局标签、练习状态分页浏览本地题库。
- **复盘**：在棋盘直接试走，用“引擎应手”走一手，用“返回主线”回到分叉位置。只有经核验的战术才显示知识点；短将杀相似题需匹配布局、应手序列与王区攻防，并通过有上限的合法防守枚举。找不到时不凑数。

未设置密钥时会尝试使用本机 CodeBuddy CLI（需要在 CLI 中完成登录）；不可用时使用本地规则。课程、题库与复盘无需联网。需要启用模型时，在启动前配置 PowerShell 环境变量（密钥只放在后端环境）：

```powershell
$env:CHESS_COACH_API_KEY = '<你的 DeepSeek API Key>'
$env:CHESS_COACH_MODEL = 'deepseek-flash'
python run.py
```

也可设置 `CHESS_COACH_API_BASE` 使用兼容 Chat Completions 的服务。模型仅接收课程目录及推荐所需的近期对话与学习摘要，返回课程 ID；后端过滤无效 ID。模型调用失败时会回到本地规则。当前保守战术解释覆盖漏一步杀、允许对手一步杀与少数直接得子；相似题覆盖有合法且可验证变化的一到三步杀，覆盖率与精确率尚未做人工标注评估。

### 使用 WorkBuddy / CodeBuddy 的 DeepSeek

参照旧 demo，默认调用已登录的 CodeBuddy CLI，模型 ID 为 `deepseek-v4.1-flash`，推理档位默认 `high`（`codebuddy --help` 里 `--model` 与 `--effort` 会列出当前账号可用的模型与档位；`dpsk-flash` 这类简称本机不可用）。可用 `CHESS_COACH_CODEBUDDY_BIN` 指定 CLI，或用 `CHESS_COACH_WORKBUDDY_CLI` 指定 WorkBuddy 自带的 JS 入口。桌面端登录不一定等于 CLI 登录；如返回 Authentication required，启动 CodeBuddy CLI 后执行 `/login`。如模型 ID 不可用，设置 `CHESS_COACH_MODEL` 为 CLI 中可用的 DeepSeek ID。
