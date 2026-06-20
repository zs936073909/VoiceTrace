"""强制对齐功能测试"""
import json
import tempfile
from pathlib import Path


def test_aligner_import():
    from voicetrace.core.aligner import (
        ForcedAligner, AlignedToken, AlignedSentence,
        AlignmentResult, is_forced_aligner_available
    )
    assert ForcedAligner is not None
    assert AlignmentResult is not None
    # faster-whisper 应该已安装
    assert is_forced_aligner_available()


def test_alignment_result_serialization():
    """测试 AlignmentResult 序列化与反序列化"""
    from voicetrace.core.aligner import (
        AlignmentResult, AlignedSentence, AlignedToken
    )

    result = AlignmentResult(
        language="zh",
        language_probability=0.98,
        sentences=[
            AlignedSentence(
                text="你好世界",
                start_time=0.0,
                end_time=2.0,
                tokens=[
                    AlignedToken("你", 0.0, 0.5),
                    AlignedToken("好", 0.5, 1.0),
                    AlignedToken("世", 1.0, 1.5),
                    AlignedToken("界", 1.5, 2.0),
                ]
            )
        ]
    )

    d = result.to_dict()
    assert d["language"] == "zh"
    assert len(d["sentences"]) == 1
    assert len(d["sentences"][0]["tokens"]) == 4
    assert d["sentences"][0]["tokens"][0]["text"] == "你"

    r2 = AlignmentResult.from_dict(d)
    assert r2.language == "zh"
    assert len(r2.sentences[0].tokens) == 4
    assert r2.sentences[0].tokens[0].start_time == 0.0


def test_align_tokens_chinese():
    """测试中文 token DP 对齐逻辑"""
    from voicetrace.core.aligner import ForcedAligner, AlignedToken

    aligner = ForcedAligner.__new__(ForcedAligner)
    script_tokens = ["你", "好", "世", "界"]
    recognized = [
        ("你", 0.0, 0.5, 0.9),
        ("好", 0.5, 1.0, 0.9),
        ("界", 1.0, 1.5, 0.8),  # 缺失 "世"
    ]

    aligned = aligner._align_tokens(script_tokens, recognized, "zh")

    assert len(aligned) == 4
    assert aligned[0].text == "你"
    assert aligned[0].is_missing is False
    assert aligned[1].text == "好"
    assert aligned[2].text == "世"
    assert aligned[2].is_missing is True
    assert aligned[3].text == "界"


def test_align_tokens_english():
    """测试英文 token DP 对齐逻辑"""
    from voicetrace.core.aligner import ForcedAligner

    aligner = ForcedAligner.__new__(ForcedAligner)
    script_tokens = ["Hello", "world", "test"]
    recognized = [
        ("hello", 0.0, 0.5, 0.9),
        ("world", 0.5, 1.0, 0.9),
    ]

    aligned = aligner._align_tokens(script_tokens, recognized, "en")

    assert len(aligned) == 3
    assert aligned[0].text == "Hello"
    assert aligned[1].text == "world"
    assert aligned[2].text == "test"
    assert aligned[2].is_missing is True


def test_group_into_sentences():
    """测试句子分组"""
    from voicetrace.core.aligner import ForcedAligner, AlignedToken

    aligner = ForcedAligner.__new__(ForcedAligner)
    script_text = "你好。世界。"
    tokens = [
        AlignedToken("你", 0.0, 0.3),
        AlignedToken("好", 0.3, 0.6),
        AlignedToken("世", 1.0, 1.3),
        AlignedToken("界", 1.3, 1.6),
    ]
    sentences = aligner._group_into_sentences(script_text, tokens, "zh")

    assert len(sentences) == 2
    assert sentences[0].text == "你好。"
    assert len(sentences[0].tokens) == 2
    assert sentences[1].text == "世界。"
    assert len(sentences[1].tokens) == 2


def test_database_alignment_json():
    """测试数据库存取 alignment_json"""
    from voicetrace.data.database import Database
    from voicetrace.data.models import Analysis, Script, Recording

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        db = Database(tmp_path / "test.db")

        sid = db.create_script(Script(title="对齐测试", category="custom", language="chinese"))
        rid = db.create_recording(Recording(script_id=sid, file_path=str(tmp_path / "fake.wav"), duration=10.0))

        alignment_data = {
            "language": "zh",
            "language_probability": 0.95,
            "sentences": [
                {
                    "text": "你好",
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "tokens": [
                        {"text": "你", "start_time": 0.0, "end_time": 0.5, "confidence": 0.9, "is_missing": False},
                        {"text": "好", "start_time": 0.5, "end_time": 1.0, "confidence": 0.9, "is_missing": False}
                    ]
                }
            ]
        }

        aid = db.create_analysis(Analysis(
            recording_id=rid,
            speech_rate=260.0,
            pause_count=2,
            total_pause_duration=0.5,
            rms_energy=0.05,
            alignment_json=json.dumps(alignment_data, ensure_ascii=False)
        ))
        assert aid > 0

        analysis = db.get_latest_analysis(rid)
        assert analysis is not None
        assert analysis.alignment_json is not None
        loaded = json.loads(analysis.alignment_json)
        assert loaded["language"] == "zh"
        assert len(loaded["sentences"][0]["tokens"]) == 2
        db.close()
