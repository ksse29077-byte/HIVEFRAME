"""SQLite metadata and external artifact storage for P0."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterator
import json
import sqlite3
import threading
import uuid

from .contracts import MAX_REFERENCE_BYTES, utc_now, validate_public_id, validate_reference_name


class ProductStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        repository_root = Path(__file__).resolve().parents[2]
        if self.root == repository_root or repository_root in self.root.parents:
            raise ValueError("artifact root must be outside the Git repository")
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets_root = self.root / "assets"
        self.assets_root.mkdir(exist_ok=True)
        self.database_path = self.root / "hiveframe-p0.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    reference_asset_id TEXT,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    output_asset_id TEXT,
                    receipt_id TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    profile TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    generation_consent INTEGER NOT NULL
                    ,backend_job_id TEXT
                    ,request_json TEXT NOT NULL DEFAULT '{}'
                    ,resolution TEXT NOT NULL DEFAULT '768P'
                    ,aspect_ratio TEXT NOT NULL DEFAULT '16:9'
                    ,backend_state TEXT NOT NULL DEFAULT 'queued'
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    user_accepted INTEGER,
                    feedback_reason TEXT,
                    generation_consent INTEGER NOT NULL,
                    training_opt_in INTEGER NOT NULL,
                    training_eligibility TEXT NOT NULL,
                    deletion_requested INTEGER NOT NULL,
                    retention_status TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                );
                """
            )
            existing = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            migrations = {
                "backend_job_id": "TEXT",
                "request_json": "TEXT NOT NULL DEFAULT '{}'",
                "resolution": "TEXT NOT NULL DEFAULT '768P'",
                "aspect_ratio": "TEXT NOT NULL DEFAULT '16:9'",
                "backend_state": "TEXT NOT NULL DEFAULT 'queued'",
            }
            for name, declaration in migrations.items():
                if name not in existing:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")

    def create_job(self, values: dict[str, Any]) -> dict[str, Any]:
        columns = (
            "job_id", "created_at", "updated_at", "backend", "model", "prompt",
            "reference_asset_id", "status", "error_code",
            "error_message", "output_asset_id", "receipt_id", "retry_count",
            "profile", "duration_seconds", "generation_consent",
            "backend_job_id", "request_json",
            "resolution", "aspect_ratio", "backend_state",
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                f"INSERT INTO jobs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values.get(column) for column in columns),
            )
            connection.execute(
                "INSERT INTO job_events(job_id,status,created_at) VALUES (?,?,?)",
                (values["job_id"], values["status"], values["created_at"]),
            )
        return self.get_job(values["job_id"])

    def update_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        validate_public_id(job_id, "job_id")
        allowed = {
            "updated_at", "reference_asset_id", "status",
            "error_code", "error_message", "output_asset_id", "receipt_id",
            "retry_count", "backend_job_id", "request_json", "backend_state",
        }
        if not changes or set(changes) - allowed:
            raise ValueError("unsupported job update")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {','.join(f'{name}=?' for name in changes)} WHERE job_id=?",
                (*changes.values(), job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
            if "status" in changes:
                connection.execute(
                    "INSERT INTO job_events(job_id,status,created_at) VALUES (?,?,?)",
                    (job_id, changes["status"], changes.get("updated_at", utc_now())),
                )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        validate_public_id(job_id, "job_id")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = dict(row)
        result["generation_consent"] = bool(result["generation_consent"])
        return result

    def job_events(self, job_id: str) -> list[str]:
        validate_public_id(job_id, "job_id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status FROM job_events WHERE job_id=? ORDER BY event_id", (job_id,)
            ).fetchall()
        return [str(row["status"]) for row in rows]

    def save_reference(self, job_id: str, filename: str, media_type: str, content: bytes) -> dict[str, Any]:
        filename = validate_reference_name(filename)
        if not content or len(content) > MAX_REFERENCE_BYTES:
            raise ValueError(f"reference image must contain 1 to {MAX_REFERENCE_BYTES} bytes")
        return self._save_asset(job_id, "reference", filename, media_type, content)

    def save_result(self, job_id: str, filename: str, media_type: str, content: bytes) -> dict[str, Any]:
        if filename != Path(filename).name or not filename:
            raise ValueError("unsafe result filename")
        return self._save_asset(job_id, "result", filename, media_type, content)

    def save_receipt(self, job_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        content = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        return self._save_asset(job_id, "receipt", "receipt.json", "application/json", content)

    def _save_asset(self, job_id: str, kind: str, filename: str, media_type: str, content: bytes) -> dict[str, Any]:
        validate_public_id(job_id, "job_id")
        asset_id = f"asset_{uuid.uuid4().hex}"
        relative_path = Path(job_id) / asset_id / filename
        destination = (self.assets_root / relative_path).resolve()
        if self.assets_root.resolve() not in destination.parents:
            raise ValueError("artifact path escaped the artifact root")
        destination.parent.mkdir(parents=True, exist_ok=False)
        with destination.open("xb") as handle:
            handle.write(content)
        metadata = {
            "asset_id": asset_id,
            "job_id": job_id,
            "kind": kind,
            "filename": filename,
            "relative_path": relative_path.as_posix(),
            "sha256": sha256(content).hexdigest(),
            "size_bytes": len(content),
            "media_type": media_type,
            "created_at": utc_now(),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO assets(asset_id,job_id,kind,filename,relative_path,sha256,size_bytes,media_type,created_at)
                   VALUES (:asset_id,:job_id,:kind,:filename,:relative_path,:sha256,:size_bytes,:media_type,:created_at)""",
                metadata,
            )
        return metadata

    def get_asset(self, asset_id: str) -> tuple[dict[str, Any], Path]:
        validate_public_id(asset_id, "asset_id")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        metadata = dict(row)
        path = (self.assets_root / metadata["relative_path"]).resolve()
        if self.assets_root.resolve() not in path.parents or not path.is_file():
            raise FileNotFoundError(asset_id)
        return metadata, path

    def save_feedback(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO feedback(
                       feedback_id,job_id,created_at,decision,user_accepted,feedback_reason,
                       generation_consent,training_opt_in,training_eligibility,
                       deletion_requested,retention_status)
                   VALUES (:feedback_id,:job_id,:created_at,:decision,:user_accepted,:feedback_reason,
                       :generation_consent,:training_opt_in,:training_eligibility,
                       :deletion_requested,:retention_status)""",
                values,
            )
        return self.get_feedback(values["feedback_id"])

    def get_feedback(self, feedback_id: str) -> dict[str, Any]:
        validate_public_id(feedback_id, "feedback_id")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM feedback WHERE feedback_id=?", (feedback_id,)).fetchone()
        if row is None:
            raise KeyError(feedback_id)
        result = dict(row)
        result["user_accepted"] = None if result["user_accepted"] is None else bool(result["user_accepted"])
        for field in ("generation_consent", "training_opt_in", "deletion_requested"):
            result[field] = bool(result[field])
        return result
