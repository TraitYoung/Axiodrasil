"""只保存原始聊天记录，沿用已有 chat_turns 表。"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3


class ChatHistory:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS chat_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_chat_turns_thread_created ON chat_turns (thread_id, created_at)")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def append_turn(self, session_id: str, user_text: str, assistant_text: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO chat_turns (thread_id, user_text, assistant_text) VALUES (?, ?, ?)",
                (session_id, user_text, assistant_text),
            )
            return int(cursor.lastrowid)

    def get_turns(self, session_id: str, limit: int = 50) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT user_text, assistant_text, created_at FROM chat_turns WHERE thread_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, max(1, limit)),
            ).fetchall()
        return [{"user": user, "assistant": assistant, "ts": str(timestamp or "")}
                for user, assistant, timestamp in reversed(rows)]

    def format_for_prompt(self, session_id: str, limit: int = 5) -> list[str]:
        return [f"User: {turn['user']}\nBina: {turn['assistant']}"
                for turn in self.get_turns(session_id, limit)]
