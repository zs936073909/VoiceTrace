"""
FSRS 间隔重复调度引擎
=====================

基于 Free Spaced Repetition Scheduler (FSRS-5) 算法，
跟踪每张记忆卡片的三变量记忆状态：
- Difficulty (D): 卡片难度 1-10
- Stability  (S): 记忆稳定性（天数，R 从 100% 衰减到 90% 所需）
- Retrievability (R): 当前可检索性（0-1）

优先使用 py-fsrs 官方实现；若未安装则回退到内置简化版实现，
保证核心调度能力可用。

参考文献：
- Ye, J. (2023). Optimizing Spaced Repetition Schedule by Capturing
  the Dynamics of Memory. IEEE TKDE.
- Roediger, H. L., & Karpicke, J. D. (2006). Test-Enhanced Learning.
  Psychological Science, 17(3), 249-255.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# 尝试导入官方 py-fsrs
try:
    from fsrs import Scheduler as _PyScheduler
    from fsrs import Card as _PyCard
    from fsrs import Rating as _PyRating
    from fsrs import State as _PyState
    _PY_FSRS_AVAILABLE = True
except Exception:  # pragma: no cover
    _PY_FSRS_AVAILABLE = False


class Rating(IntEnum):
    """用户对一张卡片的回忆评分"""
    Again = 1
    Hard = 2
    Good = 3
    Easy = 4


class State(IntEnum):
    """卡片当前所处状态"""
    New = 0
    Learning = 1
    Review = 2
    Relearning = 3


# FSRS-5 默认参数（21 个），来源：open-spaced-repetition/py-fsrs v4.x
DEFAULT_PARAMETERS: Tuple[float, ...] = (
    0.40255, 1.18385, 3.17300, 15.64540,
    7.21055, 0.53165, 1.06510, 0.02340,
    1.61600, 0.15430, 1.03175,
    0.65600, 0.12070, 1.28000, 0.74300,
    0.34000, 1.40000,
    0.20000, 0.20000, 0.40000,
    0.17000,
)

TARGET_RETRIEVABILITY_DEFAULT = 0.9


@dataclass
class MemoryCard:
    """一张记忆卡片（演讲稿分段、关键词、应急话术等）"""
    card_id: str
    script_id: Optional[int] = None
    segment_index: int = 0
    front: str = ""
    back: str = ""
    hint: str = ""

    state: int = State.New.value
    step: int = 0
    stability: float = 0.0
    difficulty: float = 0.0
    last_review: Optional[float] = None
    reps: int = 0
    lapses: int = 0
    created_at: float = field(default_factory=time.time)

    tags: List[str] = field(default_factory=list)
    scenario: str = "speech"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryCard":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class ReviewLog:
    """一次复习记录"""
    card_id: str
    rating: int
    review_duration: float = 0.0
    reviewed_at: float = field(default_factory=time.time)
    state_before: int = State.New.value
    state_after: int = State.New.value
    stability_before: float = 0.0
    stability_after: float = 0.0
    retrievability: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class _BuiltinScheduler:
    """FSRS-5 简化实现（py-fsrs 不可用时的回退）"""

    def __init__(
        self,
        parameters: Tuple[float, ...] = DEFAULT_PARAMETERS,
        desired_retention: float = TARGET_RETRIEVABILITY_DEFAULT,
        maximum_interval: int = 36500,
        enable_fuzzing: bool = False,
    ):
        if len(parameters) != 21:
            raise ValueError(f"FSRS 参数必须为 21 个，收到 {len(parameters)}")
        self.parameters = parameters
        self.desired_retention = max(0.7, min(0.99, desired_retention))
        self.maximum_interval = max(1, int(maximum_interval))
        self.enable_fuzzing = bool(enable_fuzzing)

    def get_card_retrievability(self, card: MemoryCard, now: Optional[float] = None) -> float:
        if card.state == State.New.value:
            return 0.0
        if card.last_review is None or card.stability <= 0:
            return 0.0
        now = now if now is not None else time.time()
        elapsed_days = max(0.0, (now - card.last_review) / 86400.0)
        decay = self.parameters[20]
        inner = 1.0 + elapsed_days / (9.0 * card.stability)
        r = inner ** (-1.0 / decay)
        return max(0.0, min(1.0, r))

    def _initial_stability(self, rating: Rating) -> float:
        return max(0.1, self.parameters[rating.value - 1])

    def _initial_difficulty(self, rating: Rating) -> float:
        d = self.parameters[4] - math.exp(self.parameters[5] * (rating.value - 1)) + 1.0
        return max(1.0, min(10.0, d))

    def _next_difficulty(self, d: float, rating: Rating) -> float:
        delta = -self.parameters[6] * (rating.value - 3)
        linear_damping = (10.0 - d) * delta / 9.0
        next_d = d + linear_damping
        next_d = self.parameters[7] * self._initial_difficulty(Rating.Easy) + (1 - self.parameters[7]) * next_d
        return max(1.0, min(10.0, next_d))

    def _next_recall_stability(self, d: float, s: float, r: float, rating: Rating) -> float:
        hard_penalty = self.parameters[15] if rating == Rating.Hard else 1.0
        easy_bonus = self.parameters[16] if rating == Rating.Easy else 1.0
        term = (math.exp(self.parameters[8])
                * (11.0 - d)
                * (s ** (-self.parameters[9]))
                * (math.exp((1.0 - r) * self.parameters[10]) - 1.0)
                * hard_penalty
                * easy_bonus)
        return max(0.1, s * (1.0 + term))

    def _next_forget_stability(self, d: float, s: float, r: float) -> float:
        term = (self.parameters[11]
                * (d ** (-self.parameters[12]))
                * (((s + 1.0) ** self.parameters[13]) - 1.0)
                * math.exp((1.0 - r) * self.parameters[14]))
        short_s = s / (math.exp(self.parameters[17] * self.parameters[18]))
        return max(0.1, min(term, short_s))

    def _next_interval(self, s: float) -> int:
        if s <= 0:
            return 1
        t = 9.0 * s * (self.desired_retention ** (-self.parameters[20]) - 1.0)
        t = max(1.0, t)
        if self.enable_fuzzing:
            import random
            t = t * (1.0 + random.uniform(-0.05, 0.05))
        return min(self.maximum_interval, int(round(t)))

    def review_card(
        self,
        card: MemoryCard,
        rating: Rating,
        now: Optional[float] = None,
        review_duration: float = 0.0,
    ) -> Tuple[MemoryCard, ReviewLog]:
        now = now if now is not None else time.time()
        state_before = card.state
        s_before = card.stability
        r_now = self.get_card_retrievability(card, now)

        log = ReviewLog(
            card_id=card.card_id,
            rating=int(rating),
            review_duration=review_duration,
            reviewed_at=now,
            state_before=state_before,
            stability_before=s_before,
            retrievability=r_now,
        )

        if card.state == State.New.value:
            card.stability = self._initial_stability(rating)
            card.difficulty = self._initial_difficulty(rating)
            card.state = State.Learning.value if rating == Rating.Again else State.Review.value
            card.step = 0
        elif card.state in (State.Learning.value, State.Relearning.value):
            if rating == Rating.Again:
                card.step = 0
            else:
                if card.stability == 0:
                    card.stability = self._initial_stability(rating)
                if card.difficulty == 0:
                    card.difficulty = self._initial_difficulty(rating)
                card.state = State.Review.value
                card.step = 0
        else:  # Review
            card.difficulty = self._next_difficulty(card.difficulty, rating)
            if rating == Rating.Again:
                card.stability = self._next_forget_stability(card.difficulty, card.stability, r_now)
                card.state = State.Relearning.value
                card.step = 0
                card.lapses += 1
            else:
                card.stability = self._next_recall_stability(card.difficulty, card.stability, r_now, rating)

        card.last_review = now
        card.reps += 1
        log.state_after = card.state
        log.stability_after = card.stability
        return card, log

    def next_interval_days(self, card: MemoryCard, now: Optional[float] = None) -> int:
        if card.state == State.New.value:
            return 0
        return self._next_interval(card.stability)


class MemoryScheduler:
    """VoiceTrace 统一调度器

    优先使用 py-fsrs（若安装），否则使用内置实现。
    """

    def __init__(
        self,
        desired_retention: float = TARGET_RETRIEVABILITY_DEFAULT,
        maximum_interval: int = 36500,
    ):
        self.desired_retention = desired_retention
        self.maximum_interval = maximum_interval
        self._builtin = _BuiltinScheduler(
            desired_retention=desired_retention,
            maximum_interval=maximum_interval,
        )
        self._py_scheduler = None
        if _PY_FSRS_AVAILABLE:
            try:
                self._py_scheduler = _PyScheduler(
                    desired_retention=desired_retention,
                    maximum_interval=maximum_interval,
                )
                logger.info("py-fsrs 已加载，使用官方调度器")
            except Exception as exc:
                logger.warning(f"py-fsrs 初始化失败，回退到内置实现: {exc}")
                self._py_scheduler = None

    @property
    def engine_name(self) -> str:
        return "py-fsrs" if self._py_scheduler is not None else "builtin-fsrs"

    def get_retrievability(self, card: MemoryCard, now: Optional[float] = None) -> float:
        """获取卡片当前可检索性 R（0-1）"""
        return self._builtin.get_card_retrievability(card, now)

    def review(
        self,
        card: MemoryCard,
        rating: Rating,
        review_duration: float = 0.0,
        now: Optional[float] = None,
    ) -> ReviewLog:
        """对卡片进行一次评分复习，原地更新 card，返回日志"""
        _, log = self._builtin.review_card(card, rating, now=now, review_duration=review_duration)
        return log

    def next_interval_days(self, card: MemoryCard, now: Optional[float] = None) -> int:
        """预测下一次复习间隔（天）"""
        return self._builtin.next_interval_days(card, now)

    def is_due(self, card: MemoryCard, now: Optional[float] = None) -> bool:
        """卡片是否到期需要复习"""
        if card.state == State.New.value:
            return True
        if card.last_review is None:
            return True
        now = now if now is not None else time.time()
        elapsed_days = (now - card.last_review) / 86400.0
        return elapsed_days >= self.next_interval_days(card, now)

    def due_at(self, card: MemoryCard, now: Optional[float] = None) -> float:
        """卡片到期时间戳（秒）"""
        if card.state == State.New.value or card.last_review is None:
            return 0.0
        now = now if now is not None else time.time()
        interval = self.next_interval_days(card, now)
        return card.last_review + interval * 86400.0

    def stats(self, cards: List[MemoryCard], now: Optional[float] = None) -> Dict[str, Any]:
        """统计一组卡片的整体记忆状态"""
        now = now if now is not None else time.time()
        total = len(cards)
        if total == 0:
            return {"total": 0, "due": 0, "new": 0, "avg_r": 0.0, "avg_s": 0.0, "by_state": {}}

        due = sum(1 for c in cards if self.is_due(c, now))
        new = sum(1 for c in cards if c.state == State.New.value)
        rs = [self.get_retrievability(c, now) for c in cards if c.state != State.New.value]
        ss = [c.stability for c in cards if c.state != State.New.value and c.stability > 0]

        by_state: Dict[str, int] = {}
        for c in cards:
            key = State(c.state).name
            by_state[key] = by_state.get(key, 0) + 1

        return {
            "total": total,
            "due": due,
            "new": new,
            "avg_r": sum(rs) / len(rs) if rs else 0.0,
            "avg_s": sum(ss) / len(ss) if ss else 0.0,
            "by_state": by_state,
        }


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_default_scheduler: Optional[MemoryScheduler] = None


def get_default_scheduler() -> MemoryScheduler:
    global _default_scheduler
    if _default_scheduler is None:
        _default_scheduler = MemoryScheduler()
    return _default_scheduler


def is_fsrs_available() -> bool:
    """是否安装了 py-fsrs"""
    return _PY_FSRS_AVAILABLE
