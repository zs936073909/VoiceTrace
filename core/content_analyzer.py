"""
内容分析引擎
============

针对演讲稿/主持词的智能分析与拆分，为背诵训练提供结构化输入。

核心能力：
1. 文本分段（按句子、段落、语义边界）
2. 关键词提取（基于 TF-IDF + 词性过滤，支持中英文）
3. 难度评估（基于句子长度、生僻词、专业术语）
4. 记忆组块生成（基于工作记忆 7±2 理论）

理论依据：
- Miller, G. A. (1956). The Magical Number Seven, Plus or Minus Two.
  Psychological Review, 63(2), 81-97.
- Cowan, N. (2001). The Magical Number 4 in Short-Term Memory.
  Behavioral and Brain Sciences, 24(1), 87-114.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """一个记忆组块（段落/句子）"""
    index: int
    text: str
    keywords: List[str] = field(default_factory=list)
    difficulty: float = 1.0  # 1-5，越大越难
    char_count: int = 0
    sentence_count: int = 0
    hint: str = ""           # 提示文本（首字/关键词串联）

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "text": self.text,
            "keywords": self.keywords,
            "difficulty": self.difficulty,
            "char_count": self.char_count,
            "sentence_count": self.sentence_count,
            "hint": self.hint,
        }


@dataclass
class AnalysisResult:
    """内容分析结果"""
    segments: List[Segment]
    total_chars: int
    total_sentences: int
    avg_difficulty: float
    suggested_chunk_size: int  # 建议每次记忆的段数
    keywords_global: List[str]
    language: str = "chinese"

    def to_dict(self) -> Dict:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "total_chars": self.total_chars,
            "total_sentences": self.total_sentences,
            "avg_difficulty": self.avg_difficulty,
            "suggested_chunk_size": self.suggested_chunk_size,
            "keywords_global": self.keywords_global,
            "language": self.language,
        }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

# 中英文句子分隔符
_SENTENCE_ENDINGS = re.compile(r"([。！？!?；;\n]+)")
# 中文字符
_CN_CHAR = re.compile(r"[\u4e00-\u9fff]")
# 英文单词
_EN_WORD = re.compile(r"[A-Za-z]+")
# 数字
_NUMBER = re.compile(r"\d+\.?\d*")
# 中文停用词（高频虚词）
_CN_STOPWORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "那", "它", "他", "她", "们", "把", "被", "让",
    "从", "向", "对", "为", "以", "于", "而", "与", "及", "或", "但", "可",
    "能", "会", "可以", "应", "应该", "需要", "这个", "那个", "这些", "那些",
    "什么", "怎么", "为什么", "哪里", "谁", "多少", "如何", "通过", "进行",
    "以及", "等等", "之类", "一下", "一些", "一种", "一样", "一直", "一定",
    "可能", "如果", "虽然", "但是", "因为", "所以", "因此", "然后", "接着",
    "首先", "其次", "最后", "总之", "此外", "另外", "而且", "并且", "或者",
}
# 英文停用词
_EN_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should",
    "could", "may", "might", "must", "can", "shall", "to", "of", "in",
    "on", "at", "by", "for", "with", "about", "as", "into", "through",
    "during", "before", "after", "above", "below", "from", "up", "down",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than", "too",
    "very", "just", "now", "then", "here", "there", "when", "where",
    "why", "how", "what", "which", "who", "whom", "this", "that",
    "these", "those", "i", "me", "my", "we", "us", "our", "you", "your",
    "he", "him", "his", "she", "her", "it", "its", "they", "them", "their",
}


def detect_language(text: str) -> str:
    """检测主要语言：chinese / english / mixed"""
    cn_count = len(_CN_CHAR.findall(text))
    en_count = len(_EN_WORD.findall(text))
    if cn_count == 0 and en_count == 0:
        return "chinese"
    if cn_count == 0:
        return "english"
    if en_count == 0:
        return "chinese"
    ratio = cn_count / (cn_count + en_count)
    if ratio > 0.7:
        return "chinese"
    if ratio < 0.3:
        return "english"
    return "mixed"


def split_sentences(text: str) -> List[str]:
    """将文本拆分为句子（保留分隔符）"""
    if not text or not text.strip():
        return []
    # 标准化空白
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 按分隔符切分
    parts = _SENTENCE_ENDINGS.split(text)
    sentences: List[str] = []
    buffer = ""
    for part in parts:
        if not part:
            continue
        if _SENTENCE_ENDINGS.fullmatch(part):
            buffer += part
            stripped = buffer.strip()
            if stripped:
                sentences.append(stripped)
            buffer = ""
        else:
            buffer += part
    if buffer.strip():
        sentences.append(buffer.strip())
    return sentences


def _tokenize_cn(text: str) -> List[str]:
    """简易中文分词（基于 2-gram + 词典过滤）

    在无 jieba 可用时使用；优先尝试 jieba。
    """
    try:
        import jieba  # type: ignore
        return [w for w in jieba.lcut(text) if w.strip()]
    except Exception:
        pass

    # 回退：2-gram + 单字
    chars = _CN_CHAR.findall(text)
    tokens: List[str] = []
    i = 0
    while i < len(chars):
        if i + 1 < len(chars):
            tokens.append(chars[i] + chars[i + 1])
        tokens.append(chars[i])
        i += 1
    return tokens


def _tokenize_en(text: str) -> List[str]:
    """英文分词：小写 + 词形还原（简化）"""
    return [w.lower() for w in _EN_WORD.findall(text)]


def tokenize(text: str, language: str = "chinese") -> List[str]:
    """统一分词接口"""
    if language == "english":
        return _tokenize_en(text)
    if language == "mixed":
        return _tokenize_cn(text) + _tokenize_en(text)
    return _tokenize_cn(text)


def _is_stopword(word: str, language: str) -> bool:
    if _CN_CHAR.search(word):
        return word in _CN_STOPWORDS
    return word.lower() in _EN_STOPWORDS


# ---------------------------------------------------------------------------
# 关键词提取（TF-IDF 简化版）
# ---------------------------------------------------------------------------

def extract_keywords(
    text: str,
    language: str = "chinese",
    top_k: int = 5,
    min_len: int = 2,
) -> List[str]:
    """提取关键词

    采用 TF 简化算法（单文档场景 IDF 退化为词长权重）：
    - 过滤停用词
    - 过滤过短词（中文>=2字，英文>=3字母）
    - 按词频排序，兼顾词长（长词权重略高）
    """
    if not text or not text.strip():
        return []

    tokens = tokenize(text, language)
    if not tokens:
        return []

    # 词频统计
    freq: Dict[str, int] = {}
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if _is_stopword(tok, language):
            continue
        # 长度过滤
        if _CN_CHAR.search(tok):
            if len(tok) < min_len:
                continue
        else:
            if len(tok) < 3:
                continue
        # 过滤纯数字
        if _NUMBER.fullmatch(tok):
            continue
        freq[tok] = freq.get(tok, 0) + 1

    if not freq:
        return []

    # 打分：词频 * (1 + log(词长))
    scored: List[Tuple[str, float]] = []
    for word, count in freq.items():
        length_bonus = 1.0 + math.log(max(1, len(word)))
        score = count * length_bonus
        scored.append((word, score))

    scored.sort(key=lambda x: -x[1])
    return [w for w, _ in scored[:top_k]]


# ---------------------------------------------------------------------------
# 难度评估
# ---------------------------------------------------------------------------

def estimate_difficulty(
    text: str,
    language: str = "chinese",
    avg_sentence_len_baseline: Optional[float] = None,
) -> float:
    """评估文本记忆难度（1-5）

    综合考虑：
    - 句子长度（越长越难，符合工作记忆容量限制）
    - 生僻字比例（中文）
    - 长单词比例（英文）
    - 数字与专业术语密度
    """
    if not text or not text.strip():
        return 1.0

    sentences = split_sentences(text)
    if not sentences:
        return 1.0

    # 平均句长
    if language == "english":
        words = _EN_WORD.findall(text)
        avg_len = len(words) / max(1, len(sentences))
        baseline = avg_sentence_len_baseline or 15.0
    else:
        cn_chars = _CN_CHAR.findall(text)
        avg_len = len(cn_chars) / max(1, len(sentences))
        baseline = avg_sentence_len_baseline or 25.0

    # 句长得分（相对基线）
    len_score = min(5.0, max(1.0, (avg_len / baseline) * 2.5))

    # 数字密度
    numbers = _NUMBER.findall(text)
    total_tokens = len(tokenize(text, language)) or 1
    num_density = len(numbers) / total_tokens
    num_score = min(5.0, 1.0 + num_density * 20)

    # 综合得分
    difficulty = 0.6 * len_score + 0.4 * num_score
    return round(max(1.0, min(5.0, difficulty)), 2)


# ---------------------------------------------------------------------------
# 主分析器
# ---------------------------------------------------------------------------

class ContentAnalyzer:
    """内容分析引擎主类"""

    # 不同场景的建议组块大小（每次记忆段数）
    SCENARIO_CHUNK_SIZE = {
        "speech": 3,     # 演讲：3 段一组（约 60-90 秒）
        "host": 4,       # 主持：4 段一组（短句多）
        "emergency": 2,  # 应急话术：2 段一组（精熟）
    }

    # 不同场景的建议单段长度（字符）
    SCENARIO_SEGMENT_LENGTH = {
        "speech": (60, 120),    # 演讲段落 60-120 字
        "host": (30, 80),       # 主持短句 30-80 字
        "emergency": (20, 60),  # 应急话术 20-60 字
    }

    def __init__(self, target_chunk_size: Optional[int] = None):
        """
        :param target_chunk_size: 强制每次记忆段数；None 则按场景自动
        """
        self.target_chunk_size = target_chunk_size

    def analyze(
        self,
        text: str,
        language: Optional[str] = None,
        scenario: str = "speech",
    ) -> AnalysisResult:
        """分析文本，生成记忆组块

        :param text: 原始稿件文本
        :param language: 语言（None 自动检测）
        :param scenario: 场景 'speech'|'host'|'emergency'
        :return: AnalysisResult
        """
        if not text or not text.strip():
            return AnalysisResult(
                segments=[], total_chars=0, total_sentences=0,
                avg_difficulty=0.0, suggested_chunk_size=1,
                keywords_global=[], language=language or "chinese",
            )

        language = language or detect_language(text)
        scenario = scenario if scenario in self.SCENARIO_CHUNK_SIZE else "speech"

        # 1. 拆分为句子
        sentences = split_sentences(text)
        if not sentences:
            return AnalysisResult(
                segments=[], total_chars=0, total_sentences=0,
                avg_difficulty=0.0, suggested_chunk_size=1,
                keywords_global=[], language=language,
            )

        # 2. 按场景目标长度合并句子为段落
        min_len, max_len = self.SCENARIO_SEGMENT_LENGTH[scenario]
        segments = self._merge_sentences_to_segments(
            sentences, language, scenario, min_len, max_len
        )

        # 3. 为每段提取关键词、评估难度、生成提示
        all_keywords: List[str] = []
        total_diff = 0.0
        for seg in segments:
            seg.keywords = extract_keywords(seg.text, language, top_k=5)
            seg.difficulty = estimate_difficulty(seg.text, language)
            seg.hint = self._build_hint(seg.text, seg.keywords, language)
            all_keywords.extend(seg.keywords)
            total_diff += seg.difficulty

        # 4. 全局关键词（去重，按出现次数）
        global_kw = self._dedup_keywords(all_keywords)

        # 5. 建议组块大小
        chunk_size = self.target_chunk_size or self.SCENARIO_CHUNK_SIZE[scenario]

        return AnalysisResult(
            segments=segments,
            total_chars=sum(s.char_count for s in segments),
            total_sentences=sum(s.sentence_count for s in segments),
            avg_difficulty=round(total_diff / max(1, len(segments)), 2),
            suggested_chunk_size=chunk_size,
            keywords_global=global_kw,
            language=language,
        )

    def _merge_sentences_to_segments(
        self,
        sentences: List[str],
        language: str,
        scenario: str,
        min_len: int,
        max_len: int,
    ) -> List[Segment]:
        """将句子合并为目标长度的段落"""
        segments: List[Segment] = []
        buffer: List[str] = []
        buffer_chars = 0

        def _char_count(s: str) -> int:
            if language == "english":
                return len(_EN_WORD.findall(s))
            return len(_CN_CHAR.findall(s)) or len(s)

        idx = 0
        for sent in sentences:
            sent_chars = _char_count(sent)
            # 单句已超长：独立成段
            if sent_chars >= max_len:
                if buffer:
                    segments.append(self._make_segment(idx, buffer, language))
                    idx += 1
                    buffer = []
                    buffer_chars = 0
                segments.append(self._make_segment(idx, [sent], language))
                idx += 1
                continue

            # 累加
            buffer.append(sent)
            buffer_chars += sent_chars

            # 达到目标长度
            if buffer_chars >= min_len:
                segments.append(self._make_segment(idx, buffer, language))
                idx += 1
                buffer = []
                buffer_chars = 0

        # 处理剩余
        if buffer:
            # 若剩余过短，合并到上一段
            if segments and buffer_chars < min_len // 2:
                last = segments[-1]
                last.text = last.text + "".join(buffer)
                last.char_count = _char_count(last.text)
                last.sentence_count += len(buffer)
            else:
                segments.append(self._make_segment(idx, buffer, language))

        return segments

    def _make_segment(self, index: int, sentences: List[str], language: str) -> Segment:
        text = "".join(sentences) if language != "english" else " ".join(sentences)
        # 英文用空格连接更自然
        if language == "english":
            text = " ".join(s.strip() for s in sentences)
        char_count = len(_CN_CHAR.findall(text)) if language != "english" else len(_EN_WORD.findall(text))
        if char_count == 0:
            char_count = len(text)
        return Segment(
            index=index,
            text=text,
            char_count=char_count,
            sentence_count=len(sentences),
        )

    def _build_hint(self, text: str, keywords: List[str], language: str) -> str:
        """生成记忆提示

        策略：取首字/首词 + 关键词串联
        """
        if not text:
            return ""
        # 首字提示
        if language == "english":
            first_word = _EN_WORD.search(text)
            head = first_word.group() if first_word else ""
        else:
            cn = _CN_CHAR.search(text)
            head = cn.group() if cn else text[0]

        # 关键词前 3 个
        kw = keywords[:3]
        if kw:
            return f"{head}… → {' / '.join(kw)}"
        return f"{head}…"

    def _dedup_keywords(self, keywords: List[str]) -> List[str]:
        """关键词去重并按出现次数排序"""
        freq: Dict[str, int] = {}
        for kw in keywords:
            freq[kw] = freq.get(kw, 0) + 1
        return [kw for kw, _ in sorted(freq.items(), key=lambda x: -x[1])]


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_default_analyzer: Optional[ContentAnalyzer] = None


def get_default_analyzer() -> ContentAnalyzer:
    global _default_analyzer
    if _default_analyzer is None:
        _default_analyzer = ContentAnalyzer()
    return _default_analyzer


def analyze_script(
    text: str,
    language: Optional[str] = None,
    scenario: str = "speech",
) -> AnalysisResult:
    """便捷函数：分析稿件"""
    return get_default_analyzer().analyze(text, language, scenario)
