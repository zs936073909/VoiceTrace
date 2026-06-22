import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Union
from contextlib import contextmanager

from voicetrace.data.models import (
    Script, Recording, Stumble, Analysis, Comparison,
    CustomStandard, PostureRecord, ScriptTemplate
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

    def close(self):
        try:
            self.conn.commit()
        except Exception as exc:
            logger.warning(f"关闭数据库前提交失败: {exc}")
        try:
            self.conn.close()
        except Exception as exc:
            logger.warning(f"关闭数据库失败: {exc}")
