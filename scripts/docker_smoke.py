"""Smoke-test the built Docker image against a real running container.

Runs the image on a throwaway data volume with a free host port, then checks the
SPA, the API, upload -> ready -> search, and that a graceful `docker stop` mid-ingest
leaves the document pending and a restart resumes it to ready. The container and data
volume are always removed, even when a check fails.

The embedding model downloads at server startup, so --models points at a persistent
named volume or host directory mounted at /data/models; reuse it between runs.
"""

import argparse
import io
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "backend/tests/fixtures/extraction/text.pdf"
READY_TIMEOUT = 600
PROXY_TIMEOUT = 15
APP_SOURCE = ROOT / "backend/src/oracle/server/app.py"
HEALTH_OK = {"status": "ok"}
BACKEND_PROBE = (
    "import urllib.request;"
    "print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"
    ".read().decode())"
)
INGEST_TIMEOUT = 300
STOP_TIMEOUT_SECONDS = 30
BIG_DOC_PARAGRAPHS = 1000


XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'
PKG = "http://schemas.openxmlformats.org/package/2006"
OPC = "application/vnd.openxmlformats"
WML = f"{OPC}-officedocument.wordprocessingml.document"
OFFICE_DOC = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def shutdown_ingest_timeout() -> int:
    match = re.search(
        r"^SHUTDOWN_INGEST_TIMEOUT_SECONDS = (\d+)$", APP_SOURCE.read_text(), re.M
    )
    if match is None:
        raise SmokeError(f"SHUTDOWN_INGEST_TIMEOUT_SECONDS not found in {APP_SOURCE}")
    return int(match.group(1))


class SmokeError(Exception):
    pass


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise SmokeError(f"docker {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def poll[T](
    description: str, probe: Callable[[], T], timeout: float, interval: float = 0.25
) -> T:
    deadline = time.monotonic() + timeout
    while True:
        value = probe()
        if value:
            return value
        if time.monotonic() > deadline:
            raise SmokeError(
                f"Timed out after {timeout:.0f}s waiting for {description}"
            )
        time.sleep(interval)


