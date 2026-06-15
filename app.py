from __future__ import annotations

import json
import re
import subprocess
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Dict
from urllib.parse import unquote

from encode_system import EncodeConfig, build_ffmpeg_command, estimate_encode_minutes, expected_size_mb, safe_output_name

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)
SAFE_OUTPUT_RE = re.compile(r"^[A-Za-z0-9._-]+\.mp4$")

jobs: Dict[str, Dict[str, str]] = {}
jobs_lock = Lock()


HTML_PAGE = """<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <title>Encode Sistemi</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 900px; margin: 24px auto; padding: 0 12px; }
    form { display: grid; gap: 8px; grid-template-columns: 1fr 1fr; }
    form > label { display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
    .full { grid-column: 1 / -1; }
    button { padding: 10px 14px; cursor: pointer; }
    pre { background: #f6f8fa; padding: 12px; overflow: auto; }
  </style>
</head>
<body>
  <h1>Video Encode Sistemi</h1>
  <p>Preset ile hızlı başla, istersen özel ayar gir.</p>
  <form id="frm">
    <label class="full">Video linki/dosya yolu<input name="input_source" required /></label>
    <label>Output adı<input name="output_file" value="encoded.mp4" /></label>
    <label>Süre (dakika)<input name="duration_minutes" type="number" step="0.1" value="20" /></label>
    <label>Runner
      <select name="runner_type"><option value="public">public (4 vCPU)</option><option value="private">private (2 vCPU)</option></select>
    </label>
    <label>Preset
      <select name="preset"><option>veryfast</option><option>fast</option><option selected>medium</option><option>slow</option></select>
    </label>
    <label>Çözünürlük
      <select name="resolution"><option value="source">source</option><option selected value="1080p">1080p</option><option value="720p">720p</option><option value="480p">480p</option></select>
    </label>
    <label>Mod
      <select name="mode"><option value="crf">CRF</option><option value="crf_cap">CRF + Cap</option><option value="two_pass">2-pass VBR</option></select>
    </label>
    <label>CRF<input name="crf" type="number" value="23" /></label>
    <label>Maxrate Mbps<input name="maxrate_mbps" type="number" step="0.1" value="5" /></label>
    <label>Target video Mbps<input name="target_video_bitrate_mbps" type="number" step="0.1" value="4" /></label>
    <label>Audio kbps<input name="audio_bitrate_k" type="number" value="128" /></label>
    <label class="full">Özel ffmpeg argümanları<input name="custom_extra_args" placeholder="-movflags +faststart" /></label>
    <div class="full"><button type="button" onclick="plan()">Planla</button> <button type="button" onclick="runEncode()">Encode Başlat</button></div>
  </form>
  <h3>Sonuç</h3>
  <pre id="out"></pre>
  <script>
    function formData() {
      const fd = new FormData(document.getElementById('frm'));
      return Object.fromEntries(fd.entries());
    }
    async function plan() {
      const r = await fetch('/api/plan', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(formData())});
      document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
    }
    async function runEncode() {
      const r = await fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(formData())});
      const j = await r.json();
      document.getElementById('out').textContent = JSON.stringify(j, null, 2);
      if (j.job_id) {
        poll(j.job_id);
      }
    }
    async function poll(id) {
      const timer = setInterval(async () => {
        const r = await fetch('/api/job/' + id);
        const j = await r.json();
        document.getElementById('out').textContent = JSON.stringify(j, null, 2);
        if (j.status !== 'running') clearInterval(timer);
      }, 2000);
    }
  </script>
</body>
</html>
"""


