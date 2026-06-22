"""记忆效率评估体系

基于 FSRS 复习日志计算记忆效率指标，支持 A/B 测试对比。

核心指标：
- 记忆保留率（Retention Rate）：良好+评分占比
- 遗忘率（Lapse Rate）：Again 评分占比
- 平均稳定性增长率：每次复习稳定性提升幅度
- 复习效率：单位时间内的有效复习量
- 预期保留度：基于 FSRS R 值的加权平均

A/B 测试：
- 实验组 vs 对照组的指标对比
- 支持按时间窗口、场景、用户分组
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

from voicetrace.data.database import Database
from voicetrace.data.models import MemoryCard, ReviewLog
from voicetrace.core.memory_scheduler import (
    MemoryScheduler, Rating, State, get_default_scheduler, MemoryCard as FSMemoryCard
)

logger = logging.getLogger(__name__)


@dataclass
class MemoryMetrics:
    """记忆效率指标快照"""
    total_cards: int = 0
    total_reviews: int = 0
    retention_rate: float = 0.0       # 保留率：Good+Easy 占比
    lapse_rate: float = 0.0           # 遗忘率：Again 占比
    avg_stability: float = 0.0        # 平均稳定性（天）
    avg_difficulty: float = 0.0       # 平均难度
    avg_retrievability: float = 0.0   # 平均可检索性
    avg_review_duration: float = 0.0  # 平均复习耗时（秒）
    due_count: int = 0                # 到期卡片数
    new_count: int = 0                # 新卡数
    mastered_count: int = 0           # 已掌握（Review 状态 + S>21天）
    by_state: Dict[str, int] = field(default_factory=dict)
    by_rating: Dict[str, int] = field(default_factory=dict)
    period_start: Optional[str] = None
    period_end: Optional[str] = None


@dataclass
class ABTestResult:
    """A/B 测试对比结果"""
    group_a: MemoryMetrics
    group_b: MemoryMetrics
    retention_diff: float = 0.0       # 保留率差异（百分点）
    stability_diff: float = 0.0       # 稳定性差异（天）
    efficiency_diff: float = 0.0      # 效率差异
    winner: str = ""                  # 'A' / 'B' / 'tie'
    sample_size_a: int = 0
    sample_size_b: int = 0


class MemoryEvaluator:
    """记忆效率评估器"""

    def __init__(self, db: Database, scheduler: Optional[MemoryScheduler] = None):
        self.db = db
        self.scheduler = scheduler or get_default_scheduler()

    def compute_metrics(
        self,
        script_id: Optional[int] = None,
        scenario: Optional[str] = None,
        days_back: Optional[int] = None,
    ) -> MemoryMetrics:
        """计算记忆效率指标

        Args:
            script_id: 限定稿件，None 表示全部
            scenario: 限定场景，None 表示全部
            days_back: 仅统计最近 N 天的复习日志，None 表示全部
        """
        cards = self.db.list_memory_cards(script_id=script_id)
        if scenario:
            cards = [c for c in cards if c.scenario == scenario]

        if not cards:
            return MemoryMetrics()

        # 过滤复习日志
        cutoff_ts = None
        if days_back is not None:
            cutoff_ts = time.time() - days_back * 86400

        all_logs: List[ReviewLog] = []
        for c in cards:
            logs = self.db.list_review_logs(card_id=c.card_id)
            if cutoff_ts is not None:
                logs = [l for l in logs if l.reviewed_at is None or
                        _parse_iso(l.reviewed_at) is None or
                        _parse_iso(l.reviewed_at) >= cutoff_ts]
            all_logs.extend(logs)

        # 计算指标
        total = len(cards)
        now = time.time()

        # 状态分布
        by_state: Dict[str, int] = {}
        for c in cards:
            state_name = State(c.state).name
            by_state[state_name] = by_state.get(state_name, 0) + 1

        # 评分分布
        by_rating: Dict[str, int] = {}
        for log in all_logs:
            rating_name = Rating(log.rating).name
            by_rating[rating_name] = by_rating.get(rating_name, 0) + 1

        # 保留率 / 遗忘率
        if all_logs:
            good_count = sum(1 for l in all_logs if l.rating >= Rating.Good.value)
            again_count = sum(1 for l in all_logs if l.rating == Rating.Again.value)
            retention = good_count / len(all_logs)
            lapse = again_count / len(all_logs)
            avg_dur = sum(l.review_duration for l in all_logs) / len(all_logs)
        else:
            retention = 0.0
            lapse = 0.0
            avg_dur = 0.0

        # 平均稳定性 / 难度 / 可检索性
        stabilities = []
        difficulties = []
        retrievabilities = []
        due_count = 0
        new_count = 0
        mastered = 0

        for c in cards:
            stabilities.append(c.stability)
            difficulties.append(c.difficulty)
            mem = FSMemoryCard(
                card_id=c.card_id, state=c.state, stability=c.stability,
                difficulty=c.difficulty, last_review=c.last_review,
                reps=c.reps, lapses=c.lapses,
            )
            r = self.scheduler.get_retrievability(mem, now)
            retrievabilities.append(r)
            if self.scheduler.is_due(mem, now):
                due_count += 1
            if c.state == State.New.value:
                new_count += 1
            if c.state == State.Review.value and c.stability >= 21.0:
                mastered += 1

        avg_s = sum(stabilities) / total if stabilities else 0.0
        avg_d = sum(difficulties) / total if difficulties else 0.0
        avg_r = sum(retrievabilities) / total if retrievabilities else 0.0

        # 时间窗口
        period_start = None
        period_end = None
        if all_logs:
            timestamps = [_parse_iso(l.reviewed_at) for l in all_logs if l.reviewed_at]
            timestamps = [t for t in timestamps if t is not None]
            if timestamps:
                period_start = datetime.fromtimestamp(min(timestamps)).isoformat()
                period_end = datetime.fromtimestamp(max(timestamps)).isoformat()

        return MemoryMetrics(
            total_cards=total,
            total_reviews=len(all_logs),
            retention_rate=round(retention, 4),
            lapse_rate=round(lapse, 4),
            avg_stability=round(avg_s, 2),
            avg_difficulty=round(avg_d, 2),
            avg_retrievability=round(avg_r, 4),
            avg_review_duration=round(avg_dur, 2),
            due_count=due_count,
            new_count=new_count,
            mastered_count=mastered,
            by_state=by_state,
            by_rating=by_rating,
            period_start=period_start,
            period_end=period_end,
        )

    def compare_groups(
        self,
        group_a_ids: List[int],
        group_b_ids: List[int],
        days_back: Optional[int] = None,
    ) -> ABTestResult:
        """A/B 测试：对比两组卡片的记忆效率

        Args:
            group_a_ids: A 组卡片 ID 列表
            group_b_ids: B 组卡片 ID 列表
            days_back: 统计窗口
        """
        # 获取两组卡片
        all_cards = self.db.list_memory_cards()
        cards_a = [c for c in all_cards if c.id in group_a_ids]
        cards_b = [c for c in all_cards if c.id in group_b_ids]

        # 临时计算每组的指标
        metrics_a = self._compute_for_cards(cards_a, days_back)
        metrics_b = self._compute_for_cards(cards_b, days_back)

        # 差异
        ret_diff = (metrics_a.retention_rate - metrics_b.retention_rate) * 100
        stab_diff = metrics_a.avg_stability - metrics_b.avg_stability
        eff_diff = (metrics_a.retention_rate / max(0.01, metrics_a.avg_review_duration)) - \
                   (metrics_b.retention_rate / max(0.01, metrics_b.avg_review_duration))

        # 判定胜者
        score_a = metrics_a.retention_rate * 0.5 + metrics_a.avg_stability * 0.01
        score_b = metrics_b.retention_rate * 0.5 + metrics_b.avg_stability * 0.01
        if abs(score_a - score_b) < 0.02:
            winner = "tie"
        elif score_a > score_b:
            winner = "A"
        else:
            winner = "B"

        return ABTestResult(
            group_a=metrics_a,
            group_b=metrics_b,
            retention_diff=round(ret_diff, 2),
            stability_diff=round(stab_diff, 2),
            efficiency_diff=round(eff_diff, 4),
            winner=winner,
            sample_size_a=len(cards_a),
            sample_size_b=len(cards_b),
        )

    def _compute_for_cards(
        self,
        cards: List[MemoryCard],
        days_back: Optional[int] = None,
    ) -> MemoryMetrics:
        """为指定卡片集合计算指标（内部辅助）"""
        if not cards:
            return MemoryMetrics()

        cutoff_ts = None
        if days_back is not None:
            cutoff_ts = time.time() - days_back * 86400

        all_logs: List[ReviewLog] = []
        for c in cards:
            logs = self.db.list_review_logs(card_id=c.card_id)
            if cutoff_ts is not None:
                logs = [l for l in logs if l.reviewed_at is None or
                        _parse_iso(l.reviewed_at) is None or
                        _parse_iso(l.reviewed_at) >= cutoff_ts]
            all_logs.extend(logs)

        total = len(cards)
        now = time.time()

        by_state: Dict[str, int] = {}
        for c in cards:
            state_name = State(c.state).name
            by_state[state_name] = by_state.get(state_name, 0) + 1

        by_rating: Dict[str, int] = {}
        for log in all_logs:
            rating_name = Rating(log.rating).name
            by_rating[rating_name] = by_rating.get(rating_name, 0) + 1

        if all_logs:
            good_count = sum(1 for l in all_logs if l.rating >= Rating.Good.value)
            again_count = sum(1 for l in all_logs if l.rating == Rating.Again.value)
            retention = good_count / len(all_logs)
            lapse = again_count / len(all_logs)
            avg_dur = sum(l.review_duration for l in all_logs) / len(all_logs)
        else:
            retention = 0.0
            lapse = 0.0
            avg_dur = 0.0

        stabilities = [c.stability for c in cards]
        difficulties = [c.difficulty for c in cards]
        retrievabilities = []
        due_count = 0
        new_count = 0
        mastered = 0

        for c in cards:
            mem = FSMemoryCard(
                card_id=c.card_id, state=c.state, stability=c.stability,
                difficulty=c.difficulty, last_review=c.last_review,
                reps=c.reps, lapses=c.lapses,
            )
            r = self.scheduler.get_retrievability(mem, now)
            retrievabilities.append(r)
            if self.scheduler.is_due(mem, now):
                due_count += 1
            if c.state == State.New.value:
                new_count += 1
            if c.state == State.Review.value and c.stability >= 21.0:
                mastered += 1

        return MemoryMetrics(
            total_cards=total,
            total_reviews=len(all_logs),
            retention_rate=round(retention, 4),
            lapse_rate=round(lapse, 4),
            avg_stability=round(sum(stabilities) / total, 2),
            avg_difficulty=round(sum(difficulties) / total, 2),
            avg_retrievability=round(sum(retrievabilities) / total, 4),
            avg_review_duration=round(avg_dur, 2),
            due_count=due_count,
            new_count=new_count,
            mastered_count=mastered,
            by_state=by_state,
            by_rating=by_rating,
        )

    def suggest_strategy(self, metrics: MemoryMetrics) -> str:
        """基于指标给出策略建议"""
        suggestions = []

        if metrics.retention_rate < 0.6:
            suggestions.append(
                "保留率偏低（{:.0%}），建议：\n"
                "  - 降低单次复习量，增加复习频率\n"
                "  - 优先使用「提示模式」而非「默写模式」\n"
                "  - 检查组块大小是否过大（建议 3-4 段/次）"
                .format(metrics.retention_rate)
            )
        elif metrics.retention_rate > 0.9 and metrics.avg_stability > 14:
            suggestions.append(
                "保留率优秀（{:.0%}）且稳定性高，建议：\n"
                "  - 切换到「默写模式」挑战主动回忆\n"
                "  - 启用干扰音训练抗干扰能力\n"
                "  - 增加单次复习量"
                .format(metrics.retention_rate)
            )

        if metrics.lapse_rate > 0.3:
            suggestions.append(
                "遗忘率偏高（{:.0%}），建议：\n"
                "  - 对频繁遗忘的卡片添加更多提示\n"
                "  - 缩短复习间隔，增加重学次数\n"
                "  - 检查内容难度是否超出当前水平"
                .format(metrics.lapse_rate)
            )

        if metrics.avg_review_duration > 60:
            suggestions.append(
                "平均复习耗时较长（{:.0f}秒/张），建议：\n"
                "  - 拆分过长的段落\n"
                "  - 训练快速回忆能力"
                .format(metrics.avg_review_duration)
            )

        if metrics.due_count > metrics.total_cards * 0.5:
            suggestions.append(
                "到期卡片堆积（{}/{}），建议：\n"
                "  - 每日固定时间复习\n"
                "  - 优先处理到期卡片，暂停学习新卡"
                .format(metrics.due_count, metrics.total_cards)
            )

        if not suggestions:
            suggestions.append(
                "各项指标良好，保持当前节奏即可。\n"
                "建议持续追踪 7 天 / 30 天保留率趋势。"
            )

        return "\n\n".join(suggestions)


def _parse_iso(s: Optional[str]) -> Optional[float]:
    """解析 ISO 时间字符串为时间戳"""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return None
