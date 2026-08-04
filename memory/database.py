import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory import crypto


class PersonaMemory:
    def __init__(self, db_path: str = "./data/axiodrasil_core.db"):
        # 确保数据库所在目录存在（首次运行不报错）
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # 【敏感字段加密，可选开启，见 memory/crypto.py】
        # 未设置 AX_MEMORY_ENC_KEY 时保持明文存储（不影响现有 FTS5 关键词检索）；
        # 设置后 memory_matrix.content / memory_fragments.content 会以密文落库。
        # 已知取舍：memory_matrix 走 FTS5 external-content 触发器同步索引，
        # 触发器只能原样复制列值，没有能力在 SQL 层做解密再分词——因此一旦
        # 开启加密，新写入的 memory_matrix 记录会导致 FTS5 关键词召回失效
        # （索引到的是密文，无法匹配明文查询），Hybrid 检索会自然退化为
        # 向量 + 实体两路。如果要两者兼得，需要单独维护一份"仅供分词、不含
        # 原文"的摘要列，这个不在本次改造范围内，先诚实记录这个限制。
        self._init_db()

    # ---------- 加解密（委托给 memory/crypto.py，避免多处重复实现） ----------
    def _encrypt(self, plaintext: str) -> str:
        return crypto.encrypt(plaintext)

    def _decrypt(self, stored: str) -> str:
        return crypto.decrypt(stored)

    @property
    def encryption_enabled(self) -> bool:
        return crypto.is_enabled()

    def _connect(self) -> sqlite3.Connection:
        # 短 busy 等待：跨 WSL/UNC 访问时避免整轮请求卡死数十秒
        conn = sqlite3.connect(self.db_path, timeout=1.0)
        conn.execute("PRAGMA busy_timeout=1000")
        return conn

    def _init_db(self) -> None:
        """初始化记忆矩阵表 + FTS5 视图 + 向量表 + 滚动摘要/细粒度记忆/实体表"""
        with self._connect() as conn:
            # 1) 原始记忆矩阵
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_matrix (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT,
                    quadrant TEXT,
                    content TEXT,
                    status TEXT DEFAULT 'active', -- active / archived
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # 为高频查询字段添加联合索引
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_thread_quadrant_status
                ON memory_matrix (thread_id, quadrant, status)
                """
            )

            # 2) 向量表：存放 embedding 客户端产出的向量（当前 1536 维 float32）
            # 冷启动与增量更新交由 migration/上层逻辑负责
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id INTEGER PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memory_matrix(id) ON DELETE CASCADE
                )
                """
            )

            # 3) FTS5 虚拟表：映射 memory_matrix
            # 采用 external content 模式，仅索引必要字段
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(
                    content,
                    quadrant,
                    thread_id,
                    content='memory_matrix',
                    content_rowid='id'
                )
                """
            )

            # 4) 触发器：保持 memory_matrix 与 memory_fts 同步
            conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS memory_matrix_ai
                AFTER INSERT ON memory_matrix
                BEGIN
                    INSERT INTO memory_fts(rowid, content, quadrant, thread_id)
                    VALUES (new.id, new.content, new.quadrant, new.thread_id);
                END;

                CREATE TRIGGER IF NOT EXISTS memory_matrix_ad
                AFTER DELETE ON memory_matrix
                BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, content, quadrant, thread_id)
                    VALUES('delete', old.id, old.content, old.quadrant, old.thread_id);
                END;

                CREATE TRIGGER IF NOT EXISTS memory_matrix_au
                AFTER UPDATE ON memory_matrix
                BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, content, quadrant, thread_id)
                    VALUES('delete', old.id, old.content, old.quadrant, old.thread_id);
                    INSERT INTO memory_fts(rowid, content, quadrant, thread_id)
                    VALUES (new.id, new.content, new.quadrant, new.thread_id);
                END;
                """
            )

            # 5) 滚动摘要层：填补 Redis 5 轮窗口与 L3 长期记忆之间的中期记忆空白
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT,
                    range_start_ts TEXT,
                    range_end_ts TEXT,
                    turn_count INTEGER,
                    summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_summaries_thread
                ON memory_summaries (thread_id, created_at)
                """
            )

            # 6) 每个 thread 的滚动计数器：累计多少轮未生成摘要
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_turn_counters (
                    thread_id TEXT PRIMARY KEY,
                    turns_since_summary INTEGER NOT NULL DEFAULT 0,
                    total_turns INTEGER NOT NULL DEFAULT 0
                )
                """
            )

            # 7) 细粒度记忆碎片：事实 / 偏好 / 情绪快照，由后台异步任务从
            # Q1/Q2 原始内容中提取，取代"整段 raw_input 直接向量化"的粗粒度方案
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_fragments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT,
                    source_memory_id INTEGER,
                    fragment_type TEXT, -- 'fact' | 'preference' | 'emotion'
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_memory_id) REFERENCES memory_matrix(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fragments_thread_type
                ON memory_fragments (thread_id, fragment_type)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_fragment_embeddings (
                    fragment_id INTEGER PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    FOREIGN KEY (fragment_id) REFERENCES memory_fragments(id) ON DELETE CASCADE
                )
                """
            )

            # 8) 实体聚合表：Hybrid RAG 第三路召回（人物/项目/关键词 -> 关联记忆 id）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT,
                    name TEXT,
                    entity_type TEXT, -- 'person' | 'project' | 'keyword' | ...
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(thread_id, name, entity_type)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_memory_links (
                    entity_id INTEGER,
                    memory_id INTEGER,
                    source TEXT, -- 'matrix' | 'fragment'
                    PRIMARY KEY (entity_id, memory_id, source),
                    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
                )
                """
            )

            # 9) 会话 turn 持久化：Redis 热缓存之外的冷历史，供 history/export / 断线续聊
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_turns_thread_created
                ON chat_turns (thread_id, created_at)
                """
            )

            # 10) 人设私忆：fragments.persona 列（空字符串 = 旧共享碎片 / 共识侧）
            frag_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(memory_fragments)").fetchall()
            }
            if "persona" not in frag_cols:
                conn.execute(
                    "ALTER TABLE memory_fragments ADD COLUMN persona TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_fragments_thread_persona
                ON memory_fragments (thread_id, persona, fragment_type)
                """
            )

            # 11) 内阁吵架层（M1）状态 + 轮次
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cabinet_debate_state (
                    thread_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'closed', -- open / closed
                    opened_at TIMESTAMP,
                    closed_at TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cabinet_debate_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    role TEXT NOT NULL, -- user | assistant
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_debate_turns_thread
                ON cabinet_debate_turns (thread_id, id)
                """
            )

            # 12) 内阁共识层（M3）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cabinet_consensus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    conclusions TEXT NOT NULL DEFAULT '',
                    unresolved TEXT NOT NULL DEFAULT '',
                    action_items TEXT NOT NULL DEFAULT '',
                    source_turn_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_consensus_thread
                ON cabinet_consensus (thread_id, created_at)
                """
            )

            conn.commit()

    # ==================== L3 原始记忆矩阵 ====================
    def save_memory(self, thread_id: str, content: str, quadrant: str) -> int:
        """存入记忆（文本部分）。向量部分由上层在生成 embedding 后写入 memory_embeddings。

        返回新写入行的 id，便于上层（异步提取任务）关联 source_memory_id。
        """
        stored_content = self._encrypt(content)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO memory_matrix (thread_id, content, quadrant) VALUES (?, ?, ?)",
                (thread_id, stored_content, quadrant),
            )
            conn.commit()
            return int(cur.lastrowid)

    def save_memory_embedding(self, memory_id: int, embedding_blob: bytes) -> None:
        """在线写入 matrix 向量；与 migration 冷启动路径共用同一表。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_embeddings (memory_id, embedding)
                VALUES (?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET embedding = excluded.embedding
                """,
                (memory_id, embedding_blob),
            )
            conn.commit()

    def get_active_q1(self, thread_id: str) -> List[str]:
        """获取指定对话下所有未完成的 Q1 (重要且紧急) 指令，用于注入上下文"""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT content
                FROM memory_matrix
                WHERE thread_id = ? AND quadrant = 'Q1' AND status = 'active'
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()
        return [self._decrypt(row[0]) for row in rows]

    # ==================== 滚动摘要层 ====================
    def bump_turn_counter(self, thread_id: str) -> int:
        """每完成一轮对话调用一次，返回自上次摘要以来累计的轮数。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_turn_counters (thread_id, turns_since_summary, total_turns)
                VALUES (?, 1, 1)
                ON CONFLICT(thread_id) DO UPDATE SET
                    turns_since_summary = turns_since_summary + 1,
                    total_turns = total_turns + 1
                """,
                (thread_id,),
            )
            conn.commit()
            cur = conn.execute(
                "SELECT turns_since_summary FROM memory_turn_counters WHERE thread_id = ?",
                (thread_id,),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def reset_turn_counter(self, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE memory_turn_counters SET turns_since_summary = 0 WHERE thread_id = ?",
                (thread_id,),
            )
            conn.commit()

    def save_summary(
        self,
        thread_id: str,
        summary: str,
        range_start_ts: str,
        range_end_ts: str,
        turn_count: int,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO memory_summaries
                    (thread_id, range_start_ts, range_end_ts, turn_count, summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (thread_id, range_start_ts, range_end_ts, turn_count, summary),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_recent_summaries(self, thread_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT summary, range_start_ts, range_end_ts, turn_count, created_at
                FROM memory_summaries
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "summary": row[0],
                "range_start_ts": row[1],
                "range_end_ts": row[2],
                "turn_count": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    # ==================== 细粒度记忆碎片 ====================
    def save_fragment(
        self,
        thread_id: str,
        content: str,
        fragment_type: str,
        source_memory_id: Optional[int] = None,
        persona: str = "",
    ) -> int:
        stored_content = self._encrypt(content)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO memory_fragments
                    (thread_id, source_memory_id, fragment_type, content, persona)
                VALUES (?, ?, ?, ?, ?)
                """,
                (thread_id, source_memory_id, fragment_type, stored_content, persona or ""),
            )
            conn.commit()
            return int(cur.lastrowid)

    def save_fragment_embedding(self, fragment_id: int, embedding_blob: bytes) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_fragment_embeddings (fragment_id, embedding)
                VALUES (?, ?)
                ON CONFLICT(fragment_id) DO UPDATE SET embedding = excluded.embedding
                """,
                (fragment_id, embedding_blob),
            )
            conn.commit()

    def get_fragments(
        self,
        thread_id: str,
        fragment_type: Optional[str] = None,
        limit: int = 50,
        *,
        persona: Optional[str] = None,
        shared_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """persona=None 且 shared_only=False：返回该 thread 全部碎片（兼容旧行为）。
        persona='bina'：仅该人设私忆；shared_only=True：仅 persona='' 的共享碎片。
        """
        sql = (
            "SELECT id, fragment_type, content, created_at, persona "
            "FROM memory_fragments WHERE thread_id = ?"
        )
        params: List[Any] = [thread_id]
        if fragment_type:
            sql += " AND fragment_type = ?"
            params.append(fragment_type)
        if shared_only:
            sql += " AND (persona IS NULL OR persona = '')"
        elif persona is not None:
            sql += " AND persona = ?"
            params.append(persona)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "fragment_type": row[1],
                "content": self._decrypt(row[2]),
                "created_at": row[3],
                "persona": row[4] or "",
            }
            for row in rows
        ]

    # ==================== 内阁吵架层 M1 ====================
    def get_debate_status(self, thread_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM cabinet_debate_state WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return str(row[0]) if row else "closed"

    def open_debate(self, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cabinet_debate_state (thread_id, status, opened_at, closed_at)
                VALUES (?, 'open', CURRENT_TIMESTAMP, NULL)
                ON CONFLICT(thread_id) DO UPDATE SET
                    status = 'open',
                    opened_at = CURRENT_TIMESTAMP,
                    closed_at = NULL
                """,
                (thread_id,),
            )
            conn.commit()

    def close_debate(self, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cabinet_debate_state (thread_id, status, closed_at)
                VALUES (?, 'closed', CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    status = 'closed',
                    closed_at = CURRENT_TIMESTAMP
                """,
                (thread_id,),
            )
            conn.commit()

    def append_debate_turn(
        self, thread_id: str, speaker: str, role: str, content: str
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO cabinet_debate_turns (thread_id, speaker, role, content)
                VALUES (?, ?, ?, ?)
                """,
                (thread_id, speaker, role, content),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_debate_turns(self, thread_id: str, limit: int = 30) -> List[Dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT speaker, role, content, created_at
                FROM cabinet_debate_turns
                WHERE thread_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (thread_id, max(limit, 1)),
            ).fetchall()
        turns: List[Dict[str, str]] = []
        for speaker, role, content, created_at in reversed(rows):
            turns.append(
                {
                    "speaker": str(speaker or ""),
                    "role": str(role or ""),
                    "content": str(content or ""),
                    "ts": str(created_at or ""),
                }
            )
        return turns

    def clear_debate_turns(self, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM cabinet_debate_turns WHERE thread_id = ?",
                (thread_id,),
            )
            conn.commit()

    # ==================== 内阁共识层 M3 ====================
    def save_consensus(
        self,
        thread_id: str,
        summary: str,
        conclusions: str = "",
        unresolved: str = "",
        action_items: str = "",
        source_turn_count: int = 0,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO cabinet_consensus
                    (thread_id, summary, conclusions, unresolved, action_items, source_turn_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    summary,
                    conclusions,
                    unresolved,
                    action_items,
                    source_turn_count,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_recent_consensus(self, thread_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT summary, conclusions, unresolved, action_items,
                       source_turn_count, created_at
                FROM cabinet_consensus
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        return [
            {
                "summary": row[0],
                "conclusions": row[1],
                "unresolved": row[2],
                "action_items": row[3],
                "source_turn_count": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    # ==================== 实体聚合 ====================
    def upsert_entity(self, thread_id: str, name: str, entity_type: str) -> int:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO entities (thread_id, name, entity_type)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id, name, entity_type) DO NOTHING
                """,
                (thread_id, name, entity_type),
            )
            conn.commit()
            cur = conn.execute(
                "SELECT id FROM entities WHERE thread_id = ? AND name = ? AND entity_type = ?",
                (thread_id, name, entity_type),
            )
            row = cur.fetchone()
        return int(row[0])

    def link_entity(self, entity_id: int, memory_id: int, source: str = "matrix") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO entity_memory_links (entity_id, memory_id, source)
                VALUES (?, ?, ?)
                ON CONFLICT(entity_id, memory_id, source) DO NOTHING
                """,
                (entity_id, memory_id, source),
            )
            conn.commit()

    def find_entity_memory_ids(self, thread_id: Optional[str], query: str, top_n: int = 10) -> List[int]:
        """极简实体召回：query 里出现了哪些已登记的实体名，就把对应记忆 id 都拿出来。

        不引入图数据库/NER 模型，实体来源由 `memory/enrichment.py` 的轻量抽取
        写入 `entities` 表；这里只做字符串包含匹配 + 关联记忆去重。
        """
        sql = "SELECT id, name FROM entities"
        params: List[Any] = []
        if thread_id is not None:
            sql += " WHERE thread_id = ?"
            params.append(thread_id)
        with self._connect() as conn:
            entity_rows = conn.execute(sql, params).fetchall()

            matched_ids = [eid for eid, name in entity_rows if name and name in query]
            if not matched_ids:
                return []

            placeholders = ",".join("?" for _ in matched_ids)
            link_rows = conn.execute(
                f"""
                SELECT memory_id FROM entity_memory_links
                WHERE entity_id IN ({placeholders}) AND source = 'matrix'
                LIMIT ?
                """,
                (*matched_ids, top_n),
            ).fetchall()
        return [row[0] for row in link_rows]

    def decrypt_content(self, stored: str) -> str:
        """暴露给 hybrid_engine 等外部模块的解密入口，避免各处重复实现。"""
        return self._decrypt(stored)

    # ==================== 会话 turn 持久化 ====================
    def append_chat_turn(self, thread_id: str, user_text: str, assistant_text: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO chat_turns (thread_id, user_text, assistant_text)
                VALUES (?, ?, ?)
                """,
                (thread_id, user_text, assistant_text),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_chat_turns(self, thread_id: str, limit: int = 50) -> List[Dict[str, str]]:
        """返回旧→新的 turn 列表，字段与 SessionCache.get_recent_turns 对齐。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT user_text, assistant_text, created_at
                FROM chat_turns
                WHERE thread_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (thread_id, max(limit, 1)),
            )
            rows = cur.fetchall()
        turns: List[Dict[str, str]] = []
        for user_text, assistant_text, created_at in reversed(rows):
            turns.append(
                {
                    "user": str(user_text or ""),
                    "assistant": str(assistant_text or ""),
                    "ts": str(created_at or ""),
                }
            )
        return turns

    def format_chat_history(self, thread_id: str, limit: int = 5) -> List[str]:
        """与 SessionCache.format_recent_history 同形，供 Redis 空时回退。"""
        turns = self.get_chat_turns(thread_id, limit=limit)
        lines: List[str] = []
        for idx, turn in enumerate(turns, start=1):
            lines.append(
                f"Round {idx}\nUser: {turn['user']}\nAssistant: {turn['assistant']}"
            )
        return lines
