"""Local browser interface for the CodeBuddy materials demo."""
import asyncio
from datetime import datetime
import json
import re
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from demo import MODEL, ROOT, run

app = FastAPI()
jobs = {}
active = None


class Search(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.get("/")
def home():
    return FileResponse(ROOT / "index.html")


@app.get("/example")
def example():
    return FileResponse(ROOT / "knight-fork.html")


async def collect(job, question):
    def trace(event):
        row = {"time": datetime.now().isoformat(timespec="seconds"), **event}
        with job["output"].with_name("trace.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        job["trace"].append(row)

    try:
        trace({"event": "job_start", "model": MODEL})
        await run(question, job["output"], trace=trace)
        job["status"] = "done"
    except Exception as exc:
        job.update(status="error", error=str(exc) or type(exc).__name__)


@app.post("/api/jobs", status_code=202)
async def start(body: Search):
    global active
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "请输入主题或链接。")
    if active and not active.done():
        raise HTTPException(409, "上一条任务还在运行。")
    key = uuid4().hex
    folder = ROOT / "web-runs" / key
    folder.mkdir(parents=True)
    job = {"status": "running", "output": folder / "materials.html", "trace": []}
    jobs[key] = job
    active = asyncio.create_task(collect(job, question))
    return {"id": key}


@app.get("/api/jobs/{key}")
def status(key: str):
    job = jobs.get(key)
    if not job:
        raise HTTPException(404)
    output = job["output"]
    return {"status": job["status"], "error": job.get("error"), "trace": job["trace"],
            "revision": str(output.stat().st_mtime_ns) if output.exists() else None}


@app.get("/results/{key}/{name}")
def result(key: str, name: str):
    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
        raise HTTPException(404)
    if name not in ("materials.html", "materials.json", "trace.jsonl"):
        raise HTTPException(404)
    path = ROOT / "web-runs" / key / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/results/{key}/{folder}/{name:path}")
def video_artifact(key: str, folder: str, name: str):
    if (not re.fullmatch(r"[a-f0-9]{32}", key)
            or not re.fullmatch(r"materials-video-[a-f0-9]{12}", folder)
            or not re.fullmatch(r"(?:candidates\.json|clip\.pgn|frames/frame-\d+\.jpg|frames/frame-\d+-\d+\.png)", name)):
        raise HTTPException(404)
    path = ROOT / "web-runs" / key / folder / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename="clip.pgn" if name == "clip.pgn" else None)
