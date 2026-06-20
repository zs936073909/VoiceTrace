"""强制对齐模块

基于 faster-whisper 语音识别生成字/词级时间戳，
再通过最小编辑距离将识别文本映射回原始稿件文本，
实现每个字（中文）或每个词（英文）的精确时间对齐。
"""
import os
import re
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from pathlib import Path

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False


@dataclass
class AlignedToken:
    """对齐后的最小单元（中文字 或 英文词）"""
    text: str                    # 字/词内容
    start_time: float            # 开始时间（秒）
    end_time: float              # 结束时间（秒）
    confidence: Optional[float] = None  # 置信度（如有）
    is_missing: bool = False     # 是否未在音频中检测到（原文有但识别缺失）


@dataclass
class AlignedSentence:
    """对齐后的句子"""
    text: str
    start_time: float
    end_time: float
    tokens: List[AlignedToken] = field(default_factory=list)


@dataclass
class AlignmentResult:
    """整段录音的对齐结果"""
    sentences: List[AlignedSentence] = field(default_factory=list)
    language: Optional[str] = None
    language_probability: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "language": self.language,
            "language_probability": self.language_probability,
            "sentences": [
                {
                    "text": s.text,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "tokens": [
                        {
                            "text": t.text,
                            "start_time": t.start_time,
                            "end_time": t.end_time,
                            "confidence": t.confidence,
                            "is_missing": t.is_missing
                        }
                        for t in s.tokens
                    ]
                }
                for s in self.sentences
            ]
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AlignmentResult":
        result = cls(
            language=data.get("language"),
            language_probability=data.get("language_probability"),
            error=data.get("error")
        )
        for s in data.get("sentences", []):
            sentence = AlignedSentence(
                text=s["text"],
                start_time=s["start_time"],
                end_time=s["end_time"]
            )
            for t in s.get("tokens", []):
                sentence.tokens.append(AlignedToken(
                    text=t["text"],
                    start_time=t["start_time"],
                    end_time=t["end_time"],
                    confidence=t.get("confidence"),
                    is_missing=t.get("is_missing", False)
                ))
            result.sentences.append(sentence)
        return result


