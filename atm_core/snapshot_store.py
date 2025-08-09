from __future__ import annotations
import os, sqlite3, json, gzip, time, uuid, pathlib
from typing import Optional, Dict, Any
from .models import AgentState, sha256_text

class SnapshotStore:
    def __init__(self, root: str):
        self.root = root
        self.db_path = os.path.join(root, "index.sqlite")
        self.blob_dir = os.path.join(root, "blobs")
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(self.blob_dir, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS snapshots ('
                  'snapshot_id TEXT PRIMARY KEY,'
                  'parent_snapshot_id TEXT,'
                  'state_hash TEXT,'
                  'state_blob_hash TEXT,'
                  'created_at REAL)')
        c.execute('CREATE TABLE IF NOT EXISTS tool_ledger ('
                  'id INTEGER PRIMARY KEY AUTOINCREMENT,'
                  'snapshot_id TEXT,'
                  'name TEXT,'
                  'in_hash TEXT,'
                  'out_hash TEXT,'
                  'status TEXT,'
                  'latency_ms INTEGER,'
                  'url TEXT,'
                  'created_at REAL)')
        conn.commit()
        conn.close()

    def _write_blob(self, data: bytes) -> str:
        h = sha256_text(data.decode("utf-8", errors="ignore"))
        path = os.path.join(self.blob_dir, f"{h}.json.gz")
        if not os.path.exists(path):
            with gzip.open(path, "wb") as f:
                f.write(data)
        return h

    def _read_blob(self, h: str) -> bytes:
        path = os.path.join(self.blob_dir, f"{h}.json.gz")
        with gzip.open(path, "rb") as f:
            return f.read()

    def snapshot(self, state: AgentState, parent_snapshot_id: Optional[str]=None) -> str:
        state_json = state.to_json()
        state_hash = sha256_text(state_json)
        blob_hash = self._write_blob(state_json.encode("utf-8"))
        snap_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT INTO snapshots (snapshot_id, parent_snapshot_id, state_hash, state_blob_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                  (snap_id, parent_snapshot_id, state_hash, blob_hash, time.time()))
        # persist tool ledger entries referencing this snapshot
        for tc in state.tool_ledger:
            c.execute("INSERT INTO tool_ledger (snapshot_id, name, in_hash, out_hash, status, latency_ms, url, created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (snap_id, tc.name, tc.in_hash, tc.out_hash, tc.status, tc.latency_ms, tc.url, tc.created_at))
        conn.commit()
        conn.close()
        return snap_id

    def get(self, snapshot_id: str) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT state_blob_hash FROM snapshots WHERE snapshot_id=?", (snapshot_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            raise KeyError(f"Snapshot {snapshot_id} not found")
        blob_hash = row[0]
        data = self._read_blob(blob_hash)
        return json.loads(data.decode("utf-8"))

    def last_snapshot_id(self) -> Optional[str]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
