"""台风训练 AI 教练

基于结构化数据（面部/姿态分析结果）生成实时提示和训练总结。
支持：
1. 文本大模型：基于汇总数据生成整体评价和改进建议
2. 多模态大模型（可选）：基于训练结束时的一帧画面做视觉分析

所有 LLM 配置来自 llm_config_manager。
"""
import base64
import io
import json
import logging
from typing import Optional

import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

from voicetrace.core.llm_config_manager import get_llm_config_manager
from voicetrace.core.llm_service import LLMService

logger = logging.getLogger(__name__)


def build_summary_prompt(face_summary, pose_summary, mode: str = "sit") -> str:
    """根据面部分析和姿态分析汇总构建总结 prompt"""
    parts = []
    parts.append("你是一名专业的播音主持/演讲教练。请根据以下学员台风训练数据，给出一段整体评价、3-5 条改进建议和 2-3 个今天就能练的针对性练习。")
    parts.append(f"训练模式：{'坐姿（电脑前）' if mode == 'sit' else '站姿（模拟演讲）'}")

    if face_summary:
        parts.append(
            f"\n【面部/镜头感数据】\n"
            f"- 眼神交流时长占比：{face_summary.eye_contact_ratio:.1%}\n"
            f"- 眼神交流评分：{face_summary.eye_contact_score:.0f}/100\n"
            f"- 眨眼次数：{face_summary.blink_count}，频率：{face_summary.blink_rate:.1f} 次/分\n"
            f"- 平均微笑度：{face_summary.avg_smile:.1%}\n"
            f"- 平均紧张度：{face_summary.avg_tension:.1%}\n"
            f"- 头部运动量：{face_summary.head_movement:.1f}°\n"
            f"- 头部姿态评分：{face_summary.head_pose_score:.0f}/100\n"
            f"- 表情管理评分：{face_summary.expression_score:.0f}/100"
        )

    if pose_summary:
        parts.append(
            f"\n【身体姿态数据】\n"
            f"- 站姿/坐姿评分：{pose_summary.posture_score:.0f}/100\n"
            f"- 手势评分：{pose_summary.gesture_score:.0f}/100\n"
            f"- 稳定性评分：{pose_summary.stability_score:.0f}/100\n"
            f"- 手势时长占比：{pose_summary.gesture_ratio:.1%}\n"
            f"- 身体平均运动量：{pose_summary.avg_movement:.4f}\n"
            f"- 平均肩膀倾斜：{pose_summary.avg_shoulder_tilt:.1f}°\n"
            f"- 平均身体前倾：{pose_summary.avg_body_lean:.1f}°\n"
            f"- 平均头部前伸：{pose_summary.avg_head_forward:.1f}°"
        )

    parts.append("\n要求：")
    parts.append("1. 整体评价用 2-3 句话概括优势和主要问题；")
    parts.append("2. 改进建议具体、可操作，避免空泛；")
    parts.append("3. 针对性练习要写明练习动作/方法和次数；")
    parts.append("4. 语气鼓励、专业，像一位耐心的教练。")

    return "\n".join(parts)


def generate_summary(face_summary, pose_summary, mode: str = "sit") -> str:
    """调用文本 LLM 生成台风训练总结

    如果未配置 LLM，返回基于规则的文字总结。
    """
    manager = get_llm_config_manager()
    config = manager.get_text_config()

    if not config.api_key:
        return _rule_based_summary(face_summary, pose_summary, mode)

    service = LLMService(config)
    prompt = build_summary_prompt(face_summary, pose_summary, mode)

    try:
        response = service.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是一名专业的播音主持与演讲台风教练，擅长用清晰、鼓励性的语言给出改进建议。",
            max_tokens=1500
        )
        if response.success:
            return response.content
        else:
            logger.warning(f"LLM 台风总结失败: {response.error}")
            return f"AI 总结生成失败：{response.error}\n\n{_rule_based_summary(face_summary, pose_summary, mode)}"
    except Exception as exc:
        logger.warning(f"LLM 台风总结异常: {exc}")
        return _rule_based_summary(face_summary, pose_summary, mode)


def analyze_frame_image(frame_bgr, face_summary, pose_summary, mode: str = "sit") -> str:
    """使用多模态大模型分析单帧画面

    如果未启用多模态，返回空字符串。
    """
    if not CV2_AVAILABLE or frame_bgr is None or frame_bgr.size == 0:
        return ""

    manager = get_llm_config_manager()
    config = manager.get_multimodal_config()
    if not config:
        return ""

    # 压缩并编码为 JPEG
    try:
        resized = cv2.resize(frame_bgr, (640, 480))
        _, encoded = cv2.imencode(".jpg", resized)
        image_data = encoded.tobytes()
    except Exception as exc:
        logger.warning(f"画面编码失败: {exc}")
        return ""

    prompt = (
        "你是一名专业的播音主持/演讲教练。请观察这张训练画面，\n"
        "评价学员的镜头感、表情、头部姿态和身体姿态，\n"
        "指出 2-3 个最明显的问题，并给出具体改进建议。"
    )

    service = LLMService(config)
    try:
        response = service.vision_completion(
            image_data=image_data,
            prompt=prompt,
            mime_type="image/jpeg",
            max_tokens=1000
        )
        if response.success:
            return response.content
        else:
            logger.warning(f"多模态分析失败: {response.error}")
            return ""
    except Exception as exc:
        logger.warning(f"多模态分析异常: {exc}")
        return ""


