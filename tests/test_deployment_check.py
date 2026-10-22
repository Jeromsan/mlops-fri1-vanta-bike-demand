"""Exercise the host checker against a small HTTP server, not TestClient."""

import json
import runpy
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

CHECK = runpy.run_path(str(Path(__file__).parents[1] / "scripts/smoke_api.py"))["main"]


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "model_version",
        "model_sha256",
        "source_commit",
        "json",
        "prediction",
        "invalid_status",
        "network",
    ],
)
def test_checker_accepts_only_matching_healthy_service(fault, capsys):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            result = {
                "status": "ok",
                "model_version": "approved",
                "model_sha256": "a" * 64,
                "source_commit": "source",
            }
            if fault in result:
                result[fault] = "wrong"
            self.reply(200, result)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            invalid = payload["hr"] == 24
            self.reply(
                200 if fault == "invalid_status" or not invalid else 422,
                {
                    "prediction": -1 if fault == "prediction" else 12.5,
                    "model_version": "approved",
                },
            )

        def reply(self, status, result):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(
                b"bad-json" if fault == "json" else json.dumps(result).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    if fault == "network":
        server.shutdown()
        server.server_close()
    try:
        result = CHECK(
            [
                url,
                "--expected-version",
                "approved",
                "--expected-sha256",
                "a" * 64,
                "--expected-commit",
                "source",
                "--startup-timeout",
                "0.1",
                "--request-timeout",
                "0.1",
            ]
        )
        assert result == (0 if fault is None else 1)
        records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert records
        assert all(
            {"expected", "observed", "result"} <= record.keys() for record in records
        )
    finally:
        if fault != "network":
            server.shutdown()
            server.server_close()
        thread.join(timeout=2)
