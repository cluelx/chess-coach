"""Opening courses. Every branch is replayed from the initial position."""
import chess

ECO = "https://github.com/lichess-org/chess-openings"
CAPA = "https://www.gutenberg.org/ebooks/33870"
START = chess.STARTING_FEN

def line(title, sans, note, url=ECO, fen=START):
    b = chess.Board(fen)
    moves = []
    for san in sans.split():
        mv = b.parse_san(san)
        moves.append({"san": b.san(mv), "uci": mv.uci()})
        b.push(mv)
    return {"title": title, "fen": fen, "moves": moves, "note": note,
            "source": {"url": url, "label": "Capablanca《Chess Fundamentals》例17" if url == CAPA else "Lichess ECO 开局资料"} if url else None}

FOUR = line("四马开局：出子、中心与易位", "e4 e5 Nf3 Nc6 Nc3 Nf6 Bb5 Bb4 O-O O-O d3 d6",
            "观察双方如何用中心兵和马争夺中心，再让王离开中心。易位后，d兵为象打开道路。", CAPA)
TWO = line("双马防御：波莱里奥变化", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Na5",
           "Ng5 威胁 f7，不能因为重复动马就判错。黑用 ...d5 争中心，再以 ...Na5 追击 c4 象。")
FRIED = line("双马防御：炸肝进攻", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Nxd5 Nxf7 Kxf7 Qf3+ Ke6 Nc3",
             "与 ...Na5 对照：黑马回吃后，白可以用 Nxf7 引出黑王。这是示例分支，黑方并非每步都只能这样应对。")

QGD_BOOK = line(
    "拒绝后翼弃兵：图 38 与后续",
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Nbd7 e3 Be7 Nf3 O-O Rc1 b6 cxd5 exd5 Bd3 Bb7",
    "看 2.c4 怎样挑战 d5，黑方怎样用 2…e6 支持 d5，以及 8.cxd5 exd5 如何改变中心兵形。",
)
QGD_BOOK["source"] = {
    "url": "https://www.gutenberg.org/files/5614/5614-h/5614-h.htm#:~:text=Diag.%2038",
    "label": "Edward Lasker《Chess Strategy》第 IV 章图 38",
}
PUBLISHED_OPENINGS = [
    dict(id="four", name="四马开局", summary="从卡帕布兰卡例 17 的前六回合学习出子、争中心与易位。",
         branches=[{**FOUR, "source": {**FOUR["source"], "url": CAPA + "#page25"}}], practice_tag="Four_Knights_Game"),
    dict(id="qg", name="拒绝后翼弃兵", summary="回放拉斯克图 38 的原书线路，观察双方出子与中心兵的交换。",
         branches=[QGD_BOOK], practice_tag="Queens_Gambit_Declined"),
]