def build_realtime_tip_prompt(face_recent: list, pose_recent: list, mode: str = "sit") -> str:
    """根据最近若干帧数据构建实时点拨 prompt"""
    if not face_recent and not pose_recent:
        return ""

    parts = []
    parts.append("你是一名专业的播音主持/演讲教练。请根据学员最近几秒的训练数据，给出一句简短、具体的实时点拨（不超过 40 字），直接告诉学员此刻应该调整什么。")
    parts.append(f"训练模式：{'坐姿（电脑前）' if mode == 'sit' else '站姿（模拟演讲）'}")

    if face_recent:
        avg_eye = sum(f.eye_contact for f in face_recent) / len(face_recent)
        avg_smile = sum(f.smile_score for f in face_recent) / len(face_recent)
        avg_tension = sum(f.tension_score for f in face_recent) / len(face_recent)
        last = face_recent[-1]
        parts.append(
            f"\n【最近面部数据】\n"
            f"- 眼神交流平均：{avg_eye:.1%}\n"
            f"- 微笑度平均：{avg_smile:.1%}\n"
            f"- 紧张度平均：{avg_tension:.1%}\n"
            f"- 头部偏航：{last.head_yaw:.0f}°，俯仰：{last.head_pitch:.0f}°，翻滚：{last.head_roll:.0f}°"
        )

    if pose_recent:
        last_pose = pose_recent[-1]
        parts.append(
            f"\n【最近姿态数据】\n"
            f"- 肩膀倾斜：{last_pose.shoulder_tilt:.1f}°\n"
            f"- 身体前倾：{last_pose.body_lean:.1f}°\n"
            f"- 头部前伸：{last_pose.head_forward:.1f}°\n"
            f"- 当前是否在用手势：{'是' if last_pose.is_gesturing else '否'}"
        )

    parts.append("\n要求：只输出一句具体可执行的点拨，不要解释原因，不要分点。")
    return "\n".join(parts)


def generate_realtime_tip(face_recent: list, pose_recent: list, mode: str = "sit") -> str:
    """调用文本 LLM 生成实时点拨

    如果未配置 LLM，返回空字符串，由调用方使用规则提示兜底。
    """
    manager = get_llm_config_manager()
    config = manager.get_text_config()
    if not config.api_key:
        return ""

    prompt = build_realtime_tip_prompt(face_recent, pose_recent, mode)
    if not prompt:
        return ""

    service = LLMService(config)
    try:
        response = service.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是一位专注、简洁的播音主持教练，每次只说一个最重要的调整点。",
            max_tokens=120
        )
        if response.success:
            return response.content.strip()
        else:
            logger.warning(f"实时点拨生成失败: {response.error}")
            return ""
    except Exception as exc:
        logger.warning(f"实时点拨异常: {exc}")
        return ""


def _rule_based_summary(face_summary, pose_summary, mode: str = "sit") -> str:
    """基于规则的兜底总结"""
    lines = []
    lines.append("## 台风训练总结\n")

    if face_summary:
        lines.append("### 镜头感")
        if face_summary.eye_contact_score >= 70:
            lines.append("眼神交流表现较好，大部分时间能看向镜头。")
        else:
            lines.append("眼神交流不足，训练过程中看向镜头的比例偏低，建议多练习盯镜头说话。")

        if face_summary.avg_tension > 0.5:
            lines.append("面部紧张度偏高，注意放松眉部和嘴部肌肉。")
        elif face_summary.avg_smile > 0.3:
            lines.append("表情自然，有微笑，状态放松。")

        if face_summary.head_pose_score >= 70:
            lines.append("头部姿态稳定，没有明显偏转。")
        else:
            lines.append("头部偏转或歪斜较多，注意保持面部正对镜头。")

    if pose_summary:
        lines.append("\n### 身体姿态")
        if pose_summary.posture_score >= 70:
            lines.append("身体姿态端正。" if mode == "sit" else "站姿挺拔。")
        else:
            lines.append("存在驼背/前倾或肩膀倾斜，注意打开肩膀、挺直腰背。")

        if pose_summary.gesture_score >= 70:
            lines.append("手势运用得当，能辅助表达。")
        else:
            lines.append("手势较少或过多，建议配合语气适当加入手势。")

        if pose_summary.stability_score >= 70:
            lines.append("身体稳定性好，没有明显晃动。")
        else:
            lines.append("身体晃动较多，站立/坐下时尽量保持核心稳定。")

    lines.append("\n### 建议练习")
    lines.append("1. 对镜练习：每天 3 分钟，盯着自己的眼睛说话。")
    lines.append("2. 录像复盘：录制一段 30 秒播报，观察头部是否歪斜、眼神是否飘移。")
    lines.append("3. 姿态定格：靠墙站立/端坐，保持头、肩、臀在一条线上 2 分钟。")

    return "\n".join(lines)
