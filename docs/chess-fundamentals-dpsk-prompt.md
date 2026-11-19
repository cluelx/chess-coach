# 给 dpsk 的提示词

请把 José Raúl Capablanca 的《Chess Fundamentals》整理成可查原书、可在棋盘复盘的中文学习资料。请实际读取来源并生成文件。全书按原目录处理，逐小节覆盖第一部的理论章节和第二部的示范对局，具体数量以选定版本为准。

**获取资料**

1. 用 Project Gutenberg 的 [书目页](https://www.gutenberg.org/ebooks/33870) 或 [备用书目页](https://dev.gutenberg.org/ebooks/33870) 获取带图 EPUB3 或 HTML ZIP。也可直接读取 [带图 HTML](https://www.gutenberg.org/cache/epub/33870/pg33870-images.html)。以其中一版作为正文和页码底本。若遇到 503，可让我提供下载好的 EPUB，或改用 [Wikisource 目录及各节正文](https://en.wikisource.org/wiki/Chess_Fundamentals)。记录实际使用的版本，不混用不同版本的页码。
2. 用 [社区版 LaTeX](https://github.com/lordlinks/Chess_Fundamentals/blob/main/chess_fundamentals.tex) 核对现代记谱和棋图，用 [Lichess 第一份 PGN](https://lichess.org/study/uL7pPw98.pgn) 和 [第二份 PGN](https://lichess.org/study/k3M5fqR7.pgn) 核对可回放着法。若下载链接不可用，打开对应 Study（去掉链接末尾的 .pgn），在 Share & export 中导出 Study PGN，或请我上传文件。

**整理和验证**

- 先列出底本的目录、小节、编号例图和示范对局，再按顺序逐项处理。为每节写中文讲解，保留术语、学习目标、作者给出的例子和关键变例。为每张棋图和每盘对局记录原书章节、页码（可确认时）、图号或例号、来源链接。
- 用例号、双方棋手、初始局面和关键走法匹配社区棋谱。校对描述式记谱（如 P–K4）时，结合行棋方和当时局面转换成 SAN。每个变例从正确的起始局面用 python-chess 或同等规则库逐步重放，遇到棋图时逐格对照。只有棋子摆放能确认时单独保留 piece_placement。只有行棋方、易位权等字段有来源支持时，才输出用于回放的完整 FEN。编者补充和原作者内容分别标明。
- 如出现棋图缺失、局面不符、歧义或变例走不通，将原文位置和原因记入待核对清单。无工具执行规则校验时，把棋谱标为待校验。以原书目录和图例清单验收覆盖范围，不以社区 PGN 条数代替覆盖率。

**交付**

- `01-中文导读.md`：按原书目录写，每节带页码或锚点，以及可对应的棋图和对局 ID。
- `02-棋图与例局.json`：每条含 ID、章节、标题、页码或锚点、图号或例号、棋子摆放、可确认的 FEN、中文讲解、来源和校验状态。
- `03-已校验棋谱.pgn`：每盘及每段变例标明对应 ID 和出处。
- `04-覆盖与待核对.md`：逐节列出正文、图例、主线与变例的覆盖情况、校验数量和缺项。先给第一小节做样例验证结构，随后继续生成全书。
