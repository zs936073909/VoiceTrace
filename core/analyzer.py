import re
import json
import logging
from pathlib import Path
from typing import Tuple, Optional

import numpy as np
import librosa
import webrtcvad
from voicetrace.utils.audio import count_chinese_chars, count_english_words

from voicetrace.core.prosody_analyzer import ProsodyAnalyzer, is_parselmouth_available
from voicetrace.core.aligner import ForcedAligner, is_forced_aligner_available

logger = logging.getLogger(__name__)

# WebRTC VAD 仅支持这些采样率（Hz）
_SUPPORTED_VAD_RATES = (8000, 16000, 32000, 48000)
# 为保持一致性，统一重采样到 16kHz
_VAD_TARGET_SR = 16000
# 最小可分析音频长度（秒）
_MIN_AUDIO_DURATION = 0.05


class Analyzer:
    def __init__(self, vad_aggressiveness: int = 2):
        """
        Args:
            vad_aggressiveness: WebRTC VAD 强度，0-3，越大越严格
        """
        if not 0 <= vad_aggressiveness <= 3:
            vad_aggressiveness = 2
        self.vad = webrtcvad.Vad(vad_aggressiveness)
        self.prosody_analyzer = ProsodyAnalyzer() if is_parselmouth_available() else None
        self.forced_aligner = ForcedAligner() if is_forced_aligner_available() else None

    @staticmethod
    def _safe_load_audio(audio_path: str, target_sr: Optional[int] = None) -> Tuple[np.ndarray, int]:
        """安全加载音频文件，返回 (samples, sr)

        Raises:
            ValueError: 文件不存在、无法解码或音频过短
        """
        path = Path(audio_path)
        if not path.exists():
            raise ValueError(f"音频文件不存在: {audio_path}")
        if not path.is_file():
            raise ValueError(f"路径不是文件: {audio_path}")

        try:
            y, sr = librosa.load(str(path), sr=target_sr, mono=True)
        except Exception as exc:
            raise ValueError(f"无法加载音频文件 {audio_path}: {exc}") from exc

        if y is None or y.size == 0:
            raise ValueError(f"音频文件为空或无法读取: {audio_path}")

        duration = float(len(y) / sr)
        if duration < _MIN_AUDIO_DURATION:
            raise ValueError(f"音频过短 ({duration:.3f}s)，无法分析")

        return y, sr

    @staticmethod
    def _ensure_vad_sample_rate(y: np.ndarray, sr: int) -> Tuple[np.ndarray, int]:
        """确保采样率符合 WebRTC VAD 要求"""
        if sr in _SUPPORTED_VAD_RATES:
            return y, sr
        try:
            y_resampled = librosa.resample(y, orig_sr=sr, target_sr=_VAD_TARGET_SR)
            return y_resampled, _VAD_TARGET_SR
        except Exception as exc:
            logger.warning(f"重采样到 {_VAD_TARGET_SR}Hz 失败: {exc}")
            return y, sr

    @staticmethod
    def _to_int16(samples: np.ndarray) -> np.ndarray:
        """将浮点音频 [-1, 1] 转换为 int16"""
        if samples.dtype == np.int16:
            return samples
        # 先裁剪到 [-1, 1] 防止溢出
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 32767).astype(np.int16)

    def calculate_speech_rate(self, text_count: int, speaking_duration: float, language: str) -> float:
        if speaking_duration <= 0 or text_count < 0:
            return 0.0
        return (text_count / speaking_duration) * 60

    def detect_pauses(self, samples: np.ndarray, sr: int, frame_duration_ms: int = 30) -> tuple:
        """Detect pauses using WebRTC VAD.

        Args:
            samples: int16 numpy array of audio samples
            sr: sample rate (must be one of 8k/16k/32k/48k)
            frame_duration_ms: frame size in ms (must be 10/20/30)
        """
        if samples is None or samples.size == 0:
            return 0, 0.0

        if frame_duration_ms not in (10, 20, 30):
            frame_duration_ms = 30

        if sr not in _SUPPORTED_VAD_RATES:
            logger.warning(f"VAD 不支持采样率 {sr}Hz，跳过停顿检测")
            return 0, 0.0

        frame_size = int(sr * frame_duration_ms / 1000)
        if frame_size == 0 or len(samples) < frame_size:
            return 0, 0.0

        pause_count = 0
        total_pause_duration = 0.0
        in_pause = False
        pause_start = 0.0

        for i in range(0, len(samples) - frame_size + 1, frame_size):
            frame = samples[i:i + frame_size].tobytes()
            try:
                is_speech = self.vad.is_speech(frame, sr)
            except Exception:
                # 单帧失败不影响整体，继续
                continue

            time_sec = i / sr

            if not is_speech and not in_pause:
                in_pause = True
                pause_start = time_sec
            elif is_speech and in_pause:
                in_pause = False
                pause_count += 1
                total_pause_duration += time_sec - pause_start

        # 结尾还在停顿中，计入最后一段
        if in_pause:
            total_pause_duration += (len(samples) / sr) - pause_start

        return pause_count, total_pause_duration

    def denoise_audio(self, y: np.ndarray, sr: int) -> np.ndarray:
        """简易音频降噪：使用谱减法"""
        if y is None or y.size == 0:
            return y
        try:
            # 取前0.5秒作为噪声样本（如果音频够长）
            noise_len = min(int(0.5 * sr), len(y) // 4)
            if noise_len < int(sr * 0.1):
                return y

            noise_sample = y[:noise_len]
            noise_stft = librosa.stft(noise_sample)
            noise_mag = np.mean(np.abs(noise_stft), axis=1, keepdims=True)

            # 全音频谱减
            stft = librosa.stft(y)
            mag = np.abs(stft)
            phase = np.angle(stft)

            # 谱减
            cleaned_mag = np.maximum(mag - 2 * noise_mag, 0)
            cleaned_stft = cleaned_mag * np.exp(1j * phase)
            y_clean = librosa.istft(cleaned_stft, length=len(y))

            return y_clean
        except Exception as exc:
            logger.warning(f"降噪失败，返回原音频: {exc}")
            return y

    def split_sentences(self, text: str, language: str) -> list:
        """按标点切分句子"""
        if not text or not text.strip():
            return []

        # 中文标点 + 英文标点
        if language == "chinese":
            # 按中文句号、问号、感叹号、分号切分
            parts = re.split(r'[。！？；!?;]+', text)
        elif language == "english":
            parts = re.split(r'[.!?;]+', text)
        else:
            # 混合：中英文标点都切
            parts = re.split(r'[。！？；!?;]+', text)

        # 清理空白
        sentences = [p.strip() for p in parts if p.strip()]
        return sentences

    def analyze_sentences(self, y: np.ndarray, sr: int, script_text: str, language: str,
                          total_duration: float) -> list:
        """逐句分析：按文本切分，估算每句的语速"""
        sentences = self.split_sentences(script_text, language)
        if not sentences or total_duration <= 0 or y is None or y.size == 0:
            return []

        # 按句子数量均分音频时长（简化方案）
        # 更精确的做法需要强制对齐，这里用均分作为近似
        results = []
        n = len(sentences)
        segment_duration = total_duration / n if n > 0 else total_duration

        # VAD 需要 int16 且采样率符合要求
        y_for_vad, sr_for_vad = self._ensure_vad_sample_rate(y, sr)
        y_int16 = self._to_int16(y_for_vad)

        for i, sentence in enumerate(sentences):
            start_time = i * segment_duration
            end_time = (i + 1) * segment_duration
            start_sample = int(start_time * sr_for_vad)
            end_sample = int(end_time * sr_for_vad)
            start_sample = max(0, min(start_sample, len(y_int16)))
            end_sample = max(0, min(end_sample, len(y_int16)))
            segment = y_int16[start_sample:end_sample]

            if len(segment) == 0:
                continue

            # 计算该段的停顿
            try:
                pause_count, pause_dur = self.detect_pauses(segment, sr_for_vad)
            except Exception:
                pause_count, pause_dur = 0, 0.0

            speaking_dur = max(0.1, segment_duration - pause_dur)

            # 计算该句字数
            if language == "chinese":
                char_count = count_chinese_chars(sentence)
            elif language == "english":
                char_count = count_english_words(sentence)
            else:
                char_count = count_chinese_chars(sentence) + count_english_words(sentence)

            rate = self.calculate_speech_rate(char_count, speaking_dur, language)

            results.append({
                "index": i + 1,
                "sentence": sentence[:50] + ("..." if len(sentence) > 50 else ""),
                "char_count": char_count,
                "rate": round(rate, 1),
                "pause_count": pause_count,
                "pause_duration": round(pause_dur, 2),
                "start_time": round(start_time, 2),
                "end_time": round(end_time, 2),
            })

        return results

    def get_waveform_data(self, y: np.ndarray, max_points: int = 2000) -> list:
        """获取波形数据（降采样用于可视化）"""
        if y is None or y.size == 0:
            return []
        if max_points <= 0:
            max_points = 2000

        if len(y) > max_points:
            # 降采样
            step = len(y) // max_points
            y_down = y[::step]
        else:
            y_down = y

        # 归一化到 -1 到 1
        max_val = float(np.max(np.abs(y_down))) if y_down.size > 0 else 0.0
        if max_val <= 0:
            return [0.0] * len(y_down)
        y_norm = y_down / max_val

        return y_norm.tolist()

    def get_spectrogram_data(self, y: np.ndarray, sr: int) -> dict:
        """获取梅尔频谱图数据"""
        if y is None or y.size == 0 or sr <= 0:
            return {"data": [], "n_mels": 0, "n_frames": 0, "sr": sr}
        try:
            # 计算梅尔频谱
            S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=64, fmax=8000)
            S_dB = librosa.power_to_db(S, ref=np.max)

            # 降采样：时间轴取 100 个点
            n_time = S_dB.shape[1]
            if n_time > 100:
                step = n_time // 100
                S_dB = S_dB[:, ::step]

            return {
                "data": S_dB.tolist(),
                "n_mels": S_dB.shape[0],
                "n_frames": S_dB.shape[1],
                "sr": sr
            }
        except Exception as exc:
            logger.warning(f"频谱图计算失败: {exc}")
            return {"data": [], "n_mels": 0, "n_frames": 0, "sr": sr}

    def analyze(self, audio_path: str, script_text: str, language: str,
                denoise: bool = False) -> dict:
        """分析音频

        Returns:
            dict: 包含各项分析结果。任一子模块失败都会降级返回 None 或空值，
                  不会导致整个分析崩溃。
        """
        # 加载音频
        try:
            y, sr = self._safe_load_audio(audio_path)
            duration = float(len(y) / sr)
        except Exception as exc:
            logger.error(f"音频加载失败: {exc}")
            return {
                "speech_rate": 0.0,
                "pause_count": 0,
                "total_pause_duration": 0.0,
                "rms_energy": 0.0,
                "mfcc_features": None,
                "spectral_features": None,
                "sentence_analysis_json": None,
                "waveform": [],
                "spectrogram": {"data": [], "n_mels": 0, "n_frames": 0, "sr": 0},
                "duration": 0.0,
                "prosody": None,
                "alignment": None,
                "error": str(exc),
            }

        # 降噪
        if denoise:
            y = self.denoise_audio(y, sr)

        # 停顿检测：确保采样率符合 VAD 要求
        try:
            y_for_vad, sr_for_vad = self._ensure_vad_sample_rate(y, sr)
            y_int16 = self._to_int16(y_for_vad)
            pause_count, total_pause_duration = self.detect_pauses(y_int16, sr_for_vad)
        except Exception as exc:
            logger.warning(f"停顿检测失败: {exc}")
            pause_count, total_pause_duration = 0, 0.0

        # Guard against negative speaking duration
        speaking_duration = max(0.1, duration - total_pause_duration)

        # Count text
        if language == "chinese":
            text_count = count_chinese_chars(script_text)
        elif language == "english":
            text_count = count_english_words(script_text)
        else:
            text_count = count_chinese_chars(script_text) + count_english_words(script_text)

        # Speech rate
        speech_rate = self.calculate_speech_rate(text_count, speaking_duration, language)

        # RMS energy
        try:
            rms_energy = float(np.mean(librosa.feature.rms(y=y)))
        except Exception:
            rms_energy = 0.0

        # MFCC features —统一用 float64 存储
        try:
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            mfcc_features = np.mean(mfcc, axis=1).astype(np.float64).tobytes()
        except Exception as exc:
            logger.warning(f"MFCC 提取失败: {exc}")
            mfcc_features = None

        # Spectral features
        try:
            spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
            spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)
            spectral_features = np.array([
                np.mean(spectral_centroid), np.mean(spectral_bandwidth)
            ]).astype(np.float64).tobytes()
        except Exception as exc:
            logger.warning(f"谱特征提取失败: {exc}")
            spectral_features = None

        # 逐句分析
        try:
            sentence_analysis = self.analyze_sentences(y, sr, script_text, language, duration)
            sentence_analysis_json = json.dumps(sentence_analysis, ensure_ascii=False) if sentence_analysis else None
        except Exception as exc:
            logger.warning(f"逐句分析失败: {exc}")
            sentence_analysis_json = None

        # 波形和频谱图数据（用于可视化）
        try:
            waveform = self.get_waveform_data(y)
        except Exception:
            waveform = []
        try:
            spectrogram = self.get_spectrogram_data(y, sr)
        except Exception:
            spectrogram = {"data": [], "n_mels": 0, "n_frames": 0, "sr": sr}

        # 韵律特征
        prosody = None
        if self.prosody_analyzer is not None:
            try:
                prosody = self.prosody_analyzer.analyze(y, sr, language).to_dict()
            except Exception as exc:
                logger.warning(f"韵律分析失败: {exc}")
                prosody = None

        # 强制对齐（字/词级时间戳）
        alignment = None
        if self.forced_aligner is not None and script_text and script_text.strip():
            try:
                lang_code = "zh" if language == "chinese" else ("en" if language == "english" else None)
                align_result = self.forced_aligner.align(audio_path, script_text, language=lang_code)
                if align_result and not align_result.error:
                    alignment = align_result.to_dict()
            except Exception as exc:
                logger.warning(f"强制对齐失败: {exc}")
                alignment = None

        return {
            "speech_rate": speech_rate,
            "pause_count": pause_count,
            "total_pause_duration": total_pause_duration,
            "rms_energy": rms_energy,
            "mfcc_features": mfcc_features,
            "spectral_features": spectral_features,
            "sentence_analysis_json": sentence_analysis_json,
            "waveform": waveform,
            "spectrogram": spectrogram,
            "duration": duration,
            "prosody": prosody,
            "alignment": alignment,
        }
