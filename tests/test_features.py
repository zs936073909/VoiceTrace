"""扩展测试：验证新功能模块的导入和基本功能"""
import json
import tempfile
import wave
import struct
from pathlib import Path


def test_import_follow_read_view():
    from voicetrace.ui.follow_read_view import FollowReadView
    assert FollowReadView is not None


def test_import_progress_view():
    from voicetrace.ui.progress_view import ProgressView, CalendarWidget
    assert ProgressView is not None
    assert CalendarWidget is not None


def test_import_export_pdf():
    from voicetrace.utils.export import export_pdf
    assert export_pdf is not None


def test_import_main_window():
    from voicetrace.ui.main_window import MainWindow
    assert MainWindow is not None


def test_import_training_session_model():
    from voicetrace.data.models import TrainingSession, CustomStandard
    assert TrainingSession is not None
    assert CustomStandard is not None


def test_comparator_report_fields():
    from voicetrace.core.comparator import Comparator
    c = Comparator()
    report = c.generate_report(
        current_rate=260, baseline_rate=250,
        current_pauses=3, baseline_pauses=5,
        similarity_score=0.85
    )
    assert "baseline_rate" in report
    assert "current_rate" in report
    assert report["rate_delta"] == 10
    assert report["pause_delta"] == -2
    assert len(report["improvements"]) >= 2  # 语速提升 + 卡顿减少 + 相似度高


def test_database_training_session():
    """测试训练打卡 CRUD"""
    from voicetrace.data.database import Database
    from voicetrace.data.models import TrainingSession

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        sid = db.create_training_session(TrainingSession(
            duration=60.0,
            notes="测试打卡"
        ))
        assert sid > 0
        sessions = db.list_training_sessions(10)
        assert len(sessions) == 1
        assert sessions[0].duration == 60.0
        stats = db.get_training_stats()
        assert stats["total_sessions"] == 1
        assert stats["total_duration"] == 60.0
        db.close()


def test_database_custom_standard():
    """测试自定义标准 CRUD"""
    from voicetrace.data.database import Database
    from voicetrace.data.models import CustomStandard

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        sid = db.create_custom_standard(CustomStandard(
            name="测试标准",
            language="chinese",
            category="custom",
            rate_min=200,
            rate_max=260,
            unit="CPM"
        ))
        assert sid > 0
        stds = db.list_custom_standards()
        assert len(stds) == 1
        assert stds[0].name == "测试标准"
        assert db.delete_custom_standard(sid)
        assert len(db.list_custom_standards()) == 0
        db.close()


def test_analyzer_split_sentences():
    """测试句子切分"""
    from voicetrace.core.analyzer import Analyzer
    a = Analyzer()
    s1 = a.split_sentences("你好世界。今天天气不错！", "chinese")
    assert len(s1) == 2
    s2 = a.split_sentences("Hello world. How are you?", "english")
    assert len(s2) == 2


def test_export_pdf():
    """测试 PDF 导出"""
    from voicetrace.utils.export import export_pdf

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "test.pdf"
        data = [
            {"id": 1, "title": "测试稿件", "rate": 260},
            {"id": 2, "title": "另一个", "rate": 280},
        ]
        ok = export_pdf(data, out, title="测试报告")
        assert ok
        assert out.exists()
        assert out.stat().st_size > 0


def test_export_csv_json():
    """测试 CSV/JSON 导出"""
    from voicetrace.utils.export import export_csv, export_json

    data = [{"id": 1, "name": "测试"}]
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "test.csv"
        json_path = Path(tmp) / "test.json"
        assert export_csv(data, csv_path)
        assert csv_path.exists()
        assert export_json(data, json_path)
        assert json_path.exists()
        # 验证 JSON 内容
        with open(json_path, encoding='utf-8') as f:
            loaded = json.load(f)
        assert loaded == data


def test_analyzer_with_wav():
    """端到端测试：生成 WAV → 分析"""
    import numpy as np
    from voicetrace.core.analyzer import Analyzer

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "test.wav"
        # 生成 2 秒 440Hz 正弦波
        sr = 16000
        t = np.linspace(0, 2, sr * 2, False)
        y = (np.sin(2 * np.pi * 440 * t) * 0.3 * 32767).astype(np.int16)
        with wave.open(str(wav_path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(y.tobytes())

        a = Analyzer()
        result = a.analyze(str(wav_path), "你好世界。", "chinese")
        assert "speech_rate" in result
        assert "mfcc_features" in result
        assert "waveform" in result
        assert "duration" in result
        assert result["duration"] > 1.5
