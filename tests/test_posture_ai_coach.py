"""台风训练 AI 教练模块测试"""
import pytest

from voicetrace.core.llm_config_manager import LLMConfigManager, AppLLMConfig
from voicetrace.core.posture_ai_coach import (
    build_summary_prompt,
    build_realtime_tip_prompt,
    _rule_based_summary,
)


class DummyFaceSummary:
    eye_contact_ratio = 0.6
    eye_contact_score = 65
    blink_count = 12
    blink_rate = 15.0
    avg_smile = 0.3
    avg_tension = 0.4
    head_movement = 12.5
    head_pose_score = 70
    expression_score = 68


class DummyPoseSummary:
    posture_score = 72
    gesture_score = 60
    stability_score = 75
    gesture_ratio = 0.4
    avg_movement = 0.02
    avg_shoulder_tilt = 3.0
    avg_body_lean = 5.0
    avg_head_forward = 0.08


class DummyFrame:
    eye_contact = 0.5
    smile_score = 0.3
    tension_score = 0.4
    head_yaw = 10.0
    head_pitch = 5.0
    head_roll = 2.0


class DummyPoseFrame:
    shoulder_tilt = 3.0
    body_lean = 5.0
    head_forward = 0.08
    is_gesturing = True


def test_build_summary_prompt_contains_key_metrics():
    prompt = build_summary_prompt(DummyFaceSummary(), DummyPoseSummary(), mode="sit")
    assert "眼神交流时长占比" in prompt
    assert "坐姿（电脑前）" in prompt
    assert "站姿/坐姿评分" in prompt


def test_build_summary_prompt_without_pose():
    prompt = build_summary_prompt(DummyFaceSummary(), None, mode="standing")
    assert "站姿（模拟演讲）" in prompt
    assert "身体姿态数据" not in prompt


def test_build_realtime_tip_prompt():
    prompt = build_realtime_tip_prompt([DummyFrame()], [DummyPoseFrame()], mode="sit")
    assert "实时点拨" in prompt
    assert "坐姿（电脑前）" in prompt
    assert "头部偏航" in prompt


def test_build_realtime_tip_prompt_empty():
    assert build_realtime_tip_prompt([], [], mode="sit") == ""


def test_rule_based_summary():
    text = _rule_based_summary(DummyFaceSummary(), DummyPoseSummary(), mode="sit")
    assert "台风训练总结" in text
    assert "镜头感" in text
    assert "身体姿态" in text
    assert "建议练习" in text


def test_llm_manager_ai_mode():
    # 未启用多模态时应为 text 模式
    cfg = AppLLMConfig(use_multimodal=False)
    assert cfg.to_multimodal_config() is None

    # 启用但缺少 key 时仍不可用
    cfg2 = AppLLMConfig(use_multimodal=True, multimodal_api_key="")
    assert cfg2.to_multimodal_config() is None

    # 启用且配置完整时可用
    cfg3 = AppLLMConfig(
        use_multimodal=True,
        multimodal_provider="openai",
        multimodal_api_key="sk-test",
        multimodal_model="gpt-4o"
    )
    mm_cfg = cfg3.to_multimodal_config()
    assert mm_cfg is not None
    assert mm_cfg.provider == "openai"
