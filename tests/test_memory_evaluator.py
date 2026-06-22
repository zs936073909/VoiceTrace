"""测试记忆效率评估器"""
import sys
import os
import time
import tempfile
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
parent_dir = project_root.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from voicetrace.data.database import Database
from voicetrace.data.models import Script, MemoryCard as DBMemoryCard, ReviewLog
from voicetrace.core.memory_scheduler import (
    get_default_scheduler, Rating, MemoryCard, State
)
from voicetrace.core.memory_evaluator import MemoryEvaluator


def test_metrics():
    print("\n=== 评估器测试 ===")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = Database(tmp.name)

    # 创建稿件和卡片
    script_id = db.create_script(Script(
        title="测试稿件", category="custom", language="chinese", content="测试内容"
    ))

    cards_data = []
    for i in range(10):
        dc = DBMemoryCard(
            card_id=f"test_{i}",
            script_id=script_id,
            segment_index=i,
            back=f"段落{i}内容",
            scenario="speech",
        )
        db.upsert_memory_card(dc)
        cards_data.append(dc)

    # 模拟复习
    scheduler = get_default_scheduler()
    ratings = [Rating.Good, Rating.Easy, Rating.Hard, Rating.Again, Rating.Good,
               Rating.Good, Rating.Easy, Rating.Hard, Rating.Good, Rating.Easy]

    for i, rating in enumerate(ratings):
        dc = cards_data[i]
        mem = MemoryCard(
            card_id=dc.card_id, state=dc.state, stability=dc.stability,
            difficulty=dc.difficulty, last_review=dc.last_review,
            reps=dc.reps, lapses=dc.lapses,
        )
        log = scheduler.review(mem, rating, review_duration=20.0 + i * 2)
        dc.state = mem.state
        dc.stability = mem.stability
        dc.difficulty = mem.difficulty
        dc.last_review = mem.last_review
        dc.reps = mem.reps
        dc.lapses = mem.lapses
        db.upsert_memory_card(dc)
        db.create_review_log(ReviewLog(
            card_id=dc.card_id, rating=int(rating), review_duration=20.0 + i * 2,
            state_before=log.state_before, state_after=log.state_after,
            stability_before=log.stability_before, stability_after=log.stability_after,
            retrievability=log.retrievability,
        ))

    # 计算指标
    evaluator = MemoryEvaluator(db)
    metrics = evaluator.compute_metrics(script_id=script_id)
    print(f"总卡片: {metrics.total_cards}")
    print(f"总复习: {metrics.total_reviews}")
    print(f"保留率: {metrics.retention_rate:.2%}")
    print(f"遗忘率: {metrics.lapse_rate:.2%}")
    print(f"平均稳定性: {metrics.avg_stability:.2f} 天")
    print(f"平均难度: {metrics.avg_difficulty:.2f}")
    print(f"平均可检索性: {metrics.avg_retrievability:.2%}")
    print(f"平均耗时: {metrics.avg_review_duration:.1f} 秒")
    print(f"到期: {metrics.due_count}, 新卡: {metrics.new_count}, 已掌握: {metrics.mastered_count}")
    print(f"状态分布: {metrics.by_state}")
    print(f"评分分布: {metrics.by_rating}")

    # 策略建议
    print("\n--- 策略建议 ---")
    suggestion = evaluator.suggest_strategy(metrics)
    print(suggestion)

    # A/B 测试
    print("\n--- A/B 测试 ---")
    all_cards = db.list_memory_cards(script_id=script_id)
    group_a = [c.id for c in all_cards[:5]]
    group_b = [c.id for c in all_cards[5:]]
    ab_result = evaluator.compare_groups(group_a, group_b)
    print(f"A 组: 保留率={ab_result.group_a.retention_rate:.2%}, S={ab_result.group_a.avg_stability:.2f}")
    print(f"B 组: 保留率={ab_result.group_b.retention_rate:.2%}, S={ab_result.group_b.avg_stability:.2f}")
    print(f"保留率差异: {ab_result.retention_diff:+.2f} 百分点")
    print(f"稳定性差异: {ab_result.stability_diff:+.2f} 天")
    print(f"胜者: {ab_result.winner}")

    db.close()
    os.unlink(tmp.name)
    print("\n=== 评估器测试通过 ===")


if __name__ == "__main__":
    test_metrics()