DATA = [
("italian","意大利开局","白象压住 f7；慢线先组织 c3、d4，双马防御要计算黑方的中心反击。",[
    line("慢意大利","e4 e5 Nf3 Nc6 Bc4 Bc5 d3 Nf6 O-O d6 c3","白可先稳住 e4，再准备 d4；黑也要完成易位并争夺中心。"),TWO,FRIED]),
("spanish","西班牙开局","白象攻击保护 e5 的马。比较保留张力和交换后形成的兵形。",[
    line("莫菲防御","e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7","白保留象，准备 Re1 和 c3；黑用发展与中心反击抵消压力。"),
    line("兑换变化","e4 e5 Nf3 Nc6 Bb5 a6 Bxc6 dxc6","白改变黑方兵形，黑获得双象。叠兵不等于立即处于劣势。"),
    line("柏林防御","e4 e5 Nf3 Nc6 Bb5 Nf6 O-O Nxe4","黑直接挑战 e4；白可用 d4 打开中心。")]),
("four","苏格兰与四马","对比立即用 d4 打开中心与先发展两匹马。",[
    FOUR,line("苏格兰开局","e4 e5 Nf3 Nc6 d4 exd4 Nxd4","白腾开 d 线并占中心；黑可以用 ...Nf6 或 ...Bc5 攻击 d4。")]),
("petrov","俄罗斯防御","黑不先保护 e5，而是反击 e4。对称兵形中的走序仍然重要。",[
    line("古典变化","e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4","先用 ...d6 赶马，再回吃 e4。"),
    line("现代攻法","e4 e5 Nf3 Nf6 d4 exd4 e5 Ne4","白用 d4 改变中心，双方要处理前置的马和兵。")]),
("sicilian","西西里防御","黑以 c 兵挑战 d4，往往形成不对称兵形。",[
    line("开放式：纳道尔夫入口","e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6","比较黑方 ...e5 或 ...e6 的中心计划。"),
    line("阿拉平","e4 c5 c3 d5 exd5 Qxd5 d4","白准备构建兵中心；黑可以及时用 ...d5 反击。"),
    line("罗斯索利莫","e4 c5 Nf3 Nc6 Bb5 g6","白决定是否兑换 c6 马；黑准备象走 g7。")]),
("french","法兰西防御","白可维持兵链，黑常攻链底 d4；比较不同中心结构。",[
    line("推进变化","e4 e6 d4 d5 e5 c5 c3 Nc6","白维持空间，黑增加对 d4 的压力。"),
    line("交换变化","e4 e6 d4 d5 exd5 exd5","中心趋于对称，发展和开放线使用更重要。"),
    line("温纳维尔","e4 e6 d4 d5 Nc3 Bb4 e5 c5","黑牵制 c3 马并挑战 d4。")]),
("caro","卡罗康防御","用 ...c6 支持 ...d5，并为白格象保留先出动的机会。",[
    line("古典变化","e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5","黑先出象再考虑 ...e6。"),
    line("推进变化","e4 c6 d4 d5 e5 Bf5 Nf3 e6","白有空间，黑出象后准备挑战兵链。"),
    line("潘诺夫攻法","e4 c6 d4 d5 exd5 cxd5 c4 Nf6 Nc3","中心交换可能形成孤后兵，比较活跃子力和长期弱点。")]),
("scandi","斯堪的纳维亚防御","立刻用 ...d5 换掉 e4 兵。两种回收中心兵的次序各有代价。",[
    line("后回吃","e4 d5 exd5 Qxd5 Nc3 Qa5","黑后早出会被马追，之后要尽快完成发展。"),
    line("现代变化","e4 d5 exd5 Nf6 d4 Nxd5","黑先出马再取兵；白也可以选择保住 d5 兵。")]),
("qg","后翼弃兵","白用 c 兵挑战 d5，黑可吃、守或采用斯拉夫结构。",[
    line("接受后翼弃兵","d4 d5 c4 dxc4 Nf3 Nf6 e3","白发展并准备收回 c4 兵；黑争取及时反击中心。"),
    line("拒绝后翼弃兵","d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7","黑稳住 d5 并解牵制，白保持中心张力。"),
    line("斯拉夫防御","d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4","...c6 支持 d5，也保留白格象的发展空间。")]),
("london","伦敦体系","白发展 Bf4 后搭建兵形，但要对黑方具体反击作反应。",[
    line("传统阵型","d4 d5 Nf3 Nf6 Bf4 e6 e3 c5 c3","观察白方如何守 d4，以及黑方何时可以用 ...Qb6 压迫 b2。"),
    line("黑早走 ...c5、...Qb6","d4 d5 Bf4 c5 e3 Nc6 Nf3 Qb6","停下来数 b2 和 d4 的攻防，不要机械照搬出子顺序。"),
    line("Jobava 体系","d4 Nf6 Nc3 d5 Bf4","早出 Nc3 改变中心计划，不能套用传统伦敦的 c3 兵形。")]),
("indian","印度防御","黑先发展，再选择直接限制白方中心或允许其扩张后反击。",[
    line("尼姆佐印度","d4 Nf6 c4 e6 Nc3 Bb4","黑牵制 c3 马，阻碍白轻易走 e4。"),
    line("王翼印度","d4 Nf6 c4 g6 Nc3 Bg7 e4 d6","白占中心，黑准备 ...e5 或 ...c5。"),
    line("格林菲尔德","d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5","黑邀请白建立中心，再用象和 ...c5 攻击。")]),
("english","英国式与列蒂","先从侧翼争中心，同一局面可能由不同走序到达。",[
    line("对称英国式","c4 c5 Nc3 Nc6 Nf3 Nf6","留意哪一方先用 d 兵打破对称。"),
    line("逆西西里","c4 e5 Nc3 Nf6 g3","白多一个先手，但仍需处理黑方 ...d5。"),
    line("列蒂入口","Nf3 d5 c4 e6","白下一步可选择是否走 d4，转入后翼弃兵结构。")]),
]
OPENINGS = [dict(id=slug, name=name, summary=summary, branches=branches) for slug,name,summary,branches in DATA]

