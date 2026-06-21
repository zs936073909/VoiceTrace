"""实时 AI 陪练核心模块

借鉴 RealtimeSTT / whisper_streaming 的滑动窗口 + VAD 断句思路，
但基于项目已有依赖（PySide6 + faster-whisper + webrtcvad）实现，
避免引入额外复杂依赖。

核心流程：
1. QAudioSource 实时采集麦克风音频
2. 音频推入线程安全队列
3. 后台线程：WebRTC VAD 检测有声段 → 滑动窗口 ASR → 实时特征提取
4. 检测到一段话结束（足够长静音）→ 调用 LLM 生成教练反馈
"""
import logging
import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any

import numpy as np


try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    QObject = object
    # 提供兼容 Signal，方便无 Qt 环境测试
    class _Signal:
        def connect(self, slot):
            self._slot = slot
        def emit(self, *args):
            if hasattr(self, "_slot"):
                self._slot(*args)
    Signal = _Signal


try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    WEBRTCVAD_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    import parselmouth
    PARSELMOUTH_AVAILABLE = True
except ImportError:
    PARSELMOUTH_AVAILABLE = False

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

from voicetrace.core.feedback_generator import FeedbackGenerator
from voicetrace.core.llm_service import LLMConfig

logger = logging.getLogger(__name__)


def _simple_alignment(script: str, recognized: str) -> Dict[str, Any]:
    """简易编辑距离对齐，返回差异统计"""
    try:
        from difflib import SequenceMatcher
        matcher = SequenceMatcher(None, script, recognized)
        matches = sum(block.size for block in matcher.get_matching_blocks())
        script_len = max(1, len(script))
        recognized_len = max(1, len(recognized))
        similarity = matches / max(script_len, recognized_len)
        return {
            "similarity": round(similarity, 3),
            "script_chars": script_len,
            "recognized_chars": recognized_len,
            "matched_chars": matches
        }
    except Exception:
        return {}


@dataclass
class CoachFrame:
    """实时帧数据"""
    level: float = 0.0          # 音量电平 0-100
    db: float = -100.0          # 分贝
    is_speech: bool = False     # 当前是否检测到语音
    instant_rate: float = 0.0   # 当前语速 (CPM/WPM)
    f0: float = 0.0             # 当前基频
    transcript: str = ""        # 当前识别文本


@dataclass
class CoachUtterance:
    """一次完整说话片段"""
    text: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    speech_duration: float = 0.0
    word_count: int = 0
    rate: float = 0.0           # CPM/WPM
    energy_mean: float = 0.0
    f0_mean: float = 0.0
    f0_std: float = 0.0
    pauses: int = 0
    alignment: Dict[str, Any] = field(default_factory=dict)


class RealtimeCoachSignals(QObject):
    """实时陪练信号"""
    frame_ready = Signal(object)       # CoachFrame
    utterance_ready = Signal(object)   # CoachUtterance
    feedback_ready = Signal(str)       # LLM 反馈文本
    status_changed = Signal(str)       # 状态文字
    error_occurred = Signal(str)       # 错误信息