def to_config(data: dict) -> EncodeConfig:
    requested_name = safe_output_name(data.get("output_file", "encoded.mp4"))
    out_name = f"{uuid.uuid4().hex}-{requested_name}"
    return EncodeConfig(
        input_source=str(data.get("input_source", "")).strip(),
        output_file=out_name,
        duration_minutes=float(data.get("duration_minutes", 20)),
        runner_type=str(data.get("runner_type", "public")),
        preset=str(data.get("preset", "medium")),
        resolution=str(data.get("resolution", "1080p")),
        mode=str(data.get("mode", "crf")),
        crf=int(data.get("crf", 23)),
        maxrate_mbps=float(data.get("maxrate_mbps", 5)),
        audio_bitrate_k=int(data.get("audio_bitrate_k", 128)),
        target_video_bitrate_mbps=float(data.get("target_video_bitrate_mbps", 4)),
        custom_extra_args=str(data.get("custom_extra_args", "")),
    )


def output_path(output_name: str) -> Path:
    safe_name = safe_output_name(output_name)
    if not SAFE_OUTPUT_RE.fullmatch(safe_name):
        raise ValueError("Invalid output filename")
    target = (OUTPUT_DIR / safe_name).resolve()
    if not target.is_relative_to(OUTPUT_DIR):
        raise ValueError("Invalid output path")
    return target


def run_job(job_id: str, config: EncodeConfig) -> None:
    try:
        target_output = output_path(config.output_file)
        config.output_file = str(target_output)
        cmd1 = build_ffmpeg_command(config, pass_no=1)
        cmd2 = build_ffmpeg_command(config, pass_no=2) if config.mode == "two_pass" else None
        with jobs_lock:
            jobs[job_id]["command_pass_1"] = cmd1
            if cmd2 is not None:
                jobs[job_id]["command_pass_2"] = cmd2
        if config.mode == "two_pass":
            if cmd2 is None:
                raise ValueError("second pass command missing")
            subprocess.run(cmd1, check=True)
            subprocess.run(cmd2, check=True)
        else:
            subprocess.run(cmd1, check=True)
        with jobs_lock:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["download_url"] = f"/api/output/{job_id}"
            jobs[job_id]["preview_url"] = f"/api/output/{job_id}"
            jobs[job_id]["output_abs"] = str(target_output)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError, ValueError) as exc:
        with jobs_lock:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = str(exc)


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body = HTML_PAGE.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/output/"):
            job_id = unquote(self.path[len("/api/output/") :]).strip()
            with jobs_lock:
                job = jobs.get(job_id)
            if not job or job.get("status") != "completed":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            target = Path(job.get("output_abs", "")).resolve()
            if not target.is_relative_to(OUTPUT_DIR) or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
            self.end_headers()
            with target.open("rb") as fh:
                while chunk := fh.read(64 * 1024):
                    self.wfile.write(chunk)
            return
        if self.path.startswith("/api/job/"):
            job_id = self.path.split("/")[-1]
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                self._json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
                return
            self._json(HTTPStatus.OK, job)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            return
        config = to_config(payload)
        if not config.input_source:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "input_source is required"})
            return
        if self.path == "/api/plan":
            planned = EncodeConfig(**{**config.__dict__, "output_file": str(output_path(config.output_file))})
            cmd = build_ffmpeg_command(planned)
            self._json(
                HTTPStatus.OK,
                {
                    "estimated_encode_minutes": estimate_encode_minutes(config.duration_minutes, config.runner_type, config.preset),
                    "expected_output_mb": expected_size_mb(
                        config.duration_minutes,
                        config.mode,
                        config.target_video_bitrate_mbps,
                        config.audio_bitrate_k,
                        config.crf,
                    ),
                    "command": cmd,
                    "note": "CRF sahneye göre bitrate'i otomatik ayarlar.",
                },
            )
            return
        if self.path == "/api/run":
            job_id = str(uuid.uuid4())
            with jobs_lock:
                jobs[job_id] = {"status": "running", "job_id": job_id, "output_file": str(Path(config.output_file).name)}
            Thread(target=run_job, args=(job_id, config), daemon=True).start()
            self._json(HTTPStatus.ACCEPTED, {"job_id": job_id, "status": "running"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Server running at http://127.0.0.1:8000")
    server.serve_forever()