class ForcedAligner:
    """基于 faster-whisper 的强制对齐器"""

    # 模型大小：tiny(39MB) < base(74MB) < small(244MB) < medium(766MB)
    DEFAULT_MODEL = "base"

    def __init__(self, model_size: Optional[str] = None, device: str = "cpu"):
        if not FASTER_WHISPER_AVAILABLE:
            raise ImportError(
                "faster-whisper 未安装。请运行：pip install faster-whisper"
            )
        self.model_size = model_size or self.DEFAULT_MODEL
        self.device = device
        self._model: Optional[WhisperModel] = None

    def _get_model(self) -> WhisperModel:
        """懒加载模型，便于打包时延迟下载"""
        if self._model is None:
            # 设置 HF 镜像（中国大陆环境）
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type="int8"
            )
        return self._model

    def align(self, audio_path: str, script_text: str,
              language: Optional[str] = None) -> AlignmentResult:
        """对音频和文本进行强制对齐

        Args:
            audio_path: 音频文件路径
            script_text: 原始稿件文本
            language: 'zh'/'en' 或 None 自动检测

        Returns:
            AlignmentResult
        """
        if not Path(audio_path).exists():
            return AlignmentResult(error=f"音频文件不存在: {audio_path}")

        try:
            model = self._get_model()
            segments, info = model.transcribe(
                audio_path,
                beam_size=5,
                word_timestamps=True,
                language=language,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300)
            )
        except Exception as e:
            return AlignmentResult(error=f"识别失败: {e}")

        result = AlignmentResult(
            language=info.language,
            language_probability=info.language_probability
        )

        # 将识别出的 segments 扁平化为 token 列表
        recognized_tokens: List[Tuple[str, float, float, Optional[float]]] = []
        for segment in segments:
            if segment.words:
                for word in segment.words:
                    recognized_tokens.append((
                        word.word.strip(),
                        word.start,
                        word.end,
                        getattr(word, "probability", None)
                    ))
            else:
                # 没有字级时间戳时退回到 segment 级
                recognized_tokens.append((
                    segment.text.strip(),
                    segment.start,
                    segment.end,
                    None
                ))

        # 根据语言拆分原始文本为 token 列表
        if language == "en" or (info.language == "en"):
            script_tokens = self._tokenize_english(script_text)
        else:
            script_tokens = self._tokenize_chinese(script_text)

        # 最小编辑距离对齐
        aligned = self._align_tokens(
            script_tokens,
            recognized_tokens,
            language=language or info.language
        )

        # 按句子重新组合
        result.sentences = self._group_into_sentences(
            script_text, aligned, language=language or info.language
        )

        return result

    @staticmethod
    def _tokenize_chinese(text: str) -> List[str]:
        """中文：按字切分，保留标点"""
        tokens = []
        for ch in text:
            if ch.strip():
                tokens.append(ch)
        return tokens

    @staticmethod
    def _tokenize_english(text: str) -> List[str]:
        """英文：按空格和标点切分"""
        # 保留单词，去除多余空格
        tokens = re.findall(r"[a-zA-Z']+|[^\w\s]", text)
        return [t for t in tokens if t.strip()]

    def _align_tokens(self, script_tokens: List[str],
                      recognized_tokens: List[Tuple[str, float, float, Optional[float]]],
                      language: Optional[str]) -> List[AlignedToken]:
        """用动态规划做最小编辑距离对齐"""
        if not recognized_tokens:
            return [
                AlignedToken(text=t, start_time=0.0, end_time=0.0, is_missing=True)
                for t in script_tokens
            ]

        # 识别文本数组
        rec_texts = [t[0] for t in recognized_tokens]

        m, n = len(script_tokens), len(rec_texts)
        # dp[i][j] 表示 script[:i] 与 rec[:j] 对齐的最小代价
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                s_tok = script_tokens[i - 1]
                r_tok = rec_texts[j - 1]
                cost = 0 if self._token_match(s_tok, r_tok, language) else 1
                dp[i][j] = min(
                    dp[i - 1][j - 1] + cost,  # 匹配/替换
                    dp[i - 1][j] + 1,          # 删除（script 有，rec 无）
                    dp[i][j - 1] + 1           # 插入（rec 有，script 无）
                )

        # 回溯对齐
        aligned: List[AlignedToken] = []
        i, j = m, n
        while i > 0 or j > 0:
            if i > 0 and j > 0:
                s_tok = script_tokens[i - 1]
                r_tok = rec_texts[j - 1]
                cost = 0 if self._token_match(s_tok, r_tok, language) else 1
                if dp[i][j] == dp[i - 1][j - 1] + cost:
                    if cost == 0:
                        aligned.append(AlignedToken(
                            text=s_tok,
                            start_time=recognized_tokens[j - 1][1],
                            end_time=recognized_tokens[j - 1][2],
                            confidence=recognized_tokens[j - 1][3]
                        ))
                    else:
                        # 替换：用识别到的时间，但标注原文
                        aligned.append(AlignedToken(
                            text=s_tok,
                            start_time=recognized_tokens[j - 1][1],
                            end_time=recognized_tokens[j - 1][2],
                            confidence=recognized_tokens[j - 1][3]
                        ))
                    i -= 1
                    j -= 1
                    continue

            if i > 0 and (j == 0 or dp[i][j] == dp[i - 1][j] + 1):
                # 删除：原文有但识别缺失
                aligned.append(AlignedToken(
                    text=script_tokens[i - 1],
                    start_time=0.0,
                    end_time=0.0,
                    is_missing=True
                ))
                i -= 1
                continue

            if j > 0 and (i == 0 or dp[i][j] == dp[i][j - 1] + 1):
                # 插入：识别出但原文没有，忽略
                j -= 1
                continue

            # 兜底
            break

        aligned.reverse()
        return aligned

    @staticmethod
    def _token_match(a: str, b: str, language: Optional[str]) -> bool:
        """判断两个 token 是否匹配"""
        a = a.strip().lower()
        b = b.strip().lower()
        if a == b:
            return True
        # 中文忽略标点差异
        if language != "en":
            a_clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", a)
            b_clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", b)
            if a_clean and a_clean == b_clean:
                return True
        return False

    @staticmethod
    def _group_into_sentences(script_text: str,
                              aligned_tokens: List[AlignedToken],
                              language: Optional[str]) -> List[AlignedSentence]:
        """将 token 按原文的句子结构分组"""
        # 按中英文句子结束符拆分原文，并记录每个字符所属的句子
        if language == "en":
            sentence_ends = re.compile(r"([.!?]+)")
        else:
            sentence_ends = re.compile(r"([。！？；])")

        # 简单做法：按句子结束符切分
        raw_parts = sentence_ends.split(script_text)
        sentences: List[str] = []
        i = 0
        while i < len(raw_parts):
            part = raw_parts[i]
            if i + 1 < len(raw_parts) and sentence_ends.match(raw_parts[i + 1]):
                part += raw_parts[i + 1]
                i += 2
            else:
                i += 1
            if part.strip():
                sentences.append(part.strip())

        if not sentences:
            if script_text.strip():
                sentences = [script_text.strip()]
            else:
                return []

        # 为每个字/词分配句子索引
        # 先按原文顺序将非空字符提取出来
        non_space_chars = []
        char_to_sentence = {}
        char_idx = 0
        for sent_idx, sent in enumerate(sentences):
            for ch in sent:
                if ch.strip():
                    non_space_chars.append(ch)
                    char_to_sentence[char_idx] = sent_idx
                    char_idx += 1

        result = [
            AlignedSentence(text=s, start_time=0.0, end_time=0.0)
            for s in sentences
        ]

        # 将 aligned_tokens 映射到句子
        token_idx = 0
        for char_idx, ch in enumerate(non_space_chars):
            if token_idx >= len(aligned_tokens):
                break
            token = aligned_tokens[token_idx]
            if ForcedAligner._token_match(token.text, ch, language):
                sent_idx = char_to_sentence.get(char_idx, 0)
                result[sent_idx].tokens.append(token)
                token_idx += 1

        # 计算每个句子的起止时间
        for sent in result:
            if sent.tokens:
                times = [t.start_time for t in sent.tokens if not t.is_missing]
                end_times = [t.end_time for t in sent.tokens if not t.is_missing]
                if times:
                    sent.start_time = min(times)
                    sent.end_time = max(end_times)

        return result


def is_forced_aligner_available() -> bool:
    return FASTER_WHISPER_AVAILABLE
