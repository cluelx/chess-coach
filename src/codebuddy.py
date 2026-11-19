"""CodeBuddy CLI 调用层。

两种用法：
- request(): 一次问答，等最终 JSON；
- stream(): 非交互 Agent 运行，逐条产出 CLI 事件（工具调用、结果），供上层显示进度。
工具范围由调用方指定：内置 WebSearch/WebFetch + 棋课自己的 MCP 工具。
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL = "deepseek-v4.1-flash"
DEFAULT_EFFORT = "high"
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
MCP_SERVER = "chess-coach"
MCP_TOOLS = ("search_local_materials", "parse_pgn_or_fen", "recognize_board_image", "analyse_position")
AGENT_TOOLS = ("WebSearch", "WebFetch", "ToolSearch", "DeferExecuteTool")
AGENT_TURNS = 10
AGENT_TIMEOUT = 120

_lock = threading.Lock()


class AgentError(ValueError):
    """带阶段和诊断信息的 Agent 失败，供接口层原样呈现。"""

    def __init__(self, message, *, code="agent_error", stage="agent",
                 retryable=True, detail=None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.detail = str(detail or "")[-1600:]


class LoginRequired(AgentError):
    def __init__(self, message="请先在 CodeBuddy CLI 登录", *, detail=None):
        super().__init__(message, code="login_required", stage="auth",
                         retryable=False, detail=detail)


def _tail(value, limit=1200):
    if isinstance(value, bytes):
        value = value.decode("utf8", "replace")
    return str(value or "").strip()[-limit:]


def command():
    explicit = os.environ.get("CHESS_COACH_CODEBUDDY_BIN")
    exe = explicit or shutil.which("codebuddy.cmd" if os.name == "nt" else "codebuddy")
    if exe:
        return [exe]
    cli = os.environ.get("CHESS_COACH_WORKBUDDY_CLI")
    if not cli and os.name == "nt":
        cli = r"D:\workbuddy\resources\app.asar.unpacked\cli\dist\codebuddy-lite-wb.mjs"
    node = shutil.which("node")
    return [node,cli] if cli and node and Path(cli).is_file() else None


def mcp_tool_names():
    return tuple(f"mcp__{MCP_SERVER}__{name}" for name in MCP_TOOLS)


def mcp_config():
    """棋课专用 MCP：同目录下用当前 Python 解释器拉起本地工具服务。"""
    env = {"PYTHONPATH": ROOT, "PYTHONIOENCODING": "utf-8"}
    if os.environ.get("CHESS_COACH_MCP_LOG"):
        env["CHESS_COACH_MCP_LOG"] = os.environ["CHESS_COACH_MCP_LOG"]
    return json.dumps({"mcpServers": {MCP_SERVER: {
        "command": sys.executable,
        "args": ["-B", "-m", "src.mcp_server"],
        "env": env,
    }}}, ensure_ascii=True)


def _prompt(messages):
    return messages[0]["content"] + "\n以下是本次任务的数据：\n" + messages[1]["content"]


def _env():
    return {key: value for key, value in os.environ.items()
            if key not in {"CHESS_COACH_API_KEY", "CHESS_COACH_BRAVE_KEY"}}


def _check(model, effort):
    model = model or os.environ.get("CHESS_COACH_MODEL", DEFAULT_MODEL)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", model):
        raise AgentError("无效的 CodeBuddy 模型 ID", code="invalid_model",
                         stage="config", retryable=False)
    if effort and effort not in EFFORTS:
        raise AgentError("无效的推理档位", code="invalid_effort",
                         stage="config", retryable=False)
    return model


def _tool_flags(tools, mcp, max_turns):
    names = list(tools or ())
    flags = [] if tools is None else ["--tools=" + ",".join(names)]
    allowed = list(names)
    if mcp:
        # MCP 工具是延迟加载的，必须经 ToolSearch + DeferExecuteTool 调用
        allowed += [f"DeferExecuteTool(mcp__{MCP_SERVER}__*)"]
        flags += ["--mcp-config", mcp_config(), "--strict-mcp-config"]
    if allowed:
        flags += ["--allowedTools", *allowed, "--max-turns", str(max_turns)]
    return flags


def _flags(model, effort, tools, mcp, max_turns, output):
    args = ["-p", "--model", model, "--output-format", output]
    if effort:
        args += ["--effort", effort]
    return [*command(), *args, *_tool_flags(tools, mcp, max_turns),
            "--permission-mode", "dontAsk", "--setting-sources", "user", "--no-session-persistence"]


def _decode(value):
    if isinstance(value, str):
        text = re.sub(r"^\s*```(?:json)?\s*", "", value, flags=re.I).lstrip()
        try:
            # Some CLI models append source citations after the JSON object.
            value, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            start = text.find("{")
            if start < 0:
                raise AgentError("CodeBuddy 返回的内容不是 JSON", code="invalid_json",
                                 stage="decode", detail=_tail(text)) from None
            try:
                value, _ = json.JSONDecoder().raw_decode(text[start:])
            except ValueError:
                raise AgentError("CodeBuddy 返回的内容不是 JSON", code="invalid_json",
                                 stage="decode", detail=_tail(text)) from None
    if not isinstance(value, dict):
        raise AgentError("CodeBuddy 未返回 JSON 对象", code="not_an_object",
                         stage="decode", detail=_tail(value))
    return value


def _envelopes(stdout):
    envelope = json.loads(stdout)
    return envelope if isinstance(envelope, list) else [envelope]


def _find_model(value):
    if isinstance(value, dict):
        for key in ("model", "requestModelId"):
            item = value.get(key)
            if isinstance(item, str) and item:
                return item
        for item in value.values():
            found = _find_model(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_model(item)
            if found:
                return found
    return None


def _actual_model(envelope):
    events = envelope if isinstance(envelope, list) else [envelope]
    for event in reversed(events):
        found = _find_model(event)
        if found:
            return found
    return None


def request(messages, *, model=None, effort=None, tools=(), mcp=False,
            max_turns=5, timeout=45, meta=None):
    model = _check(model, effort)
    if not command():
        raise AgentError("CodeBuddy CLI 不可用", code="cli_unavailable",
                         stage="cli", retryable=False)
    if not _lock.acquire(timeout=3):
        raise AgentError("CodeBuddy 正在处理另一个请求", code="agent_busy",
                         stage="queue", retryable=True)
    try:
        with tempfile.TemporaryDirectory(prefix="chess-coach-model-", ignore_cleanup_errors=True) as cwd:
            try:
                p = subprocess.run(
                    [*_flags(model, effort, tools, mcp, max_turns, "json")],
                    cwd=cwd, input=_prompt(messages).encode("utf8"), capture_output=True,
                    timeout=timeout, env=_env(),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired as exc:
                detail = "timeout={}s\nstdout={}\nstderr={}".format(
                    timeout, _tail(exc.stdout), _tail(exc.stderr))
                raise AgentError(f"CodeBuddy 超过 {int(timeout)} 秒未完成", code="timeout",
                                 stage="cli", retryable=True, detail=detail) from exc
    finally:
        _lock.release()
    combined = p.stdout + p.stderr
    if b"authentication required" in combined.lower():
        raise LoginRequired(detail=_tail(combined))
    if p.returncode:
        raise AgentError("CodeBuddy 调用失败", code="cli_failed", stage="cli",
                         retryable=True,
                         detail=f"exit_code={p.returncode}\nstdout={_tail(p.stdout)}\n"
                                f"stderr={_tail(p.stderr)}")
    if not p.stdout.strip():
        detail = _tail(p.stderr)
        message = "CodeBuddy 没有输出" + ("：" + detail[-300:] if detail else "，请稍后重试")
        raise AgentError(message, code="empty_output", stage="cli",
                         retryable=True, detail=detail)
    try:
        envelope = _envelopes(p.stdout)
    except (ValueError, TypeError) as exc:
        raise AgentError("CodeBuddy 事件流不是有效 JSON", code="invalid_envelope",
                         stage="decode", retryable=True,
                         detail=_tail(p.stdout)) from exc
    result = next((event for event in reversed(envelope)
                   if isinstance(event, dict) and event.get("type") == "result"), None)
    if not result:
        raise AgentError("CodeBuddy 未返回结果事件", code="missing_result",
                         stage="agent", retryable=True, detail=_tail(p.stdout))
    if result.get("is_error"):
        raise AgentError("CodeBuddy 未返回有效结果（" + str(result.get("subtype")) + "）",
                         code="agent_result_error", stage="agent", retryable=True,
                         detail=_tail(json.dumps(result, ensure_ascii=False)))
    if meta is not None:
        meta["model"] = _actual_model(envelope)
        meta["turns"] = result.get("num_turns")
    return _decode(result.get("structured_output") or result.get("result"))


def stop(holder):
    """停止后台 Agent 进程（含 Windows 上的子进程树）。"""
    holder = holder if holder is not None else {}
    holder["cancelled"] = True
    proc = holder.get("proc")
    if proc is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        pass


def stream(messages, *, model=None, effort=None, tools=AGENT_TOOLS, mcp=True,
           max_turns=AGENT_TURNS, timeout=AGENT_TIMEOUT, holder=None):
    """逐条产出 CLI 的 stream-json 事件；调用方停止时用 stop(holder) 结束进程。"""
    model = _check(model, effort)
    if not command():
        raise AgentError("CodeBuddy CLI 不可用", code="cli_unavailable",
                         stage="cli", retryable=False)
    if not _lock.acquire(timeout=3):
        raise AgentError("CodeBuddy 正在处理另一个请求", code="agent_busy",
                         stage="queue", retryable=True)
    holder = holder if holder is not None else {}
    if holder.get("cancelled"):
        _lock.release()
        return
    expired = threading.Event()
    directory = tempfile.TemporaryDirectory(prefix="chess-coach-agent-", ignore_cleanup_errors=True)
    try:
        proc = subprocess.Popen(
            _flags(model, effort, tools, mcp, max_turns, "stream-json"),
            cwd=directory.name, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=_env(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError:
        _lock.release()
        raise
    holder["proc"] = proc
    errors = []

    def read_errors():
        try:
            errors.append(proc.stderr.read() or b"")
        except (OSError, ValueError):
            pass

    threading.Thread(target=read_errors, daemon=True).start()

    def expire():
        expired.set()
        stop(holder)

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    try:
        try:
            proc.stdin.write(_prompt(messages).encode("utf8"))
            proc.stdin.close()
        except OSError:
            pass
        for raw in proc.stdout:
            line = raw.decode("utf8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                yield event
    finally:
        timer.cancel()
        stop(holder)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        _lock.release()
        try:
            directory.cleanup()
        except OSError:
            pass
    error = b"".join(errors)
    if b"authentication required" in error.lower():
        raise LoginRequired(detail=_tail(error))
    if expired.is_set():
        raise AgentError(f"CodeBuddy 超过 {int(timeout)} 秒仍未完成，已停止",
                         code="timeout", stage="agent", retryable=True,
                         detail=_tail(error))
    if proc.returncode and not holder.get("cancelled"):
        raise AgentError("CodeBuddy 调用失败", code="cli_failed", stage="agent",
                         retryable=True,
                         detail=f"exit_code={proc.returncode}\nstderr={_tail(error)}")


def decode_result(event):
    """把 result 事件里的最终 JSON 取出来。"""
    if not isinstance(event, dict) or event.get("is_error"):
        subtype = (event or {}).get("subtype") if isinstance(event, dict) else None
        detail = _tail(json.dumps(event, ensure_ascii=False)) if isinstance(event, dict) else ""
        raise AgentError("CodeBuddy 未返回有效结果" + (f"（{subtype}）" if subtype else ""),
                         code="agent_result_error", stage="agent", retryable=True,
                         detail=detail)
    return _decode(event.get("structured_output") or event.get("result"))
