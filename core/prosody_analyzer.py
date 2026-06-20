"""韵律分析模块

基于 Parselmouth(Praat) 提取基频(F0)、共振峰、强度等韵律特征，
用于播音主持训练中评估语调起伏、重音、声调稳定性等专业指标。
"""
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import numpy as np

from voicetrace.utils.audio import count_chinese_chars

try:
    import parselmouth
    from parselmouth.praat import call
    PARSELMOUTH_AVAILABLE = True
except ImportError:
    PARSELMOUTH_AVAILABLE = False


@dataclass
class ProsodyFeatures:
    """韵律特征数据类"""
    # 基频
    f0_mean: Optional[float] = None          # 平均基频 (Hz)
    f0_std: Optional[float] = None           # 基频标准差
    f0_min: Optional[float] = None           # 最低基频
    f0_max: Optional[float] = None           # 最高基频
    f0_range: Optional[float] = None         # 基频范围

    # 语调动态
    f0_slope_mean: Optional[float] = None    # 平均基频斜率 (Hz/s)
    f0_slope_std: Optional[float] = None     # 斜率标准差
    f0_rise_count: Optional[int] = None      # 上升段数量
    f0_fall_count: Optional[int] = None      # 下降段数量

    # 强度
    intensity_mean: Optional[float] = None   # 平均强度 (dB)
    intensity_std: Optional[float] = None    # 强度标准差
    intensity_range: Optional[float] = None  # 强度动态范围

    # 共振峰
    formant_mean_1: Optional[float] = None   # 第一共振峰均值 (Hz)
    formant_mean_2: Optional[float] = None   # 第二共振峰均值 (Hz)
    formant_mean_3: Optional[float] = None   # 第三共振峰均值 (Hz)

    # 声音质量
    hnr_mean: Optional[float] = None         # 谐噪比均值 (dB)
    jitter: Optional[float] = None           # 频率微扰 (%)
    shimmer: Optional[float] = None          # 振幅微扰 (%)

    # 中文声调相关
    tone_stability: Optional[float] = None   # 声调稳定性 (0-100)
    tone_score: Optional[float] = None       # 普通话声调得分 (0-100)

    # 原始序列数据 (用于绘图，JSON 序列化)
    f0_times_json: str = "[]"                # 时间点数组
    f0_values_json: str = "[]"               # 基频值数组
    intensity_times_json: str = "[]"         # 强度时间点
    intensity_values_json: str = "[]"        # 强度值

    def to_dict(self) -> Dict[str, Any]:
        return {
            "f0_mean": self.f0_mean,
            "f0_std": self.f0_std,
            "f0_min": self.f0_min,
            "f0_max": self.f0_max,
            "f0_range": self.f0_range,
            "f0_slope_mean": self.f0_slope_mean,
            "f0_slope_std": self.f0_slope_std,
            "f0_rise_count": self.f0_rise_count,
            "f0_fall_count": self.f0_fall_count,
            "intensity_mean": self.intensity_mean,
            "intensity_std": self.intensity_std,
            "intensity_range": self.intensity_range,
            "formant_mean_1": self.formant_mean_1,
            "formant_mean_2": self.formant_mean_2,
            "formant_mean_3": self.formant_mean_3,
            "hnr_mean": self.hnr_mean,
            "jitter": self.jitter,
            "shimmer": self.shimmer,
            "tone_stability": self.tone_stability,
            "tone_score": self.tone_score,
            "f0_times_json": self.f0_times_json,
            "f0_values_json": self.f0_values_json,
            "intensity_times_json": self.intensity_times_json,
            "intensity_values_json": self.intensity_values_json,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProsodyFeatures":
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


class ProsodyAnalyzer:
    """韵律分析器"""

    def __init__(self):
        self.available = PARSELMOUTH_AVAILABLE

    def analyze(self, samples: np.ndarray, sr: int, language: str = "chinese") -> ProsodyFeatures:
        """分析音频样本的韵律特征

        Args:
            samples: 音频样本，float64 numpy 数组，范围 [-1, 1]
            sr: 采样率
            language: 'chinese' | 'english'

        Returns:
            ProsodyFeatures
        """
        if not self.available:
            return ProsodyFeatures()

        try:
            sound = parselmouth.Sound(samples, sampling_frequency=sr)
        except Exception:
            return ProsodyFeatures()

        features = ProsodyFeatures()

        # 1. 基频提取
        f0_times, f0_values = self._extract_f0(sound)
        if len(f0_values) > 0 and np.any(f0_values > 0):
            valid_f0 = f0_values[f0_values > 0]
            features.f0_mean = float(np.mean(valid_f0))
            features.f0_std = float(np.std(valid_f0))
            features.f0_min = float(np.min(valid_f0))
            features.f0_max = float(np.max(valid_f0))
            features.f0_range = float(features.f0_max - features.f0_min)

            # 斜率分析
            slopes = self._compute_slopes(f0_times, f0_values)
            if len(slopes) > 0:
                features.f0_slope_mean = float(np.mean(slopes))
                features.f0_slope_std = float(np.std(slopes))
                features.f0_rise_count = int(np.sum(slopes > 10))    # >10 Hz/s 上升
                features.f0_fall_count = int(np.sum(slopes < -10))   # <-10 Hz/s 下降

            # 中文声调相关
            if language == "chinese":
                tone_metrics = self._compute_tone_metrics(f0_times, f0_values, sr)
                features.tone_stability = tone_metrics.get("tone_stability")
                features.tone_score = tone_metrics.get("tone_score")

        # 2. 强度提取（过滤 Praat 的 -300 dB 无效值）
        intensity_times, intensity_values = self._extract_intensity(sound)
        if len(intensity_values) > 0:
            valid_intensity = intensity_values[intensity_values > -100]
            if len(valid_intensity) > 0:
                features.intensity_mean = float(np.mean(valid_intensity))
                features.intensity_std = float(np.std(valid_intensity))
                features.intensity_range = float(np.max(valid_intensity) - np.min(valid_intensity))

        # 3. 共振峰
        formants = self._extract_formants(sound)
        features.formant_mean_1 = formants.get("f1")
        features.formant_mean_2 = formants.get("f2")
        features.formant_mean_3 = formants.get("f3")

        # 4. 声音质量 (HNR, Jitter, Shimmer)
        quality = self._extract_voice_quality(sound, f0_times, f0_values)
        features.hnr_mean = quality.get("hnr")
        features.jitter = quality.get("jitter")
        features.shimmer = quality.get("shimmer")

        # 5. 序列数据 JSON 化
        # 如果没有有效 F0/强度，则清空序列（避免绘出无效点）
        if features.f0_mean is None:
            f0_times = np.array([])
            f0_values = np.array([])
        if features.intensity_mean is None:
            intensity_times = np.array([])
            intensity_values = np.array([])

        features.f0_times_json = json.dumps([float(x) for x in f0_times])
        features.f0_values_json = json.dumps([float(x) for x in f0_values])
        features.intensity_times_json = json.dumps([float(x) for x in intensity_times])
        features.intensity_values_json = json.dumps([float(x) for x in intensity_values])

        return features

    def _extract_f0(self, sound: "parselmouth.Sound") -> tuple:
        """提取基频曲线"""
        try:
            # 标准基频范围 75-600 Hz，适合人声
            pitch = call(sound, "To Pitch", 0.0, 75, 600)
            times = pitch.xs()
            values = pitch.selected_array['frequency']
            return np.array(times), np.array(values)
        except Exception:
            return np.array([]), np.array([])

    def _extract_intensity(self, sound: "parselmouth.Sound") -> tuple:
        """提取强度曲线"""
        try:
            intensity = sound.to_intensity()
            times = intensity.xs()
            values = intensity.values[0]
            return np.array(times), np.array(values)
        except Exception:
            return np.array([]), np.array([])

    def _extract_formants(self, sound: "parselmouth.Sound") -> Dict[str, Optional[float]]:
        """提取前三个共振峰均值"""
        result = {"f1": None, "f2": None, "f3": None}
        try:
            formant = call(sound, "To Formant (burg)", 0.0, 5, 5500, 0.025, 50)
            f1_list, f2_list, f3_list = [], [], []
            num_frames = call(formant, "Get number of frames")
            for i in range(1, num_frames + 1):
                t = call(formant, "Get time from frame number", i)
                f1 = call(formant, "Get value at time", 1, t, "Hertz", "Linear")
                f2 = call(formant, "Get value at time", 2, t, "Hertz", "Linear")
                f3 = call(formant, "Get value at time", 3, t, "Hertz", "Linear")
                if not np.isnan(f1) and f1 > 0:
                    f1_list.append(f1)
                if not np.isnan(f2) and f2 > 0:
                    f2_list.append(f2)
                if not np.isnan(f3) and f3 > 0:
                    f3_list.append(f3)
            if f1_list:
                result["f1"] = float(np.mean(f1_list))
            if f2_list:
                result["f2"] = float(np.mean(f2_list))
            if f3_list:
                result["f3"] = float(np.mean(f3_list))
        except Exception:
            pass
        return result

    def _extract_voice_quality(self, sound: "parselmouth.Sound",
                               f0_times: np.ndarray,
                               f0_values: np.ndarray) -> Dict[str, Optional[float]]:
        """提取声音质量指标"""
        result = {"hnr": None, "jitter": None, "shimmer": None}
        try:
            # 谐噪比（过滤无效值）
            harmonicity = call(sound, "To Harmonicity (cc)", 0.01, 75, 0.1, 1.0)
            hnr_values = harmonicity.values[0]
            valid_hnr = hnr_values[hnr_values > -100]
            if len(valid_hnr) > 0:
                result["hnr"] = float(np.mean(valid_hnr))

            # 需要足够长的浊音段才能计算 jitter/shimmer
            if len(f0_values) > 0 and np.sum(f0_values > 0) >= 20:
                # 提取一个稳定的浊音区间
                voiced_indices = np.where(f0_values > 0)[0]
                if len(voiced_indices) >= 20:
                    start_idx = voiced_indices[0]
                    end_idx = voiced_indices[min(50, len(voiced_indices) - 1)]
                    start_time = float(f0_times[start_idx])
                    end_time = float(f0_times[end_idx])
                    duration = end_time - start_time
                    if duration >= 0.2:  # 至少 200ms
                        point_process = call(sound, "To PointProcess (periodic, cc)",
                                            75, 600, 0.0)
                        jitter = call(point_process, "Get jitter (local)",
                                     start_time, end_time, 0.0001, 0.02, 1.3)
                        shimmer = call([sound, point_process],
                                      "Get shimmer (local)",
                                      start_time, end_time, 0.0001, 0.02, 1.3, 1.6)
                        result["jitter"] = float(jitter) * 100 if jitter is not None else None
                        result["shimmer"] = float(shimmer) * 100 if shimmer is not None else None
        except Exception:
            pass
        return result

    def _compute_slopes(self, times: np.ndarray, values: np.ndarray,
                        window: int = 5) -> np.ndarray:
        """计算基频变化斜率 (Hz/s)"""
        if len(times) < window + 1:
            return np.array([])

        slopes = []
        valid_values = values.copy()
        valid_values[valid_values <= 0] = np.nan

        half = window // 2
        for i in range(half, len(times) - half):
            left_vals = valid_values[i - half:i + half + 1]
            if np.sum(~np.isnan(left_vals)) < 3:
                continue
            # 线性回归
            t_window = times[i - half:i + half + 1] - times[i]
            valid_mask = ~np.isnan(left_vals)
            if np.sum(valid_mask) < 3:
                continue
            slope, _ = np.polyfit(t_window[valid_mask], left_vals[valid_mask], 1)
            slopes.append(slope)

        return np.array(slopes)

    def _compute_tone_metrics(self, times: np.ndarray, values: np.ndarray,
                              sr: int) -> Dict[str, Optional[float]]:
        """计算中文声调稳定性指标

        思路：将基频曲线分成若干短段（约200-300ms），
        计算相邻段之间的调型一致性。调型变化过大可能意味着声调不准。
        """
        if len(values) < 10 or np.sum(values > 0) < 10:
            return {"tone_stability": None, "tone_score": None}

        valid_mask = values > 0
        valid_times = times[valid_mask]
        valid_values = values[valid_mask]

        if len(valid_values) < 10:
            return {"tone_stability": None, "tone_score": None}

        # 归一化到 0-1
        f0_min, f0_max = np.min(valid_values), np.max(valid_values)
        if f0_max - f0_min < 1:
            return {"tone_stability": None, "tone_score": None}

        normalized = (valid_values - f0_min) / (f0_max - f0_min)

        # 声调稳定性：基频曲线平滑度
        diff = np.diff(normalized)
        stability = max(0, 100 - float(np.std(diff)) * 200)

        # 声调得分：综合稳定性 + 动态范围
        dynamic_range = f0_max - f0_min
        # 普通话声调应有足够动态范围（>20Hz），但不宜过大或过小
        if dynamic_range < 10:
            range_score = 50
        elif dynamic_range > 100:
            range_score = 85
        else:
            range_score = 60 + (dynamic_range - 10) / 90 * 35

        tone_score = (stability * 0.6 + range_score * 0.4)

        return {
            "tone_stability": float(stability),
            "tone_score": float(tone_score)
        }


def is_parselmouth_available() -> bool:
    return PARSELMOUTH_AVAILABLE
