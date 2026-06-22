import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Union
from contextlib import contextmanager

from voicetrace.data.models import (
    Script, Recording, Stumble, Analysis, Comparison,
    CustomStandard, PostureRecord, ScriptTemplate,
    MemoryCard, ReviewLog
)

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Union[str, Path]):
        self.db_path = Path(db_path)
        try:
            self.conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self._create_tables()
            self._migrate()
            self._create_indexes()
        except sqlite3.Error as exc:
            logger.error(f"数据库连接失败 {self.db_path}: {exc}")
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @contextmanager
    def transaction(self):
        """事务上下文管理器"""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                language TEXT NOT NULL,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY,
                script_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                duration REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS stumbles (
                id INTEGER PRIMARY KEY,
                recording_id INTEGER NOT NULL,
                stumble_time REAL NOT NULL,
                label TEXT,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY,
                recording_id INTEGER NOT NULL,
                speech_rate REAL,
                pause_count INTEGER,
                total_pause_duration REAL,
                rms_energy REAL,
                mfcc_features BLOB,
                spectral_features BLOB,
                sentence_analysis_json TEXT,
                prosody_json TEXT,
                alignment_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS comparisons (
                id INTEGER PRIMARY KEY,
                recording_id INTEGER NOT NULL,
                baseline_id INTEGER NOT NULL,
                similarity_score REAL,
                differences_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE,
                FOREIGN KEY (baseline_id) REFERENCES recordings(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS custom_standards (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                language TEXT NOT NULL,
                category TEXT NOT NULL,
                rate_min INTEGER NOT NULL,
                rate_max INTEGER NOT NULL,
                unit TEXT DEFAULT 'CPM'
            );
            CREATE TABLE IF NOT EXISTS posture_records (
                id INTEGER PRIMARY KEY,
                recording_id INTEGER,
                duration REAL DEFAULT 0,
                eye_contact_score REAL,
                expression_score REAL,
                head_pose_score REAL,
                posture_score REAL,
                gesture_score REAL,
                stability_score REAL,
                overall_score REAL,
                details_json TEXT,
                video_path TEXT,
                notes TEXT,
                date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS script_templates (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                language TEXT NOT NULL,
                structure_json TEXT,
                tips TEXT
            );
            CREATE TABLE IF NOT EXISTS memory_cards (
                id INTEGER PRIMARY KEY,
                card_id TEXT NOT NULL UNIQUE,
                script_id INTEGER,
                segment_index INTEGER DEFAULT 0,
                front TEXT DEFAULT '',
                back TEXT DEFAULT '',
                hint TEXT DEFAULT '',
                scenario TEXT DEFAULT 'speech',
                tags_json TEXT,
                state INTEGER DEFAULT 0,
                step INTEGER DEFAULT 0,
                stability REAL DEFAULT 0.0,
                difficulty REAL DEFAULT 0.0,
                last_review REAL,
                reps INTEGER DEFAULT 0,
                lapses INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS review_logs (
                id INTEGER PRIMARY KEY,
                card_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                review_duration REAL DEFAULT 0.0,
                reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                state_before INTEGER DEFAULT 0,
                state_after INTEGER DEFAULT 0,
                stability_before REAL DEFAULT 0.0,
                stability_after REAL DEFAULT 0.0,
                retrievability REAL DEFAULT 0.0,
                FOREIGN KEY (card_id) REFERENCES memory_cards(card_id) ON DELETE CASCADE
            );
        """)
        self.conn.commit()

    def _migrate(self):
        """Add columns if they don't exist (for existing databases)."""
        columns_to_add = [
            ("analyses", "sentence_analysis_json", "TEXT"),
            ("analyses", "prosody_json", "TEXT"),
            ("analyses", "alignment_json", "TEXT"),
        ]
        for table, column, col_type in columns_to_add:
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                self.conn.commit()
                logger.info(f"数据库迁移：添加列 {table}.{column}")
            except sqlite3.OperationalError:
                # 列已存在
                pass
            except Exception as exc:
                logger.warning(f"数据库迁移失败 {table}.{column}: {exc}")

    def _create_indexes(self):
        self.conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_recordings_script_id ON recordings(script_id);
            CREATE INDEX IF NOT EXISTS idx_stumbles_recording_id ON stumbles(recording_id);
            CREATE INDEX IF NOT EXISTS idx_analyses_recording_id ON analyses(recording_id);
            CREATE INDEX IF NOT EXISTS idx_comparisons_recording_id ON comparisons(recording_id);
            CREATE INDEX IF NOT EXISTS idx_comparisons_baseline_id ON comparisons(baseline_id);
            CREATE INDEX IF NOT EXISTS idx_posture_date ON posture_records(date);
            CREATE INDEX IF NOT EXISTS idx_posture_recording_id ON posture_records(recording_id);
            CREATE INDEX IF NOT EXISTS idx_memory_cards_card_id ON memory_cards(card_id);
            CREATE INDEX IF NOT EXISTS idx_memory_cards_script_id ON memory_cards(script_id);
            CREATE INDEX IF NOT EXISTS idx_memory_cards_state ON memory_cards(state);
            CREATE INDEX IF NOT EXISTS idx_memory_cards_last_review ON memory_cards(last_review);
            CREATE INDEX IF NOT EXISTS idx_review_logs_card_id ON review_logs(card_id);
            CREATE INDEX IF NOT EXISTS idx_review_logs_reviewed_at ON review_logs(reviewed_at);
        """)
        self.conn.commit()

    # ---- Script CRUD ----

    def create_script(self, script: Script) -> int:
        if not script.title:
            raise ValueError("稿件标题不能为空")
        cursor = self.conn.execute(
            "INSERT INTO scripts (title, category, language, content) VALUES (?, ?, ?, ?)",
            (script.title, script.category, script.language, script.content)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_script(self, script_id: int) -> Optional[Script]:
        if script_id is None:
            return None
        row = self.conn.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()
        if row:
            return Script(
                id=row["id"], title=row["title"], category=row["category"],
                language=row["language"], content=row["content"]
            )
        return None

    def list_scripts(self) -> List[Script]:
        rows = self.conn.execute("SELECT * FROM scripts ORDER BY created_at DESC").fetchall()
        return [
            Script(id=r["id"], title=r["title"], category=r["category"],
                   language=r["language"], content=r["content"])
            for r in rows
        ]

    def update_script(self, script: Script) -> bool:
        if script.id is None:
            return False
        if not script.title:
            return False
        cursor = self.conn.execute(
            "UPDATE scripts SET title=?, category=?, language=?, content=? WHERE id=?",
            (script.title, script.category, script.language, script.content, script.id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_script(self, script_id: int) -> bool:
        if script_id is None:
            return False
        cursor = self.conn.execute("DELETE FROM scripts WHERE id=?", (script_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- Recording CRUD ----

    def create_recording(self, recording: Recording) -> int:
        if recording.script_id is None:
            raise ValueError("录音必须关联稿件")
        if not recording.file_path:
            raise ValueError("录音文件路径不能为空")
        cursor = self.conn.execute(
            "INSERT INTO recordings (script_id, file_path, duration) VALUES (?, ?, ?)",
            (recording.script_id, recording.file_path, recording.duration)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_recording(self, recording_id: int) -> Optional[Recording]:
        if recording_id is None:
            return None
        row = self.conn.execute(
            "SELECT * FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
        if row:
            return Recording(
                id=row["id"], script_id=row["script_id"],
                file_path=row["file_path"], duration=row["duration"]
            )
        return None

    def list_recordings(self, script_id: Optional[int] = None) -> List[Recording]:
        if script_id is not None:
            rows = self.conn.execute(
                "SELECT * FROM recordings WHERE script_id = ? ORDER BY created_at DESC",
                (script_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM recordings ORDER BY created_at DESC"
            ).fetchall()
        return [
            Recording(id=r["id"], script_id=r["script_id"],
                      file_path=r["file_path"], duration=r["duration"])
            for r in rows
        ]

    def delete_recording(self, recording_id: int) -> bool:
        if recording_id is None:
            return False
        cursor = self.conn.execute("DELETE FROM recordings WHERE id=?", (recording_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- Stumble CRUD ----

    def create_stumble(self, stumble: Stumble) -> int:
        if stumble.recording_id is None:
            raise ValueError("卡顿必须关联录音")
        cursor = self.conn.execute(
            "INSERT INTO stumbles (recording_id, stumble_time, label) VALUES (?, ?, ?)",
            (stumble.recording_id, stumble.stumble_time, stumble.label)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_stumbles(self, recording_id: int) -> List[Stumble]:
        if recording_id is None:
            return []
        rows = self.conn.execute(
            "SELECT * FROM stumbles WHERE recording_id = ? ORDER BY stumble_time",
            (recording_id,)
        ).fetchall()
        return [
            Stumble(id=r["id"], recording_id=r["recording_id"],
                    stumble_time=r["stumble_time"], label=r["label"])
            for r in rows
        ]

    def delete_stumbles(self, recording_id: int) -> int:
        if recording_id is None:
            return 0
        cursor = self.conn.execute(
            "DELETE FROM stumbles WHERE recording_id=?", (recording_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    # ---- Analysis CRUD ----

    def create_analysis(self, analysis: Analysis) -> int:
        if analysis.recording_id is None:
            raise ValueError("分析必须关联录音")
        cursor = self.conn.execute(
            """INSERT INTO analyses (recording_id, speech_rate, pause_count,
               total_pause_duration, rms_energy, mfcc_features, spectral_features,
               sentence_analysis_json, prosody_json, alignment_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (analysis.recording_id, analysis.speech_rate, analysis.pause_count,
             analysis.total_pause_duration, analysis.rms_energy,
             analysis.mfcc_features, analysis.spectral_features,
             analysis.sentence_analysis_json, analysis.prosody_json,
             analysis.alignment_json)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_latest_analysis(self, recording_id: int) -> Optional[Analysis]:
        if recording_id is None:
            return None
        row = self.conn.execute(
            "SELECT * FROM analyses WHERE recording_id = ? ORDER BY created_at DESC LIMIT 1",
            (recording_id,)
        ).fetchone()
        if row:
            return Analysis(
                id=row["id"], recording_id=row["recording_id"],
                speech_rate=row["speech_rate"], pause_count=row["pause_count"],
                total_pause_duration=row["total_pause_duration"],
                rms_energy=row["rms_energy"],
                mfcc_features=row["mfcc_features"],
                spectral_features=row["spectral_features"],
                sentence_analysis_json=row["sentence_analysis_json"],
                prosody_json=row["prosody_json"],
                alignment_json=row["alignment_json"]
            )
        return None

    def list_analyses(self, recording_id: int) -> List[Analysis]:
        if recording_id is None:
            return []
        rows = self.conn.execute(
            "SELECT * FROM analyses WHERE recording_id = ? ORDER BY created_at DESC",
            (recording_id,)
        ).fetchall()
        return [
            Analysis(
                id=r["id"], recording_id=r["recording_id"],
                speech_rate=r["speech_rate"], pause_count=r["pause_count"],
                total_pause_duration=r["total_pause_duration"],
                rms_energy=r["rms_energy"],
                mfcc_features=r["mfcc_features"],
                spectral_features=r["spectral_features"],
                sentence_analysis_json=r["sentence_analysis_json"],
                prosody_json=r["prosody_json"],
                alignment_json=r["alignment_json"]
            )
            for r in rows
        ]

    # ---- Comparison CRUD ----

    def create_comparison(self, comparison: Comparison) -> int:
        if comparison.recording_id is None or comparison.baseline_id is None:
            raise ValueError("对比必须关联两条录音")
        cursor = self.conn.execute(
            """INSERT INTO comparisons (recording_id, baseline_id, similarity_score, differences_json)
               VALUES (?, ?, ?, ?)""",
            (comparison.recording_id, comparison.baseline_id,
             comparison.similarity_score, comparison.differences_json)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_latest_comparison(self, recording_id: int) -> Optional[Comparison]:
        if recording_id is None:
            return None
        row = self.conn.execute(
            "SELECT * FROM comparisons WHERE recording_id = ? ORDER BY created_at DESC LIMIT 1",
            (recording_id,)
        ).fetchone()
        if row:
            return Comparison(
                id=row["id"], recording_id=row["recording_id"],
                baseline_id=row["baseline_id"],
                similarity_score=row["similarity_score"],
                differences_json=row["differences_json"]
            )
        return None

    # ---- CustomStandard CRUD ----

    def create_custom_standard(self, std: CustomStandard) -> int:
        if not std.name:
            raise ValueError("标准名称不能为空")
        if std.rate_min is None or std.rate_max is None or std.rate_min > std.rate_max:
            raise ValueError("语速范围无效")
        cursor = self.conn.execute(
            "INSERT INTO custom_standards (name, language, category, rate_min, rate_max, unit) VALUES (?, ?, ?, ?, ?, ?)",
            (std.name, std.language, std.category, std.rate_min, std.rate_max, std.unit)
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_custom_standards(self) -> List[CustomStandard]:
        rows = self.conn.execute("SELECT * FROM custom_standards ORDER BY name").fetchall()
        return [
            CustomStandard(
                id=r["id"], name=r["name"], language=r["language"],
                category=r["category"], rate_min=r["rate_min"],
                rate_max=r["rate_max"], unit=r["unit"]
            )
            for r in rows
        ]

    def delete_custom_standard(self, std_id: int) -> bool:
        if std_id is None:
            return False
        cursor = self.conn.execute("DELETE FROM custom_standards WHERE id=?", (std_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- PostureRecord CRUD ----

    def create_posture_record(self, record: PostureRecord) -> int:
        if record.date is None:
            record.date = datetime.now().strftime("%Y-%m-%d")
        cursor = self.conn.execute(
            """INSERT INTO posture_records
               (recording_id, duration, eye_contact_score, expression_score, head_pose_score,
                posture_score, gesture_score, stability_score, overall_score,
                details_json, video_path, notes, date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record.recording_id, record.duration,
             record.eye_contact_score, record.expression_score, record.head_pose_score,
             record.posture_score, record.gesture_score, record.stability_score,
             record.overall_score, record.details_json, record.video_path,
             record.notes, record.date)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_posture_record(self, record_id: int) -> Optional[PostureRecord]:
        if record_id is None:
            return None
        row = self.conn.execute(
            "SELECT * FROM posture_records WHERE id = ?", (record_id,)
        ).fetchone()
        if row:
            return self._row_to_posture_record(row)
        return None

    def list_posture_records(self, limit: int = 100) -> List[PostureRecord]:
        limit = max(1, min(limit, 10000))
        rows = self.conn.execute(
            "SELECT * FROM posture_records ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_posture_record(r) for r in rows]

    def _row_to_posture_record(self, row) -> PostureRecord:
        return PostureRecord(
            id=row["id"], recording_id=row["recording_id"], duration=row["duration"],
            eye_contact_score=row["eye_contact_score"],
            expression_score=row["expression_score"],
            head_pose_score=row["head_pose_score"],
            posture_score=row["posture_score"],
            gesture_score=row["gesture_score"],
            stability_score=row["stability_score"],
            overall_score=row["overall_score"],
            details_json=row["details_json"],
            video_path=row["video_path"],
            notes=row["notes"], date=row["date"]
        )

    # ---- ScriptTemplate CRUD ----

    def create_script_template(self, tpl: ScriptTemplate) -> int:
        if not tpl.name:
            raise ValueError("模板名称不能为空")
        cursor = self.conn.execute(
            "INSERT INTO script_templates (name, category, language, structure_json, tips) VALUES (?, ?, ?, ?, ?)",
            (tpl.name, tpl.category, tpl.language, tpl.structure_json, tpl.tips)
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_script_templates(self, category: Optional[str] = None) -> List[ScriptTemplate]:
        if category:
            rows = self.conn.execute(
                "SELECT * FROM script_templates WHERE category = ? ORDER BY name", (category,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM script_templates ORDER BY name"
            ).fetchall()
        return [
            ScriptTemplate(
                id=r["id"], name=r["name"], category=r["category"],
                language=r["language"], structure_json=r["structure_json"], tips=r["tips"]
            )
            for r in rows
        ]

    # ---- MemoryCard CRUD ----

    def upsert_memory_card(self, card: MemoryCard) -> int:
        """插入或更新记忆卡片（基于 card_id 唯一）"""
        if not card.card_id:
            raise ValueError("card_id 不能为空")
        cursor = self.conn.execute(
            """INSERT INTO memory_cards
               (card_id, script_id, segment_index, front, back, hint, scenario,
                tags_json, state, step, stability, difficulty, last_review,
                reps, lapses)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(card_id) DO UPDATE SET
                 script_id=excluded.script_id,
                 segment_index=excluded.segment_index,
                 front=excluded.front,
                 back=excluded.back,
                 hint=excluded.hint,
                 scenario=excluded.scenario,
                 tags_json=excluded.tags_json,
                 state=excluded.state,
                 step=excluded.step,
                 stability=excluded.stability,
                 difficulty=excluded.difficulty,
                 last_review=excluded.last_review,
                 reps=excluded.reps,
                 lapses=excluded.lapses""",
            (card.card_id, card.script_id, card.segment_index,
             card.front, card.back, card.hint, card.scenario,
             card.tags_json, card.state, card.step, card.stability,
             card.difficulty, card.last_review, card.reps, card.lapses)
        )
        self.conn.commit()
        # 返回 card_id 对应的行 id
        row = self.conn.execute(
            "SELECT id FROM memory_cards WHERE card_id = ?", (card.card_id,)
        ).fetchone()
        return row["id"] if row else cursor.lastrowid

    def get_memory_card(self, card_id: str) -> Optional[MemoryCard]:
        row = self.conn.execute(
            "SELECT * FROM memory_cards WHERE card_id = ?", (card_id,)
        ).fetchone()
        return self._row_to_memory_card(row) if row else None

    def list_memory_cards(
        self,
        script_id: Optional[int] = None,
        scenario: Optional[str] = None,
    ) -> List[MemoryCard]:
        """列出记忆卡片，可按稿件/场景过滤"""
        sql = "SELECT * FROM memory_cards"
        conditions = []
        params: list = []
        if script_id is not None:
            conditions.append("script_id = ?")
            params.append(script_id)
        if scenario is not None:
            conditions.append("scenario = ?")
            params.append(scenario)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY segment_index ASC"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_memory_card(r) for r in rows]

    def delete_memory_cards_by_script(self, script_id: int) -> int:
        """删除某稿件下的所有记忆卡片（含复习日志）"""
        if script_id is None:
            return 0
        cursor = self.conn.execute(
            "DELETE FROM memory_cards WHERE script_id = ?", (script_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    def _row_to_memory_card(self, row) -> MemoryCard:
        return MemoryCard(
            id=row["id"],
            card_id=row["card_id"],
            script_id=row["script_id"],
            segment_index=row["segment_index"],
            front=row["front"] or "",
            back=row["back"] or "",
            hint=row["hint"] or "",
            scenario=row["scenario"] or "speech",
            tags_json=row["tags_json"],
            state=row["state"] or 0,
            step=row["step"] or 0,
            stability=row["stability"] or 0.0,
            difficulty=row["difficulty"] or 0.0,
            last_review=row["last_review"],
            reps=row["reps"] or 0,
            lapses=row["lapses"] or 0,
            created_at=row["created_at"],
        )

    # ---- ReviewLog CRUD ----

    def create_review_log(self, log: ReviewLog) -> int:
        if not log.card_id:
            raise ValueError("card_id 不能为空")
        cursor = self.conn.execute(
            """INSERT INTO review_logs
               (card_id, rating, review_duration, reviewed_at,
                state_before, state_after, stability_before,
                stability_after, retrievability)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (log.card_id, log.rating, log.review_duration,
             log.reviewed_at or datetime.now().isoformat(),
             log.state_before, log.state_after,
             log.stability_before, log.stability_after,
             log.retrievability)
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_review_logs(
        self,
        card_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[ReviewLog]:
        sql = "SELECT * FROM review_logs"
        params: list = []
        if card_id is not None:
            sql += " WHERE card_id = ?"
            params.append(card_id)
        sql += " ORDER BY reviewed_at DESC LIMIT ?"
        params.append(max(1, min(limit, 10000)))
        rows = self.conn.execute(sql, params).fetchall()
        return [
            ReviewLog(
                id=r["id"],
                card_id=r["card_id"],
                rating=r["rating"],
                review_duration=r["review_duration"] or 0.0,
                reviewed_at=r["reviewed_at"],
                state_before=r["state_before"] or 0,
                state_after=r["state_after"] or 0,
                stability_before=r["stability_before"] or 0.0,
                stability_after=r["stability_after"] or 0.0,
                retrievability=r["retrievability"] or 0.0,
            )
            for r in rows
        ]

    def close(self):
        try:
            self.conn.commit()
        except Exception as exc:
            logger.warning(f"关闭数据库前提交失败: {exc}")
        try:
            self.conn.close()
        except Exception as exc:
            logger.warning(f"关闭数据库失败: {exc}")
