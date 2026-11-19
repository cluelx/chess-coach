# Chess Coach 素材搜索 Demo

在本目录执行 `.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8766`，然后打开 [本地搜索页面](http://127.0.0.1:8766/)。

在本目录使用 PowerShell：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe demo.py "初学者的马捉双，重点讲带将的捉双" --output knight-fork.html
Invoke-Item knight-fork.html
```

同名 JSON 保存来源、棋子摆放或完整 FEN、讲解和题目走法。可省略问题参数在终端输入，也可传入一条 HTTPS 链接直接处理。使用 CodeBuddy SDK 的认证，模型固定为 `deepseek-v4.1-flash`。网页的「工具调用追踪」展示 SDK 事件与本地工具耗时，每次任务还会保存 `trace.jsonl`。

已知来源可通过重复传入 `--source` 来复现预览：

```powershell
.venv/Scripts/python.exe demo.py "初学者的马捉双，重点讲带将的捉双" --source https://chesstold.com/learn/fork/ --source 'https://www.youtube.com/watch?v=r7_dazAcHsc' --output knight-fork.html
```

- 自动搜索按 B 站、其他国内视频站、海外视频站的顺序尝试单条视频，保留来源链接中的分集和时间参数。首条读取失败或没有找到棋盘时尝试第二个。追踪记录会区分访问预检、下载和识盘。复用同级 `chess-video-lab/collect.py`，未指定时间时在前 10 分钟每 6 秒粗查一帧，发现第一个候选后切换到附近 100 秒内每 0.5 秒检查棋盘变化。可在 B 站或 YouTube 链接附上 `t=秒数` 指定起点，此时扫描 180 秒。视频处理和图文深读并行。
- 从识别到的标准开局摆放出发，可以衔接出一段唯一的简短合法走法时，提供逐手回放与 PGN 下载。有遗漏时最多尝试连接两手，以推断标记未直接拍到的中间走法。剪辑、悔棋、多盘或有歧义时可能只得到短前缀。中盘起始或无法确认走法时展示候选局面、棋盘原图、画面时间和候选 JSON。采集失败或片段内没有棋盘时保留原链接。
- 视频采集依赖 Python 3.12+、PyAV、同级实验目录的 yt-dlp、Fenshot 权重和 Node.js。首版的 PGN 依据画面和合法走法生成，流程未启用音频转写。
- 图文读取公开网页中的 PGN 和 A1 Learner 的小节棋盘步骤，应用合法走法并核对可取得的逐手 FEN。通过校验的局面支持逐手回放和重置。只有 FEN 时展示静态棋盘。图片用现有 Fenshot 识别并附原图，依赖 Node.js 和同级 chess-video-lab 模型。
- Lichess 题按题目 ID 查 chess-coach 本地库。本地缺题时调用 Lichess 公开 API，仍未取得时保留原链接。马捉双主题会额外在本地筛找带将的例题，将出题前一手应用到源 FEN，然后核验并逐手回放解法。
- 每次最多深入处理 3 个非视频来源，识别 4 张候选图，输出最多 3 条棋盘素材和 2 个视频链接。SDK 搜索和深读分别限制等待时间，已取得的结果会随处理进度写入文件。公开静态网页缺少棋盘、访问失败或识图失败时，保留来源链接。
- 搜索和讲解各有 35 秒的 SDK 时限。程序并行读取候选文章并先保存可验证的棋盘，模型随后补充讲解。每个来源最多尝试识别一张图片。牵制、串击主题会补入已复核的相关文章和带分集、时间参数的 B 站样片。


