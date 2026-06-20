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


# ---- 台风训练功能测试 ----

def test_posture_record_model():
    """测试 PostureRecord 数据模型"""
    from voicetrace.data.models import PostureRecord, ScriptTemplate
    r = PostureRecord(
        duration=60.0,
        eye_contact_score=85.0,
        expression_score=70.0,
        overall_score=80.0
    )
    assert r.duration == 60.0
    assert r.eye_contact_score == 85.0
    t = ScriptTemplate(name="测试模板", category="news_broadcast", language="chinese")
    assert t.name == "测试模板"


def test_database_posture_record():
    """测试台风训练记录 CRUD"""
    from voicetrace.data.database import Database
    from voicetrace.data.models import PostureRecord

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        rid = db.create_posture_record(PostureRecord(
            duration=120.0,
            eye_contact_score=88.0,
            expression_score=75.0,
            head_pose_score=90.0,
            posture_score=82.0,
            gesture_score=70.0,
            stability_score=85.0,
            overall_score=81.7,
            details_json='{"test": true}'
        ))
        assert rid > 0
        records = db.list_posture_records()
        assert len(records) == 1
        assert records[0].overall_score == 81.7
        assert records[0].eye_contact_score == 88.0
        db.close()


def test_script_writer_templates():
    """测试文案模板加载"""
    from voicetrace.core.script_writer import ScriptWriter
    w = ScriptWriter()
    templates = w.load_templates()
    assert len(templates) > 0
    # 按类别筛选
    news = w.get_templates_by_category("news_broadcast", "chinese")
    assert len(news) >= 2
    # 获取单个模板
    t = w.get_template("新闻播报-时政")
    assert t is not None
    assert "structure" in t


def test_script_writer_generate():
    """测试模板文案生成"""
    from voicetrace.core.script_writer import ScriptWriter
    w = ScriptWriter()
    result = w.generate_from_template("新闻播报-时政", {
        "date": "2026年1月1日",
        "program_name": "新闻联播",
        "topic": "测试主题",
        "lead_sentence": "这是导语。",
        "detail_1": "细节一",
        "detail_2": "细节二",
        "detail_3": "细节三"
    })
    assert result.success
    assert "新闻联播" in result.content
    assert "测试主题" in result.content
    assert result.source == "template"


def test_script_writer_prompt():
    """测试 AI 提示词构建"""
    from voicetrace.core.script_writer import ScriptWriter
    w = ScriptWriter()
    prompt = w.build_ai_prompt(
        category="news_broadcast",
        topic="教育改革",
        language="chinese",
        duration="2-3分钟"
    )
    assert "新闻播报" in prompt
    assert "教育改革" in prompt
    assert "中文" in prompt


def test_posture_analyzer_import():
    """测试面部分析器导入（不依赖摄像头）"""
    from voicetrace.core.posture_analyzer import (
        PostureAnalyzer, FrameAnalysis, SessionSummary,
        is_mediapipe_available
    )
    assert PostureAnalyzer is not None
    assert FrameAnalysis is not None
    assert SessionSummary is not None
    # MediaPipe 应该已安装
    assert is_mediapipe_available()


def test_pose_analyzer_modes():
    """测试身体姿态分析器的坐姿/站姿模式"""
    from voicetrace.core.pose_analyzer import PoseAnalyzer, PoseSessionSummary
    # 坐姿模式
    pa_sitting = PoseAnalyzer(mode="sitting")
    assert pa_sitting.mode == "sitting"
    # 站姿模式
    pa_standing = PoseAnalyzer(mode="standing")
    assert pa_standing.mode == "standing"
    # 切换模式
    pa_sitting.set_mode("standing")
    assert pa_sitting.mode == "standing"


def test_radar_chart_widget():
    """测试雷达图组件"""
    import os
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from voicetrace.ui.radar_chart import RadarChart
    chart = RadarChart()
    chart.set_data(
        ["眼神", "表情", "姿态", "手势", "稳定", "头部"],
        [80, 70, 90, 60, 85, 75]
    )
    chart.set_theme("dark")
    chart.set_theme("light")
    assert chart._labels == ["眼神", "表情", "姿态", "手势", "稳定", "头部"]


def test_posture_view_import():
    """测试台风训练视图导入"""
    import os
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from voicetrace.ui.posture_view import PostureView
    from voicetrace.ui.script_writer_view import ScriptWriterView
    assert PostureView is not None
    assert ScriptWriterView is not None


def test_camera_view_import():
    """测试摄像头视图导入"""
    import os
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from voicetrace.ui.camera_view import CameraView
    cv = CameraView()
    assert cv.is_running() is False
