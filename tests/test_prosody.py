"""韵律分析功能测试"""
import json
import tempfile
import wave
import struct
from pathlib import Path

import numpy as np
import pytest


def _make_wav(path: Path, freq: float = 440.0, duration: float = 2.0, sr: int = 16000):
    """生成测试用 WAV 文件"""
    t = np.linspace(0, duration, int(sr * duration), False)
    # 添加包络避免爆破音
    envelope = np.ones_like(t)
    attack = int(0.05 * sr)
    release = int(0.05 * sr)
    envelope[:attack] = np.linspace(0, 1, attack)
    envelope[-release:] = np.linspace(1, 0, release)
    y = (np.sin(2 * np.pi * freq * t) * 0.3 * envelope * 32767).astype(np.int16)
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(y.tobytes())


def test_prosody_analyzer_import():
    from voicetrace.core.prosody_analyzer import (
        ProsodyAnalyzer, ProsodyFeatures, is_parselmouth_available
    )
    assert ProsodyAnalyzer is not None
    assert ProsodyFeatures is not None
    assert is_parselmouth_available()


def test_prosody_features_serialization():
    """测试 ProsodyFeatures 序列化与反序列化"""
    from voicetrace.core.prosody_analyzer import ProsodyFeatures

    f = ProsodyFeatures(
        f0_mean=200.0,
        f0_std=15.5,
        f0_min=150.0,
        f0_max=250.0,
        f0_range=100.0,
        f0_times_json="[0.0, 0.1, 0.2]",
        f0_values_json="[200.0, 205.0, 210.0]"
    )
    d = f.to_dict()
    assert d["f0_mean"] == 200.0
    assert d["f0_std"] == 15.5
    assert d["f0_times_json"] == "[0.0, 0.1, 0.2]"

    f2 = ProsodyFeatures.from_dict(d)
    assert f2.f0_mean == 200.0
    assert f2.f0_std == 15.5


def test_prosody_analyze_sine_wave():
    """测试用正弦波生成可识别的基频"""
    from voicetrace.core.prosody_analyzer import ProsodyAnalyzer

    sr = 16000
    duration = 2.0
    freq = 220.0
    t = np.linspace(0, duration, int(sr * duration), False)
    y = (np.sin(2 * np.pi * freq * t) * 0.3).astype(np.float64)

    pa = ProsodyAnalyzer()
    result = pa.analyze(y, sr, "english")

    assert result.f0_mean is not None
    # 允许 ±10% 误差
    assert abs(result.f0_mean - freq) < freq * 0.15
    assert result.f0_min is not None
    assert result.f0_max is not None
    assert result.f0_range >= 0
    assert result.intensity_mean is not None
    assert len(json.loads(result.f0_times_json)) > 0
    assert len(json.loads(result.f0_values_json)) > 0


def test_prosody_analyze_silence():
    """静音音频应返回空特征"""
    from voicetrace.core.prosody_analyzer import ProsodyAnalyzer

    sr = 16000
    y = np.zeros(sr, dtype=np.float64)
    pa = ProsodyAnalyzer()
    result = pa.analyze(y, sr, "chinese")

    assert result.f0_mean is None
    assert result.intensity_mean is None
    assert json.loads(result.f0_times_json) == []


def test_analyzer_returns_prosody():
    """测试 Analyzer.analyze 返回 prosody 字段"""
    from voicetrace.core.analyzer import Analyzer

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "test.wav"
        _make_wav(wav_path, freq=330.0, duration=2.0)

        a = Analyzer()
        result = a.analyze(str(wav_path), "你好世界。", "chinese")

        assert "prosody" in result
        prosody = result["prosody"]
        assert prosody is not None
        assert "f0_mean" in prosody
        assert prosody["f0_mean"] is not None
        assert abs(prosody["f0_mean"] - 330.0) < 50.0


def test_database_analysis_prosody_json():
    """测试数据库存取 prosody_json"""
    from voicetrace.data.database import Database
    from voicetrace.data.models import Analysis, Script, Recording

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        db = Database(tmp_path / "test.db")

        # 先创建 script 和 recording 以满足外键约束
        sid = db.create_script(Script(title="测试稿件", category="custom", language="chinese"))
        rid = db.create_recording(Recording(script_id=sid, file_path=str(tmp_path / "fake.wav"), duration=10.0))

        prosody_data = {
            "f0_mean": 200.0,
            "f0_std": 15.0,
            "f0_times_json": "[0.0, 0.1]",
            "f0_values_json": "[200.0, 210.0]"
        }
        aid = db.create_analysis(Analysis(
            recording_id=rid,
            speech_rate=260.0,
            pause_count=2,
            total_pause_duration=0.5,
            rms_energy=0.05,
            prosody_json=json.dumps(prosody_data, ensure_ascii=False)
        ))
        assert aid > 0

        analysis = db.get_latest_analysis(rid)
        assert analysis is not None
        assert analysis.prosody_json is not None
        loaded = json.loads(analysis.prosody_json)
        assert loaded["f0_mean"] == 200.0
        assert loaded["f0_std"] == 15.0
        db.close()
