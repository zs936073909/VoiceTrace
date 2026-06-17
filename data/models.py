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
    id: Optional[int] = None


@dataclass
class Comparison:
    recording_id: int
    baseline_id: int
    similarity_score: Optional[float] = None
    differences_json: Optional[str] = None
    id: Optional[int] = None


@dataclass
class TrainingSession:
    """训练打卡记录"""
    script_id: Optional[int] = None
    recording_id: Optional[int] = None
    duration: float = 0.0  # 训练时长(秒)
    notes: Optional[str] = None
    id: Optional[int] = None
    date: Optional[str] = None  # YYYY-MM-DD


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