class RealtimeCoach:
    """实时 AI 陪练

    注意：本类设计为与 Qt 主线程配合使用。start() 会在内部开启后台线程，
    通过 signals 与 UI 通信。调用 stop() 停止。
    """

    # 音频参数
    SAMPLE_RATE = 16000
    CHANNELS = 1
    SAMPLE_WIDTH = 2          # int16
    FRAME_DURATION_MS = 30    # WebRTC VAD 要求 10/20/30ms
    CHUNK_SECONDS = 1.5       # ASR 滑动窗口长度
    SILENCE_SECONDS = 0.8     # 判断一段话结束的静音长度
    VAD_AGGRESSIVENESS = 1    # 0-3，越大越严格

    def __init__(
        self,
        whisper_model: Optional[WhisperModel] = None,
        language: str = "chinese",
        llm_config: Optional[LLMConfig] = None,
        feedback_interval: int = 1,  # 每说完几句话调用一次 LLM
        script_text: str = ""
    ):
        self.signals = RealtimeCoachSignals()
        self.language = language
        self.script_text = script_text.strip()
        self.feedback_interval = max(1, feedback_interval)

        # ASR 模型
        if whisper_model is not None:
            self._model = whisper_model
            self._owns_model = False
        else:
            if not WHISPER_AVAILABLE:
                raise ImportError("faster-whisper 未安装")
            self._model = WhisperModel("base", device="cpu", compute_type="int8")
            self._owns_model = True

        # VAD
        if not WEBRTCVAD_AVAILABLE:
            raise ImportError("webrtcvad 未安装")
        self._vad = webrtcvad.Vad(self.VAD_AGGRESSIVENESS)

        # LLM 反馈生成器
        self._feedback_generator = FeedbackGenerator(llm_config)
        self._llm_config = llm_config

        # 线程与队列
        self._audio_queue: queue.Queue[bytes] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 状态
        self.is_running = False
        self._start_time = 0.0
        self._utterance_count = 0
        self._recent_utterances: deque = deque(maxlen=3)

        # 音频缓冲
        self._ring_buffer = bytearray()
        self._speech_buffer = bytearray()
        self._silence_frames = 0
        self._in_speech = False
        self._utterance_start_time = 0.0
        self._frame_level_history: deque = deque(maxlen=50)

    def start(self):
        """启动后台处理线程"""
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        self.signals.status_changed.emit("陪练已启动，请开始朗读...")

    def stop(self):
        """停止处理线程"""
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self.signals.status_changed.emit("陪练已停止")

    def feed_audio(self, data: bytes):
        """主线程调用：把音频数据喂给陪练模块"""
        if not self.is_running:
            return
        try:
            self._audio_queue.put(data, block=False)
        except queue.Full:
            pass

    def set_llm_config(self, config: LLMConfig):
        """动态更新 LLM 配置"""
        self._llm_config = config
        self._feedback_generator.set_llm_config(config)

    def _process_loop(self):
        """后台处理循环"""
        while not self._stop_event.is_set():
            try:
                data = self._audio_queue.get(timeout=0.05)
            except queue.Empty:
                # 没有新数据也尝试处理已有缓冲（用于触发句尾检测）
                data = b""

            if data:
                self._ring_buffer.extend(data)
                frame = self._extract_frame(data)
                if frame is not None:
                    self._frame_level_history.append(frame)
                    self.signals.frame_ready.emit(frame)

            # 处理 ASR 和断句（约每 100ms 检查一次）
            self._process_speech()

        # 结束前处理剩余缓冲
        if self._speech_buffer:
            self._finish_utterance()

    def _extract_frame(self, data: bytes) -> Optional[CoachFrame]:
        """从原始音频中提取一帧特征"""
        try:
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if samples.size == 0:
                return None

            rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
            if rms > 0:
                db = 20 * math.log10(rms / 32768.0)
                level = int((db + 60) / 57 * 100)
                level = max(0, min(100, level))
            else:
                db = -100.0
                level = 0

            # VAD 需要 30ms 的整数倍数据
            frame_len = int(self.SAMPLE_RATE * self.FRAME_DURATION_MS / 1000) * self.SAMPLE_WIDTH
            if len(data) >= frame_len:
                vad_frame = data[:frame_len]
                is_speech = self._vad.is_speech(vad_frame, self.SAMPLE_RATE)
            else:
                is_speech = level > 10

            # 计算瞬时 F0（可选）
            f0 = 0.0
            if LIBROSA_AVAILABLE and samples.size > 1024 and level > 15:
                try:
                    f0s = librosa.yin(
                        samples / 32768.0,
                        fmin=80,
                        fmax=400,
                        sr=self.SAMPLE_RATE
                    )
                    valid = f0s[f0s > 0]
                    if valid.size:
                        f0 = float(np.median(valid))
                except Exception:
                    pass

            # 瞬时语速：基于最近有声段估算
            instant_rate = self._estimate_instant_rate()

            return CoachFrame(
                level=level,
                db=db,
                is_speech=is_speech,
                instant_rate=instant_rate,
                f0=f0,
                transcript=""
            )
        except Exception as exc:
            logger.debug(f"提取实时帧失败: {exc}")
            return None

    def _estimate_instant_rate(self) -> float:
        """估算最近 3 秒内的瞬时语速"""
        if not self._frame_level_history:
            return 0.0
        recent = list(self._frame_level_history)[-30:]  # 约 3 秒
        speech_frames = [f for f in recent if f.is_speech]
        if not speech_frames:
            return 0.0
        # 粗略估算：有声帧比例越高，语速越快（结合后续 ASR 修正）
        ratio = len(speech_frames) / len(recent)
        # 中文正常语速约 250 CPM，映射 ratio 到 0-350
        return ratio * 300.0

    def _process_speech(self):
        """处理语音段和断句"""
        frame_len = int(self.SAMPLE_RATE * self.FRAME_DURATION_MS / 1000) * self.SAMPLE_WIDTH
        if len(self._ring_buffer) < frame_len:
            return

        # 取一个 VAD 帧
        frame_bytes = bytes(self._ring_buffer[:frame_len])
        self._ring_buffer = self._ring_buffer[frame_len:]

        try:
            is_speech = self._vad.is_speech(frame_bytes, self.SAMPLE_RATE)
        except Exception:
            is_speech = False

        silence_frames_threshold = int(self.SILENCE_SECONDS * 1000 / self.FRAME_DURATION_MS)

        if is_speech:
            self._speech_buffer.extend(frame_bytes)
            self._silence_frames = 0
            if not self._in_speech:
                self._in_speech = True
                self._utterance_start_time = time.time() - self._start_time
        else:
            if self._in_speech:
                self._speech_buffer.extend(frame_bytes)
                self._silence_frames += 1
                if self._silence_frames >= silence_frames_threshold:
                    self._finish_utterance()

    def _finish_utterance(self):
        """完成当前话语段，进行 ASR 和反馈"""
        if len(self._speech_buffer) < self.SAMPLE_RATE * 0.3 * self.SAMPLE_WIDTH:
            # 太短，忽略
            self._reset_utterance()
            return

        audio_bytes = bytes(self._speech_buffer)
        self._reset_utterance()

        end_time = time.time() - self._start_time
        duration = max(0.1, end_time - self._utterance_start_time)

        try:
            utterance = self._transcribe_utterance(audio_bytes, self._utterance_start_time, end_time, duration)
        except Exception as exc:
            logger.warning(f"实时 ASR 失败: {exc}")
            return

        self._recent_utterances.append(utterance)
        self._utterance_count += 1
        self.signals.utterance_ready.emit(utterance)

        # 每 N 句话或一段话较长时生成 LLM 反馈
        if self._llm_config and self._llm_config.api_key and self._utterance_count % self.feedback_interval == 0:
            self._generate_feedback()

    def _reset_utterance(self):
        self._speech_buffer = bytearray()
        self._silence_frames = 0
        self._in_speech = False

    def _transcribe_utterance(
        self,
        audio_bytes: bytes,
        start_time: float,
        end_time: float,
        duration: float
    ) -> CoachUtterance:
        """对一段语音做 ASR 和特征提取"""
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # ASR
        lang_code = "zh" if self.language == "chinese" else "en"
        segments, _ = self._model.transcribe(
            samples,
            language=lang_code,
            beam_size=1,
            best_of=1,
            condition_on_previous_text=True,
            vad_filter=False,  # 已经用 WebRTC VAD 分好段
            word_timestamps=False
        )
        text = " ".join([seg.text.strip() for seg in segments]).strip()

        # 基础特征
        energy = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
        speech_samples = samples[np.abs(samples) > 0.01]
        speech_duration = len(speech_samples) / self.SAMPLE_RATE if speech_samples.size else 0.0

        # 计算字数/词数
        if self.language == "chinese":
            word_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
            word_count = max(1, word_count)
        else:
            word_count = max(1, len(text.split()))

        rate = word_count / (speech_duration / 60.0) if speech_duration > 0 else 0.0

        # F0
        f0_mean = 0.0
        f0_std = 0.0
        if PARSELMOUTH_AVAILABLE and samples.size > 1024:
            try:
                snd = parselmouth.Sound(samples, sampling_frequency=self.SAMPLE_RATE)
                pitch = snd.to_pitch()
                f0_values = pitch.selected_array['frequency']
                valid = f0_values[f0_values > 0]
                if valid.size:
                    f0_mean = float(np.mean(valid))
                    f0_std = float(np.std(valid))
            except Exception:
                pass

        # 与稿件对齐（如果有稿件）
        alignment = {}
        if self.script_text and text:
            try:
                alignment = _simple_alignment(self.script_text[:200], text[:200])
            except Exception:
                pass

        # 停顿次数：基于能量低于阈值的片段
        pauses = self._count_pauses(samples)

        return CoachUtterance(
            text=text,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            speech_duration=speech_duration,
            word_count=word_count,
            rate=rate,
            energy_mean=energy,
            f0_mean=f0_mean,
            f0_std=f0_std,
            pauses=pauses,
            alignment=alignment
        )

    def _count_pauses(self, samples: np.ndarray, threshold: float = 0.015, min_pause_sec: float = 0.3) -> int:
        """统计停顿次数"""
        if samples.size == 0:
            return 0
        frame_size = int(self.SAMPLE_RATE * 0.02)
        energies = np.array([
            np.sqrt(np.mean(samples[i:i+frame_size] ** 2))
            for i in range(0, len(samples) - frame_size, frame_size)
        ])
        below = energies < threshold
        pause_frames = 0
        pauses = 0
        for b in below:
            if b:
                pause_frames += 1
            else:
                if pause_frames * 0.02 >= min_pause_sec:
                    pauses += 1
                pause_frames = 0
        if pause_frames * 0.02 >= min_pause_sec:
            pauses += 1
        return pauses

    def _generate_feedback(self):
        """调用 LLM 生成阶段性反馈"""
        if not self._recent_utterances:
            return

        # 汇总最近几句话
        combined_text = " ".join([u.text for u in self._recent_utterances])
        total_words = sum(u.word_count for u in self._recent_utterances)
        total_speech_dur = sum(u.speech_duration for u in self._recent_utterances)
        avg_rate = total_words / (total_speech_dur / 60.0) if total_speech_dur > 0 else 0.0
        avg_f0 = np.mean([u.f0_mean for u in self._recent_utterances if u.f0_mean > 0]) or 0.0
        f0_std = np.mean([u.f0_std for u in self._recent_utterances if u.f0_std > 0]) or 0.0
        total_pauses = sum(u.pauses for u in self._recent_utterances)

        # 构造一个精简的 result dict，复用 FeedbackGenerator
        result = {
            "speech_rate": float(avg_rate),
            "pause_count": total_pauses,
            "total_pause_duration": 0.0,
            "rms_energy": float(np.mean([u.energy_mean for u in self._recent_utterances])),
            "duration": float(sum(u.duration for u in self._recent_utterances)),
            "prosody": {
                "f0_mean": float(avg_f0),
                "f0_std": float(f0_std),
            },
            "alignment": None,
            "sentence_analysis_json": "[]"
        }

        try:
            feedback = self._feedback_generator.generate(
                result=result,
                script_content=self.script_text,
                script_language=self.language,
                script_category="realtime_coach",
                use_llm=True
            )
            summary = feedback.get("summary", "")
            suggestions = feedback.get("suggestions", "")
            drills = feedback.get("drills", "")
            parts = [f"**整体评价**：{summary}"]
            if suggestions:
                parts.append(f"**改进建议**：{suggestions}")
            if drills:
                parts.append(f"**针对性练习**：{drills}")
            self.signals.feedback_ready.emit("\n\n".join(parts))
        except Exception as exc:
            logger.warning(f"LLM 反馈生成失败: {exc}")

    def __del__(self):
        self.stop()
        if self._owns_model and hasattr(self, "_model"):
            self._model = None
