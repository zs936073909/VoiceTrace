from dataclasses import dataclass, field
from typing import Optional, List
import json


@dataclass
class Script:
    title: str
    category: str  # 'news_broadcast'|'improv_commentary'|'mock_host'|'custom'
    language: str  # 'chinese'|'english'|'mixed'
    content: Optional[str] = None
    id: Optional[int] = None


@dataclass
class Recording:
    script_id: int
    file_path: str
    duration: Optional[float] = None
    id: Optional[int] = None


@dataclass
class Stumble:
    recording_id: int
    stumble_time: float  # seconds
    label: Optional[str] = None
    id: Optional[int] = None


@dataclass
class Analysis:
    recording_id: int
    speech_rate: Optional[float] = None
    pause_count: Optional[int] = None
    total_pause_duration: Optional[float] = None
    rms_energy: Optional[float] = None
    mfcc_features: Optional[bytes] = None
    spectral_features: Optional[bytes] = None
    sentence_analysis_json: Optional[str] = None  # JSON: [{sentence, rate, pause_count}, ...]
    # 韵律特征 JSON
    prosody_json: Optional[str] = None  # JSON: ProsodyFeatures.to_dict()
    # 强制对齐结果 JSON
    alignment_json: Optional[str] = None  # JSON: AlignmentResult.to_dict()
    id: Optional[int] = None


@dataclass
class Comparison:
    recording_id: int
    baseline_id: int
    similarity_score: Optional[float] = None
    differences_json: Optional[str] = None
    id: Optional[int] = None


@dataclass
class CustomStandard:
    """自定义语速标准"""
    name: str
    language: str
    category: str
    rate_min: int
    rate_max: int
    unit: str = "CPM"
    id: Optional[int] = None


@dataclass
class PostureRecord:
    """台风训练记录（镜头感 + 肢体语言）"""
    recording_id: Optional[int] = None  # 关联的录音ID（可选）
    duration: float = 0.0  # 训练时长(秒)
    # 镜头感维度（0-100）
    eye_contact_score: Optional[float] = None  # 眼神交流评分
    expression_score: Optional[float] = None  # 表情评分
    head_pose_score: Optional[float] = None  # 头部姿态评分
    # 肢体语言维度（0-100）
    posture_score: Optional[float] = None  # 站姿评分
    gesture_score: Optional[float] = None  # 手势评分
    stability_score: Optional[float] = None  # 稳定性评分
    # 综合评分
    overall_score: Optional[float] = None  # 综合台风评分
    # 详细数据（JSON）
    details_json: Optional[str] = None  # 详细分析数据
    video_path: Optional[str] = None  # 视频文件路径（用户选择保存时）
    notes: Optional[str] = None
    id: Optional[int] = None
    date: Optional[str] = None  # YYYY-MM-DD


@dataclass
class ScriptTemplate:
    """稿件模板（用于 AI 文案写作）"""
    name: str
    category: str  # 'news_broadcast'|'improv_commentary'|'mock_host'|'speech'
    language: str  # 'chinese'|'english'|'mixed'
    structure_json: Optional[str] = None  # 结构化模板数据
    tips: Optional[str] = None  # 写作提示
    id: Optional[int] = None


@dataclass
class MemoryCard:
    """记忆卡片（背诵训练核心数据结构）

    基于 FSRS-5 DSR 模型跟踪记忆状态。
    """
    card_id: str                       # 唯一 ID（f"script_{sid}_seg_{idx}"）
    script_id: Optional[int] = None    # 关联稿件 ID
    segment_index: int = 0             # 段落序号
    front: str = ""                    # 正面（提示，如关键词、上文）
    back: str = ""                     # 背面（答案，如完整段落）
    hint: str = ""                     # 额外提示
    scenario: str = "speech"           # 'speech' | 'host' | 'emergency'
    tags_json: Optional[str] = None    # 标签 JSON

    # FSRS 状态
    state: int = 0                     # 0=New, 1=Learning, 2=Review, 3=Relearning
    step: int = 0
    stability: float = 0.0
    difficulty: float = 0.0
    last_review: Optional[float] = None  # Unix 时间戳
    reps: int = 0
    lapses: int = 0
    created_at: Optional[str] = None    # ISO 时间字符串
    id: Optional[int] = None


@dataclass
class ReviewLog:
    """复习日志（每次评分的记录）"""
    card_id: str
    rating: int                        # 1=Again, 2=Hard, 3=Good, 4=Easy
    review_duration: float = 0.0       # 本次复习耗时（秒）
    reviewed_at: Optional[str] = None  # ISO 时间字符串
    state_before: int = 0
    state_after: int = 0
    stability_before: float = 0.0
    stability_after: float = 0.0
    retrievability: float = 0.0
    id: Optional[int] = None
