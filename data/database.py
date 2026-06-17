import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from voicetrace.data.models import (
    Script, Recording, Stumble, Analysis, Comparison,
    TrainingSession, CustomStandard
)


class Database:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()
        self._migrate()
        self._create_indexes()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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
            CREATE TABLE IF NOT EXISTS training_sessions (
                id INTEGER PRIMARY KEY,
                script_id INTEGER,
                recording_id INTEGER,
                duration REAL DEFAULT 0,
                notes TEXT,
                date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE SET NULL,
                FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE SET NULL
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
        """)
        self.conn.commit()

    def _migrate(self):
        """Add columns if they don't exist (for existing databases)."""
        try:
            self.conn.execute("ALTER TABLE analyses ADD COLUMN sentence_analysis_json TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def _create_indexes(self):
        self.conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_recordings_script_id ON recordings(script_id);
            CREATE INDEX IF NOT EXISTS idx_stumbles_recording_id ON stumbles(recording_id);
            CREATE INDEX IF NOT EXISTS idx_analyses_recording_id ON analyses(recording_id);
            CREATE INDEX IF NOT EXISTS idx_comparisons_recording_id ON comparisons(recording_id);
            CREATE INDEX IF NOT EXISTS idx_comparisons_baseline_id ON comparisons(baseline_id);
            CREATE INDEX IF NOT EXISTS idx_training_date ON training_sessions(date);
        """)
        self.conn.commit()

    # ---- Script CRUD ----

    def create_script(self, script: Script) -> int:
        cursor = self.conn.execute(
            "INSERT INTO scripts (title, category, language, content) VALUES (?, ?, ?, ?)",
            (script.title, script.category, script.language, script.content)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_script(self, script_id: int) -> Optional[Script]:
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
        cursor = self.conn.execute(
            "UPDATE scripts SET title=?, category=?, language=?, content=? WHERE id=?",
            (script.title, script.category, script.language, script.content, script.id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_script(self, script_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM scripts WHERE id=?", (script_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- Recording CRUD ----

    def create_recording(self, recording: Recording) -> int:
        cursor = self.conn.execute(
            "INSERT INTO recordings (script_id, file_path, duration) VALUES (?, ?, ?)",
            (recording.script_id, recording.file_path, recording.duration)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_recording(self, recording_id: int) -> Optional[Recording]:
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
        cursor = self.conn.execute("DELETE FROM recordings WHERE id=?", (recording_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- Stumble CRUD ----

    def create_stumble(self, stumble: Stumble) -> int:
        cursor = self.conn.execute(
            "INSERT INTO stumbles (recording_id, stumble_time, label) VALUES (?, ?, ?)",
            (stumble.recording_id, stumble.stumble_time, stumble.label)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_stumbles(self, recording_id: int) -> List[Stumble]:
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
        cursor = self.conn.execute(
            "DELETE FROM stumbles WHERE recording_id=?", (recording_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    # ---- Analysis CRUD ----

    def create_analysis(self, analysis: Analysis) -> int:
        cursor = self.conn.execute(
            """INSERT INTO analyses (recording_id, speech_rate, pause_count,
               total_pause_duration, rms_energy, mfcc_features, spectral_features,
               sentence_analysis_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (analysis.recording_id, analysis.speech_rate, analysis.pause_count,
             analysis.total_pause_duration, analysis.rms_energy,
             analysis.mfcc_features, analysis.spectral_features,
             analysis.sentence_analysis_json)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_latest_analysis(self, recording_id: int) -> Optional[Analysis]:
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
                sentence_analysis_json=row["sentence_analysis_json"]
            )
        return None

    def list_analyses(self, recording_id: int) -> List[Analysis]:
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
                sentence_analysis_json=r["sentence_analysis_json"]
            )
            for r in rows
        ]

    # ---- Comparison CRUD ----

    def create_comparison(self, comparison: Comparison) -> int:
        cursor = self.conn.execute(
            """INSERT INTO comparisons (recording_id, baseline_id, similarity_score, differences_json)
               VALUES (?, ?, ?, ?)""",
            (comparison.recording_id, comparison.baseline_id,
             comparison.similarity_score, comparison.differences_json)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_latest_comparison(self, recording_id: int) -> Optional[Comparison]:
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

    # ---- TrainingSession CRUD ----

    def create_training_session(self, session: TrainingSession) -> int:
        if session.date is None:
            session.date = datetime.now().strftime("%Y-%m-%d")
        cursor = self.conn.execute(
            "INSERT INTO training_sessions (script_id, recording_id, duration, notes, date) VALUES (?, ?, ?, ?, ?)",
            (session.script_id, session.recording_id, session.duration, session.notes, session.date)
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_training_sessions(self, limit: int = 100) -> List[TrainingSession]:
        rows = self.conn.execute(
            "SELECT * FROM training_sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            TrainingSession(
                id=r["id"], script_id=r["script_id"], recording_id=r["recording_id"],
                duration=r["duration"], notes=r["notes"], date=r["date"]
            )
            for r in rows
        ]

    def get_training_dates(self) -> List[str]:
        """返回所有打卡日期列表 (YYYY-MM-DD)"""
        rows = self.conn.execute("SELECT DISTINCT date FROM training_sessions ORDER BY date DESC").fetchall()
        return [r["date"] for r in rows]

    def get_training_stats(self) -> dict:
        """获取训练统计"""
        total = self.conn.execute("SELECT COUNT(*) as c FROM training_sessions").fetchone()["c"]
        total_duration = self.conn.execute("SELECT COALESCE(SUM(duration), 0) as s FROM training_sessions").fetchone()["s"]
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = self.conn.execute(
            "SELECT COUNT(*) as c FROM training_sessions WHERE date = ?", (today,)
        ).fetchone()["c"]
        # 连续打卡天数
        dates = self.get_training_dates()
        streak = 0
        check_date = datetime.now().strftime("%Y-%m-%d")
        for d in dates:
            if d == check_date:
                streak += 1
                # 前一天
                from datetime import timedelta
                check_date = (datetime.strptime(check_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            elif d < check_date:
                break
        return {
            "total_sessions": total,
            "total_duration": total_duration,
            "today_count": today_count,
            "streak": streak
        }

    # ---- CustomStandard CRUD ----

    def create_custom_standard(self, std: CustomStandard) -> int:
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
        cursor = self.conn.execute("DELETE FROM custom_standards WHERE id=?", (std_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def close(self):
        self.conn.close()