def revise_lessons(lessons):
    by = {l["id"]:l for l in lessons}
    for lid, ex, intro in [
        ("l1-7",FOUR,"通过四马开局观察占中心、发展和王安全。原则帮助找候选着，具体威胁可以改变优先级。"),
        ("l2-7",TWO,"比较双马防御的两条分支：先算对手的强制着，再判断吃子是否合适。"),
        ("l3-2",line("潘诺夫兵形：白方孤后兵","e4 c6 d4 d5 exd5 cxd5 c4 Nf6 Nc3 Nc6 cxd5 Nxd5",
                    "白 d4 兵的 c、e 邻列没有白兵。它控制 c5、e5，却不能由相邻白兵保护。"),
                    "兵形能通过交换改变。比较孤兵带来的空间、活跃性和长期防守负担。"),
        ("l3-3",line("卢塞纳：架桥练习","Rf4 Ra1 Kc7 Rc1+ Kb6 Rb1+ Kc6 Rc1+ Kb5 Rb1+ Rb4",
                    "白车到第四排，白王逐步走出后可用车遮挡横向将军。以下是演示应对，不是唯一防守。",
                    None,"1K6/1P2k3/8/8/8/8/r7/5R2 w - - 0 1"),
                    "两种典型车兵对车局面：菲利多尔用第六排阻挡王，卢塞纳用架桥掩护升变。"),
        ("l3-4",line("对王：黑先走","Kd7 Kf6","两个王隔一格对峙。黑王向 d7 让开，白王从 f6 进入关键格。",
                    None,"8/4k3/8/4K3/4P3/8/8/8 b - - 0 1"),
                    "比较同一棋形中谁先走；关键格取决于兵的列和进度。"),
    ]:
        by[lid].update(example=ex,intro=intro)
    by["l2-7"]["example"] = {**TWO, "branches":[TWO,FRIED]}
    philidor = line("菲利多尔：第三排防守","Ra6 e6 Ra1",
                    "黑车先在黑方第三排挡住白王；白兵推进后，黑车转向白王后方，准备连续将军。",
                    None,"4k3/8/8/4PK2/8/8/r7/7R b - - 0 1")
    lucena = by["l3-3"]["example"]
    by["l3-3"]["example"] = {**lucena, "branches":[lucena,philidor]}
    king = by["l3-4"]["example"]
    other = line("对王：同一局面白先","Kd5 Kd7","白先无法直接走到 d6、e6 或 f6；黑跟随保持对王。",
                 None,"8/4k3/8/4K3/4P3/8/8/8 w - - 0 1")
    by["l3-4"]["example"] = {**king, "branches":[king,other]}
    sections = {
       "l1-7":[("三原则","用兵争中心、发展马象、保障王安全。遇到具体威胁时先计算。")],
       "l2-7":[("先看对方的最强应对","在变化树切换 5...Na5 和 5...Nxd5，比较 f7、黑王和白象。")],
       "l3-2":[("什么是孤兵","相邻两列没有己方兵。孤兵既可以控制格子，也可能成为攻击目标。")],
       "l3-3":[("菲利多尔","防守王挡住兵，防守车沿第六排限制进攻王。兵前进后，再转到后方将军。"),("卢塞纳","进攻王暂时挡在己兵前，进攻车可到第四排准备挡将。")],
       "l3-4":[("对王","两王隔一格正对时，轮到走的一方不能踏进对方王的控制格。把它用来争取关键格。")],
    }
    for lid, pairs in sections.items():
        by[lid]["sections"] = [dict(h=h,p=p) for h,p in pairs]



def identify(moves):
    """Recognize only openings with a matching recorded move order."""
    if not moves or moves[0]["fen"] != START:
        return None
    played = [m["uci"] for m in moves]
    scores = []
    for opening in OPENINGS:
        count = 0
        for ex in opening["branches"]:
            same = 0
            for actual, expected in zip(played, ex["moves"]):
                if actual != expected["uci"]:
                    break
                same += 1
            count = max(count, same)
        if count >= 4:
            scores.append((count, opening["name"]))
    scores.sort(reverse=True)
    if not scores or (len(scores) > 1 and scores[0][0] == scores[1][0]):
        return None
    return scores[0][1]
