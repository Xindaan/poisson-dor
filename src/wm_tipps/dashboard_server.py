from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .dashboard import CLI_UI_COMMANDS, build_dashboard_payload
from .io import read_json, write_json
from .paths import DATA_DIR, PROJECT_ROOT


COMMAND_RUNS_PATH = DATA_DIR / "ui_command_runs.json"
DEFAULT_TIMEOUT_SECONDS = 900
OUTPUT_TAIL_CHARS = 12000


def command_specs() -> dict[str, dict[str, Any]]:
    return {row["command"]: row for row in CLI_UI_COMMANDS}


def execute_ui_command(
    command: str,
    *,
    record: bool = True,
    refresh_dashboard: bool = True,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    specs = command_specs()
    spec = specs.get(command)
    if not spec:
        raise ValueError(f"Unbekanntes Kommando: {command}")
    if spec.get("runnable") is False:
        raise ValueError(spec.get("disabled_reason") or f"{command} ist nicht direkt aus der UI startbar.")

    args = list(spec.get("run_args") or [command])
    started_at = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(
        [sys.executable, "-m", "wm_tipps.cli", *args],
        cwd=PROJECT_ROOT,
        env=command_env(),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    finished_at = datetime.now(timezone.utc).isoformat()
    parsed_stdout = parse_stdout_json(proc.stdout)
    result = {
        "command": command,
        "args": args,
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": proc.returncode,
        "ok": command_result_ok(proc.returncode, proc.stdout),
        "stdout_tail": tail_text(proc.stdout),
        "stderr_tail": tail_text(proc.stderr),
    }
    if isinstance(parsed_stdout, dict):
        result["payload_ok"] = parsed_stdout.get("ok")
        if "quality_status" in parsed_stdout:
            result["quality_status"] = parsed_stdout.get("quality_status")
        if "quality_messages" in parsed_stdout:
            messages = parsed_stdout.get("quality_messages")
            result["quality_messages"] = messages[:6] if isinstance(messages, list) else messages
        if "steps_ok" in parsed_stdout and "steps_total" in parsed_stdout:
            result["steps_summary"] = f"{parsed_stdout.get('steps_ok')}/{parsed_stdout.get('steps_total')}"
    if record:
        record_command_run(result)
    if refresh_dashboard:
        build_dashboard_payload()
    return result


def command_env() -> dict[str, str]:
    env = dict(os.environ)
    src = str(PROJECT_ROOT / "src")
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src if not current else src + os.pathsep + current
    return env


def tail_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    value = str(value)
    if len(value) <= OUTPUT_TAIL_CHARS:
        return value
    return value[-OUTPUT_TAIL_CHARS:]


def command_result_ok(returncode: int, stdout: str) -> bool:
    if returncode != 0:
        return False
    payload = parse_stdout_json(stdout)
    if isinstance(payload, dict) and payload.get("ok") is False:
        return False
    return True


def parse_stdout_json(stdout: str) -> Any:
    try:
        return json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        return None


def record_command_run(result: dict[str, Any]) -> None:
    payload = read_json(COMMAND_RUNS_PATH, {"last_runs": {}, "history": []})
    if not isinstance(payload, dict):
        payload = {"last_runs": {}, "history": []}
    last_runs = payload.get("last_runs") if isinstance(payload.get("last_runs"), dict) else {}
    history = payload.get("history") if isinstance(payload.get("history"), list) else []
    last_runs[result["command"]] = result
    history.append(result)
    payload["last_runs"] = last_runs
    payload["history"] = history[-50:]
    write_json(COMMAND_RUNS_PATH, payload)


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    server_version = "WMTippsDashboard/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def end_headers(self) -> None:
        # Statische Assets (app.js/index.html/dashboard.json) nie cachen:
        # Safari haelt app.js sonst hartnaeckig -> Aenderungen erscheinen erst
        # nach manuellem "Cache-Speicher leeren". no-cache erzwingt Revalidierung.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_POST(self) -> None:
        if self.path != "/api/run-command":
            self.send_error(404, "Not found")
            return
        try:
            payload = self.read_json_body()
            command = str(payload.get("command") or "")
            result = execute_ui_command(command)
            self.write_json_response({"ok": True, "result": result})
        except ValueError as exc:
            self.write_json_response({"ok": False, "error": str(exc)}, status=400)
        except subprocess.TimeoutExpired as exc:
            result = {
                "command": str((getattr(exc, "cmd", []) or [""])[-1]),
                "ok": False,
                "returncode": None,
                "stdout_tail": tail_text(exc.stdout or ""),
                "stderr_tail": tail_text(exc.stderr or "Timeout"),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
            record_command_run(result)
            self.write_json_response({"ok": False, "error": "Timeout", "result": result}, status=504)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise ValueError("Request zu gross.")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON-Body muss ein Objekt sein.")
        return payload

    def write_json_response(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_dashboard(host: str = "127.0.0.1", port: int = 8002) -> dict[str, Any]:
    build_dashboard_payload()
    server = ThreadingHTTPServer((host, port), DashboardRequestHandler)
    url = f"http://{host}:{port}/"
    print(f"Serving WM dashboard with command runner on {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"status": "stopped", "url": url}
