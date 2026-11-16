"""
server.py
---------
Upload one or more report files in the browser, watch the three agents run,
and see the merged graph drawn on the dashboard.

  python server.py          # http://localhost:8000

POST /build  (multipart, field name "files")  ->  newline-delimited JSON events
"""

import json
import os
import queue
import threading

import uvicorn
from fastapi import FastAPI, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from graph_builder import build_graph_from_text

ROOT = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="defense-logistics graph builder")


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "ui", "index.html"))


@app.post("/build")
async def build(files: list[UploadFile]):
    # Several files are just concatenated with a header each; V1 keeps it simple.
    parts = []
    for f in files:
        text = (await f.read()).decode("utf-8", errors="replace")
        parts.append(f"=== {f.filename} ===\n{text}")
    report = "\n\n".join(parts)

    q: queue.Queue = queue.Queue()

    def worker():
        try:
            build_graph_from_text(report, on_event=q.put)
        except Exception as e:
            q.put({"event": "error", "error": f"{type(e).__name__}: {e}"})
        finally:
            q.put({"event": "done"})

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield json.dumps({"event": "received", "files": [f.filename for f in files],
                          "chars": len(report)}) + "\n"
        while True:
            ev = q.get()
            yield json.dumps(ev) + "\n"
            if ev["event"] == "done":
                break

    return StreamingResponse(stream(), media_type="application/x-ndjson")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
