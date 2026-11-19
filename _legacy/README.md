# 棋局教练

在 PowerShell 中运行：

```powershell
cd D:\py\chess-projects\chess-coach
python -m pip install -r requirements.txt
python app.py
```

打开 http://127.0.0.1:8765。Stockfish 默认使用 `D:\stockfish\stockfish-windows-x86-64-avx2.exe`，可用 `STOCKFISH_PATH` 覆盖。CodeBuddy CLI 使用当前登录和 `deepseek-v4.1-flash`，可用 `CHESS_COACH_MODEL` 指定其他模型 ID。调用讲解或追问时，所需的局面、问题和引擎证据会发送到该模型渠道。

导入 PGN 或 FEN 后，点击棋谱节点，选择讲解上一手或分析当前局面。可以拖动棋子建立分支，也可以点按讲解中的变化。整局扫描使用较浅搜索初筛，再复核少量候选转折点。分析结果反映有限搜索，点击转折点后可继续追问。

棋盘、棋谱和对话存储在当前浏览器。本地后端逐步验证走法和变化，按白方视角显示评分。模型文字仍可能有棋理错误，证据编号和表述筛查无法证明战略解释正确。模型调用失败时保留引擎候选和可回放变化。「取消等待」停止浏览器等待，后端调用由自身超时限制。

本次实现沿用轻量网页与 Python HTTP 服务。完整设计和后续验收项见实施方案。

## 本机验证记录

- CodeBuddy 2.181.0 与 Stockfish 18。实测单步讲解能返回模型讲解和四条引擎变化。
- 实测自由追问指定 e4，路由选中 e2e4，走法比较和模型讲解均返回。
- HTTP 冒烟检查通过首页、含分支的 PGN 导入、整局扫描及提示接口。示例棋谱的扫描能找到黑方漏防，并在复核变化中重放白方将死。
- 前端脚本通过 Node 语法检查。完整浏览器交互验收、人工讲解评审和 40–60 题对照实验仍待进行。
