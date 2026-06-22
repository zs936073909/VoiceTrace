"""端到端集成测试：背诵训练功能"""
import sys
import os
import time
import json
import tempfile
from pathlib import Path
from datetime import datetime

# 设置 path
project_root = Path(__file__).resolve().parent.parent
parent_dir = project_root.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from voicetrace.data.database import Database
from voicetrace.data.models import Script, MemoryCard as DBMemoryCard, ReviewLog
from voicetrace.core.memory_scheduler import (
    MemoryScheduler, Rating, MemoryCard, State, get_default_scheduler
)
from voicetrace.core.content_analyzer import ContentAnalyzer


def test_full_workflow():
    """测试完整工作流：分析稿件 → 生成卡片 → 训练复习 → 持久化"""
    print("\n=== 端到端测试 ===")

    # 1. 临时数据库
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = Database(tmp.name)
    print(f"✓ 临时数据库: {tmp.name}")

    # 2. 创建稿件
    script = Script(
        title="坚持的力量",
        category="improv_commentary",
        language="chinese",
        content=(
            "各位评委，大家好。今天我演讲的题目是坚持的力量。"
            "坚持，是通往成功的必经之路。没有坚持，就没有奇迹。"
            "爱迪生发明电灯，失败了上千次，却从未放弃。"
            "正是这种坚持，点亮了人类的夜晚。"
            "让我们在人生的道路上，永不言弃，坚持到底。谢谢大家。"
        ),
    )
    script_id = db.create_script(script)
    print(f"✓ 创建稿件: id={script_id}")

    # 3. 分析稿件
    analyzer = ContentAnalyzer()
    result = analyzer.analyze(script.content, language="chinese", scenario="speech")
    print(f"✓ 分析完成: {len(result.segments)} 段, 难度{result.avg_difficulty:.1f}")

    # 4. 持久化卡片
    for seg in result.segments:
        card_id = f"script_{script_id}_seg_{seg.index}"
        db_card = DBMemoryCard(
            card_id=card_id,
            script_id=script_id,
            segment_index=seg.index,
            front=seg.hint,
            back=seg.text,
            hint=seg.hint,
            scenario="speech",
            tags_json=json.dumps({"keywords": seg.keywords, "difficulty": seg.difficulty}),
        )
        db.upsert_memory_card(db_card)
    cards = db.list_memory_cards(script_id=script_id)
    print(f"✓ 持久化卡片: {len(cards)} 张")
    assert len(cards) == len(result.segments)

    # 5. 模拟复习
    scheduler = get_default_scheduler()
    ratings_sequence = [Rating.Good, Rating.Hard, Rating.Again, Rating.Good, Rating.Easy]

    for i, rating in enumerate(ratings_sequence):
        dc = cards[i % len(cards)]
        mem_card = MemoryCard(
            card_id=dc.card_id, state=dc.state, step=dc.step,
            stability=dc.stability, difficulty=dc.difficulty,
            last_review=dc.last_review, reps=dc.reps, lapses=dc.lapses,
        )
        log = scheduler.review(mem_card, rating, review_duration=5.0)
        # 更新数据库
        dc.state = mem_card.state
        dc.step = mem_card.step
        dc.stability = mem_card.stability
        dc.difficulty = mem_card.difficulty
        dc.last_review = mem_card.last_review
        dc.reps = mem_card.reps
        dc.lapses = mem_card.lapses
        db.upsert_memory_card(dc)
        # 写入日志
        db.create_review_log(ReviewLog(
            card_id=dc.card_id,
            rating=int(rating),
            review_duration=5.0,
            state_before=log.state_before,
            state_after=log.state_after,
            stability_before=log.stability_before,
            stability_after=log.stability_after,
            retrievability=log.retrievability,
        ))
        print(f"  第{i+1}次 rating={rating.name}: S={mem_card.stability:.2f} D={mem_card.difficulty:.2f}")

    # 6. 验证复习日志
    logs = db.list_review_logs()
    print(f"✓ 复习日志: {len(logs)} 条")
    assert len(logs) == len(ratings_sequence)

    # 7. 验证统计
    all_cards = db.list_memory_cards()
    stats = scheduler.stats([MemoryCard(
        card_id=dc.card_id, state=dc.state, stability=dc.stability,
        difficulty=dc.difficulty, last_review=dc.last_review,
        reps=dc.reps, lapses=dc.lapses,
    ) for dc in all_cards])
    print(f"✓ 统计: total={stats['total']} due={stats['due']} avg_r={stats['avg_r']:.2f}")
    print(f"  按状态: {stats['by_state']}")

    # 8. 验证到期判断
    now = time.time()
    due_count = sum(
        1 for dc in all_cards
        if scheduler.is_due(MemoryCard(
            card_id=dc.card_id, state=dc.state, stability=dc.stability,
            last_review=dc.last_review,
        ), now)
    )
    print(f"✓ 当前到期: {due_count} 张")

    # 9. 清理
    db.close()
    os.unlink(tmp.name)
    print("✓ 清理完成")

    print("\n=== 所有测试通过 ===")


def test_scheduler_persistence():
    """测试调度器状态在多次会话间的一致性"""
    print("\n=== 调度器持久化测试 ===")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = Database(tmp.name)

    # 创建卡片并复习
    card_id = "test_persist_0"
    dc = DBMemoryCard(card_id=card_id, script_id=None, segment_index=0, back="测试内容")
    db.upsert_memory_card(dc)

    scheduler = get_default_scheduler()

    # 第一次复习
    dc = db.get_memory_card(card_id)
    mem = MemoryCard(card_id=dc.card_id, state=dc.state, stability=dc.stability,
                     difficulty=dc.difficulty, last_review=dc.last_review,
                     reps=dc.reps, lapses=dc.lapses)
    scheduler.review(mem, Rating.Good)
    dc.state = mem.state
    dc.stability = mem.stability
    dc.difficulty = mem.difficulty
    dc.last_review = mem.last_review
    dc.reps = mem.reps
    db.upsert_memory_card(dc)

    # 重新加载
    dc2 = db.get_memory_card(card_id)
    assert dc2.state == dc.state, f"state mismatch: {dc2.state} != {dc.state}"
    assert dc2.stability == dc.stability
    assert dc2.reps == 1
    print(f"✓ 持久化一致: state={dc2.state} S={dc2.stability:.2f} reps={dc2.reps}")

    db.close()
    os.unlink(tmp.name)
    print("✓ 持久化测试通过")


if __name__ == "__main__":
    test_full_workflow()
    test_scheduler_persistence()
