"""稳定性与边界情况测试"""
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest


def test_analyzer_missing_file():
    """分析不存在的音频文件应返回错误信息而不是崩溃"""
    from voicetrace.core.analyzer import Analyzer

    analyzer = Analyzer()
    result = analyzer.analyze("/path/that/does/not/exist.wav", "测试文本", "chinese")

    assert "error" in result
    assert result["speech_rate"] == 0.0
    assert result["duration"] == 0.0


def test_analyzer_empty_file():
    """分析空音频文件应返回错误信息而不是崩溃"""
    from voicetrace.core.analyzer import Analyzer

    with tempfile.TemporaryDirectory() as tmp:
        empty_path = Path(tmp) / "empty.wav"
        empty_path.write_bytes(b"")

        analyzer = Analyzer()
        result = analyzer.analyze(str(empty_path), "测试文本", "chinese")

        assert "error" in result


def test_analyzer_nonstandard_sample_rate():
    """分析非 16kHz 采样率音频应能正常处理"""
    from voicetrace.core.analyzer import Analyzer

    sr = 22050
    duration = 1.0
    t = np.linspace(0, duration, int(sr * duration))
    y = 0.1 * np.sin(2 * np.pi * 440 * t)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.wav"
        import soundfile as sf
        sf.write(path, y, sr)

        analyzer = Analyzer()
        result = analyzer.analyze(str(path), "测试文本", "chinese")

        assert "error" not in result
        assert result["duration"] > 0
        assert result["pause_count"] >= 0


def test_analyzer_silence():
    """分析静音音频不应崩溃"""
    from voicetrace.core.analyzer import Analyzer

    sr = 16000
    y = np.zeros(sr, dtype=np.float32)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "silence.wav"
        import soundfile as sf
        sf.write(path, y, sr)

        analyzer = Analyzer()
        result = analyzer.analyze(str(path), "测试文本", "chinese")

        assert "error" not in result
        assert result["duration"] == pytest.approx(1.0, abs=0.01)


def test_analyzer_waveform_empty():
    """空波形数据应返回空列表"""
    from voicetrace.core.analyzer import Analyzer

    analyzer = Analyzer()
    assert analyzer.get_waveform_data(np.array([])) == []


def test_analyzer_spectrogram_empty():
    """空频谱图数据应返回空结构"""
    from voicetrace.core.analyzer import Analyzer

    analyzer = Analyzer()
    result = analyzer.get_spectrogram_data(np.array([]), 16000)
    assert result["data"] == []
    assert result["n_mels"] == 0


def test_posture_analyzer_invalid_frames():
    """面部分析器对无效帧应安全返回"""
    from voicetrace.core.posture_analyzer import PostureAnalyzer, is_mediapipe_available

    if not is_mediapipe_available():
        pytest.skip("MediaPipe 未安装")

    analyzer = PostureAnalyzer()

    # None
    result = analyzer.analyze_frame(None, 0.0)
    assert result.face_detected is False

    # 空数组
    result = analyzer.analyze_frame(np.array([]), 0.0)
    assert result.face_detected is False

    # 错误维度
    result = analyzer.analyze_frame(np.zeros((100,)), 0.0)
    assert result.face_detected is False

    # 灰度图
    result = analyzer.analyze_frame(np.zeros((100, 100), dtype=np.uint8), 0.0)
    assert result.face_detected is False

    analyzer.close()


def test_posture_analyzer_session_empty():
    """空时间线汇总不应崩溃"""
    from voicetrace.core.posture_analyzer import PostureAnalyzer, is_mediapipe_available

    if not is_mediapipe_available():
        pytest.skip("MediaPipe 未安装")

    analyzer = PostureAnalyzer()
    summary = analyzer.summarize_session([])
    assert summary.duration == 0.0
    assert summary.eye_contact_score == 0.0
    analyzer.close()


def test_pose_analyzer_invalid_frames():
    """姿态分析器对无效帧应安全返回"""
    from voicetrace.core.pose_analyzer import PoseAnalyzer, is_mediapipe_available

    if not is_mediapipe_available():
        pytest.skip("MediaPipe 未安装")

    analyzer = PoseAnalyzer(mode="standing")

    result = analyzer.analyze_frame(None, 0.0)
    assert result.pose_detected is False

    result = analyzer.analyze_frame(np.array([]), 0.0)
    assert result.pose_detected is False

    result = analyzer.analyze_frame(np.zeros((100,)), 0.0)
    assert result.pose_detected is False

    analyzer.close()


def test_database_invalid_inputs():
    """数据库对无效输入应抛出合理异常而不是崩溃"""
    from voicetrace.data.database import Database
    from voicetrace.data.models import Script, Recording

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")

        with pytest.raises(ValueError):
            db.create_script(Script(title="", category="custom", language="chinese"))

        with pytest.raises(ValueError):
            db.create_recording(Recording(script_id=1, file_path=""))

        assert db.get_script(None) is None
        assert db.get_recording(None) is None
        assert db.get_stumbles(None) == []
        assert db.list_analyses(None) == []
        db.close()
