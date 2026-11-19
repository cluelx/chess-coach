"""Content-grounded lesson planning and durable learning state."""
import json
import os
import re
import time
import urllib.request
import subprocess
from . import codebuddy, db, knowledge, openings

def init():
    with db.db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS coach_state(
          learner_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lesson_read(
          learner_id TEXT, lesson_id TEXT, finished_at REAL,
          PRIMARY KEY(learner_id, lesson_id));
        """)

def load(lid):
    row = db.one("SELECT payload FROM coach_state WHERE learner_id=?", (lid,))
    reads = db.query("SELECT lesson_id FROM lesson_read WHERE learner_id=?", (lid,))
    state = json.loads(row["payload"]) if row else {}
    state["read_lessons"] = [r["lesson_id"] for r in reads]
    state["progress"] = db.kp_progress(lid)
    recent = db.recent_reviews(lid, 10)
    counts = {}
    opening_counts = {}
    for game in recent:
        item = game["payload"]
        if item.get("opening") and item.get("player"):
            key = (item["opening"], item["player"])
            opening_counts[key] = opening_counts.get(key,0)+1
        for kp in set(item.get("verified_topics", [])):
            counts[kp] = counts.get(kp, 0) + 1
    state["review_observations"] = [
        {"topic": knowledge.KP_BY_ID[k]["name"], "games": n, "sample": len(recent)}
        for k,n in counts.items() if n >= 2 and k in knowledge.KP_BY_ID]
    state["opening_observations"] = [
        {"opening":name,"side":side,"games":count} for (name,side),count in opening_counts.items() if count >= 2
    ]
    return state

def provider():
    if os.environ.get("CHESS_COACH_API_KEY"):
        return "api"
    return "codebuddy" if codebuddy.command() else "local"


def available():
    return provider() != "local"

def catalog():
    if not knowledge.TUTORIALS_PUBLISHED:
        return []
    return [
        {"id":l["id"],"title":l["title"],"href":"#/lesson/"+l["id"],"level":l["level"],
         "topic":"开局" if set(l["kps"]) & {"k09","k18"} else "残局" if set(l["kps"]) & {"k04","k05","k21","k22","k23","k24"} else "战术与基础",
         "kps":l["kps"]} for l in knowledge.PUBLISHED_LESSONS
    ] + [
        {"id":o["id"],"title":o["name"],"href":"#/openings/"+o["id"],"level":2,"topic":"开局","kps":["k09","k18"]}
        for o in openings.OPENINGS
    ]

def model_request(message, state, options):
    base = os.environ.get("CHESS_COACH_API_BASE", "https://api.deepseek.com").rstrip("/")
    body = {"model":os.environ.get("CHESS_COACH_MODEL","deepseek-flash"),"response_format":{"type":"json_object"},
            "max_tokens":650,"messages":[
      {"role":"system","content":"你是国际象棋课程规划员。只选给定目录中的 ID。返回 JSON：ids（按先修与需求排序的课程ID列表），mode（single或plan），weeks（1到12，0表示沿用），minutes（5到120，0表示沿用），reply（解释选择的原因，不编造走法、历史、掌握度或课程）。"},
      {"role":"user","content":json.dumps({"request":message,"goals":state.get("goals",{}),
        "completed":state["read_lessons"],"review":state["review_observations"],"openings":state["opening_observations"],
        "practice":{k:{"seen":v["seen"],"accuracy":v["accuracy"]} for k,v in state["progress"].items()},
        "recent_dialogue":state.get("conversation",[])[-4:],"catalog":options},ensure_ascii=False)}
    ]}
    if provider() == "codebuddy":
        parsed=codebuddy.request(body["messages"])
    else:
        req=urllib.request.Request(base+"/chat/completions",json.dumps(body).encode(),
          {"Authorization":"Bearer "+os.environ["CHESS_COACH_API_KEY"],"Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=15) as resp:
            output=json.loads(resp.read(1_000_000))["choices"][0]["message"]["content"]
        parsed=json.loads(output)
    if not isinstance(parsed,dict) or not isinstance(parsed.get("ids"),list):
        raise ValueError("invalid model response")
    return parsed

def request(lid, message):
    state = load(lid)
    goals = dict(state.get("goals",{}))
    message = message.strip()
    context = (goals.get("request","") + " " + message)[-900:]
    if re.search(r"只想|只学|只练|今天|今晚|本次",message):
        context = message
    days = re.search(r"(\d+)\s*(?:天|日)\s*(?:的)?(?:计划|安排|课程)",message)
    weeks = re.search(r"([0-9一二两三四五六七八九十]+)\s*(?:周|星期)",message)
    minutes = re.search(r"(\d+)\s*分钟",message)
    rating = re.search(r"(?<!\d)([5-9]\d\d|[12]\d{3})(?!\d)",message)
    level = db.ensure_learner(lid)["level"]
    if rating:
        goals["rating_note"] = message[:300]
    if re.search(r"刚学|零基础|初学|新手",context):
        level = 1
    elif re.search(r"有基础|进阶",context):
        level = 2
    elif re.search(r"高手|高级",context):
        level = 3
    duration = int(goals.get("weeks", 0))
    mode = "plan" if weeks or days else "single" if re.search(r"今天|今晚|本次|单次",message) else "plan" if "计划" in message or duration else "single"
    if weeks:
        raw=weeks[1]
        duration=int(raw) if raw.isdigit() else dict(zip("一二两三四五六七八九十",[1,2,2,3,4,5,6,7,8,9,10])).get(raw,4)
    elif days:
        duration=max(1,(int(days[1])+6)//7)
    duration=max(1,min(12,duration or 4))
    budget=max(5,min(120,int(minutes[1]) if minutes else goals.get("minutes",20)))
    if not re.search(r"今天|今晚|本次|单次",message):
        goals.update(request=context, minutes=budget)
    options=catalog()
    lookup={o["id"]:o for o in options}
    named_kps={k["id"] for k in knowledge.KPS if k["name"] in context}
    names=[o for o in options if named_kps.intersection(o["kps"]) or o["title"] in context or (o["id"] in {"italian","spanish","london","french","sicilian","caro"} and o["title"][:2] in context)]
    topics=[t for t in ("开局","残局","战术") if t in context]
    if re.search(r"开局和残局|残局和开局", context):
        topics=["开局","残局"]
    related=[o for o in options if any(t in o["topic"] for t in topics)] if topics else options
    def rank(o):
        kps=o["kps"]
        weakest=min((state["progress"].get(k,{}).get("mastery",0) for k in kps),default=0)
        return (o["id"] in state["read_lessons"],abs(level-o["level"]),weakest)
    related.sort(key=rank)
    if len(topics)>1:
        groups=[[o for o in related if t in o["topic"]] for t in topics]
        related=[g[i] for i in range(max(map(len,groups))) for g in groups if i<len(g)]
    ids=list(dict.fromkeys(o["id"] for o in names+related))
    source="local"
    provider_status=None
    reply="根据目标、通用档位和练习记录，从现有内容中安排课程。"
    if available():
        try:
            result=model_request(message,{**state,"goals":goals},options)
            chosen=list(dict.fromkeys(i for i in result["ids"] if isinstance(i,str) and i in lookup))
            if not chosen:
                raise ValueError("empty catalog selection")
            ids=chosen
            if not (weeks or days or re.search(r"今天|今晚|本次|单次|长期|计划",message)) and result.get("mode") in ("single","plan"):
                mode=result["mode"]
            if not (weeks or days) and isinstance(result.get("weeks"),int) and 1<=result["weeks"]<=12:
                duration=result["weeks"]
            if not minutes and isinstance(result.get("minutes"),int) and 5<=result["minutes"]<=120:
                budget=result["minutes"]
            if isinstance(result.get("reply"),str):
                reply=result["reply"][:600]
            source="ai"
        except codebuddy.LoginRequired:
            source="fallback"
            provider_status="login_required"
        except (OSError,ValueError,KeyError,IndexError,TypeError,subprocess.TimeoutExpired):
            source="fallback"
    if not re.search(r"今天|今晚|本次|单次",message):
        goals["minutes"]=budget
    prior=state.get("long_plan")
    days_count=max(1,min(84,int(days[1]))) if days else duration*7
    revising=prior and re.search(r"调整|改成|换成|每天|只剩|本周",message) and not re.search(r"重新|新计划",message)
    old_done=[x for x in prior["tasks"] if x.get("done")] if mode=="plan" and revising else []
    prior_days={x["day"] for x in old_done}
    tasks=list(old_done)
    for day in range(1,(days_count if mode=="plan" else 1)+1):
        if day in prior_days:
            continue
        for idx in range(1 if mode=="plan" else min(2,len(ids))):
            slot=((day-1)-(day-1)//7+idx) if mode=="plan" else idx
            content=lookup[ids[slot % len(ids)]]
            tasks.append({**content,"day":day,"task_id":f"{day}-{idx}","done":False,
                          "activity": "回顾并做一道未见过的相关题" if day%7==0 else "读讲解、走一遍棋盘，并复述关键条件",
                          "minutes":budget if mode=="plan" else budget//min(2,len(ids))})
    tasks.sort(key=lambda x:x["day"])
    plan={"mode":mode,"tasks":tasks,"reply":reply,"source":source,"provider_status":provider_status}
    log=(state.get("conversation",[])+[{"request":message,"reply":reply}])[-12:]
    saved={"goals":goals,"plan":plan,"conversation":log,
           "long_plan":plan if mode=="plan" else prior,
           "versions":(state.get("versions",[])+([state["plan"]] if state.get("plan") else []))[-5:]}
    if mode=="plan":
        goals["weeks"]=duration
    store(lid,saved)
    return load(lid)

def store(lid,state):
    data={k:v for k,v in state.items() if k not in {"read_lessons","progress","review_observations","opening_observations"}}
    db.execute("INSERT INTO coach_state(learner_id,payload) VALUES(?,?) ON CONFLICT(learner_id) DO UPDATE SET payload=excluded.payload",(lid,json.dumps(data,ensure_ascii=False)))

def complete(lid,task_id,done):
    state=load(lid)
    plan=state.get("plan")
    if not plan:
        raise ValueError("没有计划")
    task=next((x for x in plan["tasks"] if x["task_id"]==task_id),None)
    if not task:
        raise ValueError("任务不存在")
    task["done"]=done
    if plan["mode"]=="plan":
        state["long_plan"]=plan
    store(lid,state)
    return load(lid)


def resume(lid):
    state = load(lid)
    plan = state.get("long_plan")
    if not plan:
        raise ValueError("没有保留的长期计划")
    if state.get("plan") and state["plan"]["mode"] == "single":
        state["versions"] = (state.get("versions",[]) + [state["plan"]])[-5:]
    state["plan"] = plan
    store(lid,state)
    return load(lid)