def make_big_docx(paragraphs: int) -> bytes:
    """A minimal .docx of many distinct paragraphs, so ingest takes several seconds."""
    body = "".join(
        f"<w:p><w:r><w:t>Paragraph {i} of the long survey. "
        + " ".join(f"entry{i}x{j} harbour tide cargo" for j in range(12))
        + "</w:t></w:r></w:p>"
        for i in range(paragraphs)
    )
    parts = {
        "[Content_Types].xml": (
            f'{XML_DECL}<Types xmlns="{PKG}/content-types">'
            f'<Default Extension="rels" ContentType="{OPC}-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{WML}.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            f'{XML_DECL}<Relationships xmlns="{PKG}/relationships">'
            f'<Relationship Id="rId1" Type="{OFFICE_DOC}" Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": (
            f'{XML_DECL}<w:document xmlns:w="{WORD_NS}">'
            f"<w:body>{body}</w:body></w:document>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class Container:
    def __init__(self, name: str, base_url: str = "") -> None:
        self.name = name
        self.base_url = base_url

    def refresh_port(self) -> None:
        # The ephemeral host port can change across a stop/start.
        def probe() -> str:
            out = docker("port", self.name, "80/tcp", check=False).stdout.split()
            return out[0] if out else ""

        mapping = poll("the container port mapping", probe, 30)
        self.base_url = f"http://127.0.0.1:{mapping.rsplit(':', 1)[1]}"

    def request(
        self,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return int(resp.status), bytes(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def get_json(self, path: str) -> dict[str, Any] | list[Any]:
        status, body = self.request(path)
        if status != 200:
            raise SmokeError(f"GET {path} returned {status}: {body[:99]!r}")
        return json.loads(body)

    def upload(self, filename: str, content: bytes) -> int:
        boundary = uuid.uuid4().hex
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        status, resp = self.request(
            "/api/documents",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        if status != 202:
            raise SmokeError(f"Upload of {filename} returned {status}: {resp[:200]!r}")
        return int(json.loads(resp)["id"])

    def get_document(self, doc_id: int) -> dict[str, Any]:
        document = self.get_json(f"/api/documents/{doc_id}")
        if not isinstance(document, dict):
            raise SmokeError(f"Unexpected document payload: {document!r}")
        return document

    def doc_status(self, doc_id: int) -> str:
        return str(self.get_document(doc_id)["status"])

    def require_running(self) -> None:
        state = docker("inspect", "-f", "{{.State.Running}}", self.name, check=False)
        if state.stdout.strip() != "true":
            raise SmokeError("Container is not running")

    def wait_healthy(self) -> None:
        """Wait for the backend (long: the model downloads at startup), then nginx."""

        def backend_up() -> bool:
            self.require_running()
            result = docker(
                "exec", self.name, "/app/backend/.venv/bin/python", "-c",
                BACKEND_PROBE,
                check=False,
            )  # fmt: skip
            try:
                return bool(json.loads(result.stdout) == HEALTH_OK)
            except ValueError:
                return False

        poll(
            "the backend /health (the embedding model downloads at startup)",
            backend_up,
            READY_TIMEOUT,
            1,
        )

        def proxy_up() -> bool:
            self.require_running()
            try:
                status, body = self.request("/api/health")
                return status == 200 and bool(json.loads(body) == HEALTH_OK)
            except (OSError, ValueError):
                return False

        # nginx also answers 200 with index.html for unknown paths, so the body
        # must parse as the health JSON to prove /api/ reaches the backend.
        poll("nginx to proxy /api/health to the backend", proxy_up, PROXY_TIMEOUT, 0.5)

    def wait_status(self, doc_id: int, wanted: str) -> None:
        def probe() -> bool:
            status = self.doc_status(doc_id)
            if status == "failed":
                detail = self.get_document(doc_id)
                raise SmokeError(f"Document {doc_id} failed: {detail}")
            return status == wanted

        poll(f"document {doc_id} to be {wanted}", probe, INGEST_TIMEOUT)

    def db_status(self, doc_id: int) -> str:
        """Read a stopped container's db; the graceful shutdown checkpointed the WAL."""
        with tempfile.TemporaryDirectory() as tmp:
            docker("cp", f"{self.name}:/data/oracle.db", tmp)
            docker("cp", f"{self.name}:/data/oracle.db-wal", tmp, check=False)
            conn = sqlite3.connect(Path(tmp) / "oracle.db")
            try:
                row = conn.execute(
                    "SELECT status FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            raise SmokeError(f"Document {doc_id} not in the stopped container's db")
        return str(row[0])


def step(message: str) -> None:
    print(f"==> {message}", flush=True)


def run_checks(container: Container, search_term: str) -> None:
    drain_limit = shutdown_ingest_timeout()
    step("waiting for the server to be healthy")
    started = time.monotonic()
    container.wait_healthy()
    print(f"    healthy after {time.monotonic() - started:.1f}s")

    step("GET / serves the SPA")
    status, body = container.request("/")
    if status != 200 or b'<div id="app"' not in body:
        raise SmokeError(
            f"GET / returned {status} without the SPA root: {body[:200]!r}"
        )

    step("GET /api/documents")
    container.get_json("/api/documents")

    step("upload text.pdf, wait for ready, search")
    doc_id = container.upload("text.pdf", FIXTURE.read_bytes())
    container.wait_status(doc_id, "ready")
    status, body = container.request(
        "/api/search",
        data=json.dumps({"query": search_term}).encode(),
        headers={"Content-Type": "application/json"},
    )
    if status != 200:
        raise SmokeError(f"POST /api/search returned {status}: {body[:200]!r}")
    results = json.loads(body)["results"]
    if not any(
        r["doc_id"] == doc_id and search_term.lower() in r["text"].lower()
        for r in results
    ):
        raise SmokeError(f"No hit containing {search_term!r} in text.pdf: {results!r}")

    step("upload a large document and docker stop it mid-ingest")
    big_id = container.upload("big.docx", make_big_docx(BIG_DOC_PARAGRAPHS))
    if container.doc_status(big_id) != "pending":
        raise SmokeError("Large document finished before the stop; make it bigger")
    stop_started = time.monotonic()
    result = docker("stop", "-t", str(STOP_TIMEOUT_SECONDS), container.name)
    stop_seconds = time.monotonic() - stop_started
    print(f"    stopped in {stop_seconds:.1f}s")
    exit_code = docker(
        "inspect", "-f", "{{.State.ExitCode}}", container.name
    ).stdout.strip()
    if exit_code != "0":
        raise SmokeError(
            f"Container exited {exit_code} on SIGTERM (137 means it was killed): "
            f"{result.stderr.strip()}"
        )
    # Exit 0 and a pending row also come from an abandoned ingest that merely ran
    # out the drain timeout, so require the interrupt log line and a fast stop.
    if stop_seconds >= drain_limit:
        raise SmokeError(
            f"Stop took {stop_seconds:.1f}s, not under the {drain_limit}s ingest drain "
            "timeout: the ingest was not interrupted promptly"
        )
    logs = docker("logs", container.name, check=False)
    interrupted = f"Ingest of document {big_id} interrupted; left pending"
    if interrupted not in logs.stdout + logs.stderr:
        raise SmokeError(f"Stop logs lack {interrupted!r}")
    if (db_status := container.db_status(big_id)) != "pending":
        raise SmokeError(
            f"Stop did not interrupt the ingest: document is {db_status!r}, not pending"
        )

    step("docker start resumes the pending document")
    docker("start", container.name)
    container.refresh_port()
    container.wait_healthy()
    container.wait_status(big_id, "ready")
    logs = docker("logs", container.name, check=False)
    if "Resuming 1 document(s) left pending" not in logs.stdout + logs.stderr:
        raise SmokeError("Restart logs lack the startup resume message")


def chown_models(image: str, models: str) -> None:
    # The container writes the cache as root; hand it back so cache save works.
    docker(
        "run", "--rm", "--entrypoint", "chown", "-v", f"{models}:/models", image,
        "-R", f"{os.getuid()}:{os.getgid()}", "/models",
        check=False,
    )  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="oracle-smoke")
    parser.add_argument(
        "--models",
        default="oracle-smoke-models",
        help="named volume or absolute host directory mounted at /data/models",
    )
    parser.add_argument("--search-term", default="lighthouse")
    args = parser.parse_args()

    # Turn SIGTERM into an exception so the finally block still tears down.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    if args.models.startswith("/"):
        Path(args.models).mkdir(parents=True, exist_ok=True)

    suffix = uuid.uuid4().hex[:8]
    name = f"oracle-smoke-{suffix}"
    data_volume = f"oracle-smoke-data-{suffix}"
    container = Container(name)
    started = time.monotonic()
    try:
        docker("volume", "create", data_volume)
        docker(
            "run", "-d", "--init", "--name", name,
            "-p", "127.0.0.1::80",
            "-v", f"{data_volume}:/data",
            "-v", f"{args.models}:/data/models",
            args.image,
        )  # fmt: skip
        container.refresh_port()
        run_checks(container, args.search_term)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        if not isinstance(exc, SmokeError):
            traceback.print_exc()
        logs = docker("logs", "--tail", "40", name, check=False)
        print(logs.stdout + logs.stderr, file=sys.stderr)
        return 1
    finally:
        docker("rm", "-f", name, check=False)
        docker("volume", "rm", "-f", data_volume, check=False)
        if args.models.startswith("/"):
            chown_models(args.image, args.models)
    print(f"PASS in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
