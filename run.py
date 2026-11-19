"""启动本地服务：python run.py"""
import os
import socket
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

if __name__ == "__main__":
    host, port = "127.0.0.1", 8765
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((host, port)) == 0:
            raise SystemExit(
                f"{host}:{port} 已有服务在运行。请先停止旧服务（在原终端按 Ctrl+C），"
                "再运行 python run.py 加载新版后端。"
            )
    print(f"chess-coach: http://{host}:{port}")
    try:
        webbrowser.open(f"http://{host}:{port}")
    except Exception:
        pass
    uvicorn.run("src.app:app", host=host, port=port, reload=False, log_level="info")
