#!/usr/bin/env python3
"""Simple HTTP webhook service for Grafana alerts.

This service is intentionally dependency-free so it can run in environments
without extra package installs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict


class AlertWebhookHandler(BaseHTTPRequestHandler):
    server_version = "AlertWebhook/1.0"

    def _json_response(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        if not raw:
            return {}
        try:
            decoded = raw.decode("utf-8")
            parsed = json.loads(decoded)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except Exception as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc

    def _is_authorized(self) -> bool:
        token = self.server.auth_token  # type: ignore[attr-defined]
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {token}"

    def _store_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        log_path: Path = self.server.log_path  # type: ignore[attr-defined]
        event = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "source": "grafana-webhook",
            "remote": self.client_address[0],
            "payload": payload,
        }

        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

        print(
            f"[{event['received_at']}] {event_type} from {event['remote']} -> {log_path}",
            flush=True,
        )

    def _run_auto_ingest(self) -> Dict[str, Any]:
        if not getattr(self.server, "auto_ingest", False):  # type: ignore[attr-defined]
            return {"enabled": False}

        ingest_script: Path = self.server.ingest_script  # type: ignore[attr-defined]
        bpmn_file: Path = self.server.bpmn_file  # type: ignore[attr-defined]
        log_path: Path = self.server.log_path  # type: ignore[attr-defined]

        if not ingest_script.exists():
            return {
                "enabled": True,
                "ok": False,
                "error": f"Ingest script not found: {ingest_script}",
            }

        if not bpmn_file.exists():
            return {
                "enabled": True,
                "ok": False,
                "error": f"BPMN file not found: {bpmn_file}",
            }

        cmd = [
            sys.executable,
            str(ingest_script),
            "--bpmn",
            str(bpmn_file),
            "--alerts-file",
            str(log_path),
            "--output",
            str(bpmn_file),
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception as exc:
            return {
                "enabled": True,
                "ok": False,
                "error": f"Failed to execute ingestion script: {exc}",
            }

        ok = proc.returncode == 0
        return {
            "enabled": True,
            "ok": ok,
            "code": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "bpmn": str(bpmn_file),
        }

    def log_message(self, format: str, *args: Any) -> None:
        # Keep output concise while still showing request metadata.
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"{self.client_address[0]} {self.command} {self.path} "
            + format % args,
            flush=True,
        )

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json_response(200, {"ok": True, "service": "alert-webhook"})
            return

        self._json_response(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._is_authorized():
            self._json_response(401, {"ok": False, "error": "Unauthorized"})
            return

        if self.path not in {"/grafana/alert", "/threshold-exceeded", "/error"}:
            self._json_response(404, {"ok": False, "error": "Not found"})
            return

        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._json_response(400, {"ok": False, "error": str(exc)})
            return

        event_type = {
            "/grafana/alert": "grafana_alert",
            "/threshold-exceeded": "threshold_exceeded",
            "/error": "error_event",
        }[self.path]

        self._store_event(event_type, payload)
        ingest_result = self._run_auto_ingest()
        self._json_response(
            200,
            {
                "ok": True,
                "received": event_type,
                "status": payload.get("status", "unknown"),
                "ingest": ingest_result,
            },
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Grafana alert webhook service.")
    parser.add_argument("--host", default=os.getenv("WEBHOOK_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("WEBHOOK_PORT", "8088")))
    parser.add_argument(
        "--log-file",
        default=os.getenv(
            "WEBHOOK_LOG_FILE",
            str(Path(__file__).resolve().parent.parent / "bin" / "alert-webhook" / "alerts.ndjson"),
        ),
    )
    parser.add_argument(
        "--auth-token",
        default=os.getenv("WEBHOOK_AUTH_TOKEN", ""),
        help="Optional bearer token required for POST requests.",
    )
    parser.add_argument(
        "--auto-ingest",
        action="store_true",
        default=os.getenv("WEBHOOK_AUTO_INGEST", "").lower() in {"1", "true", "yes"},
        help="Automatically ingest alerts into a BPMN file after each webhook event.",
    )
    parser.add_argument(
        "--bpmn-file",
        default=os.getenv("WEBHOOK_BPMN_FILE", ""),
        help="BPMN file to update when --auto-ingest is enabled.",
    )
    parser.add_argument(
        "--ingest-script",
        default=os.getenv(
            "WEBHOOK_INGEST_SCRIPT",
            str(Path(__file__).resolve().parents[1] / ".." / "tests" / "ingest_alerts_into_bpmn.py"),
        ),
        help="Path to tests/ingest_alerts_into_bpmn.py.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_path = Path(args.log_file).resolve()

    server = ThreadingHTTPServer((args.host, args.port), AlertWebhookHandler)
    server.log_path = log_path  # type: ignore[attr-defined]
    server.auth_token = args.auth_token  # type: ignore[attr-defined]
    server.auto_ingest = args.auto_ingest  # type: ignore[attr-defined]
    server.bpmn_file = Path(args.bpmn_file).resolve() if args.bpmn_file else Path("")  # type: ignore[attr-defined]
    server.ingest_script = Path(args.ingest_script).resolve()  # type: ignore[attr-defined]

    print(f"Starting alert webhook service on http://{args.host}:{args.port}", flush=True)
    print("Endpoints: GET /health, POST /grafana/alert, POST /threshold-exceeded, POST /error", flush=True)
    print(f"Writing events to: {log_path}", flush=True)
    if args.auto_ingest:
        print(f"Auto-ingest enabled for BPMN file: {server.bpmn_file}", flush=True)
        print(f"Using ingest script: {server.ingest_script}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down webhook service...", flush=True)
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
