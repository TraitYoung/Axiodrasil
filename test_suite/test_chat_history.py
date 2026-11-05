"""验证轻量聊天记录存储与现有 SQLite 表兼容。"""

from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from storage.chat_history import ChatHistory


class ChatHistoryTests(unittest.TestCase):
    def test_existing_history_survives_and_sessions_stay_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "history.db")
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE chat_turns (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, user_text TEXT NOT NULL, assistant_text TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
                connection.execute("INSERT INTO chat_turns (thread_id, user_text, assistant_text) VALUES ('old', '以前的对话', '[bina]: 记得')")
            history = ChatHistory(path)
            history.append_turn("new", "新会话", "新回复")
            history.append_turn("old", "继续", "接着聊")
            self.assertEqual([turn["user"] for turn in history.get_turns("old")], ["以前的对话", "继续"])
            self.assertEqual([turn["user"] for turn in history.get_turns("old", 1)], ["继续"])
            self.assertEqual(len(history.get_turns("new")), 1)

    def test_new_database_only_creates_chat_history(self):
        with tempfile.TemporaryDirectory() as directory:
            history = ChatHistory(str(Path(directory) / "history.db"))
            with closing(sqlite3.connect(history.db_path)) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables, {"chat_turns", "sqlite_sequence"})


if __name__ == "__main__":
    unittest.main()
