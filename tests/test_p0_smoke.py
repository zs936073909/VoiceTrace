"""快速验证 P0 模块"""
import sys
import os
from pathlib import Path

# 把项目父目录加入 path，使 voicetrace 包可导入
project_root = Path(__file__).resolve().parent.parent
parent_dir = project_root.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from voicetrace.core.memory_scheduler import (
    MemoryScheduler, Rating, MemoryCard, State, get_default_scheduler
)
from voicetrace.core.content_analyzer import ContentAnalyzer, analyze_script
from voicetrace.data.models import MemoryCard as DBMemoryCard, ReviewLog

print("=== P0 模块导入成功 ===")

# 1. FSRS 调度器
s = MemoryScheduler()
print(f"调度引擎: {s.engine_name}")

c = MemoryCard(card_id="test_1", front="关键词提示", back="完整段落内容")
r = s.review(c, Rating.Good, review_duration=5.0)
print(f"复习后: reps={c.reps} state={State(c.state).name} stability={c.stability:.3f}")
print(f"可检索性 R={s.get_retrievability(c):.3f}")
print(f"下次复习间隔: {s.next_interval_days(c)} 天")

# 模拟多次复习
for i, rating in enumerate([Rating.Good, Rating.Hard, Rating.Again, Rating.Good, Rating.Easy]):
    s.review(c, rating, review_duration=3.0)
    print(f"  第{i+2}次 rating={rating.name}: S={c.stability:.2f} D={c.difficulty:.2f} reps={c.reps} lapses={c.lapses}")

# 2. 内容分析器
print("\n=== 内容分析器 ===")
text = """各位评委，大家好。今天我演讲的题目是坚持的力量。
坚持，是通往成功的必经之路。没有坚持，就没有奇迹。
爱迪生发明电灯，失败了上千次，却从未放弃。
正是这种坚持，点亮了人类的夜晚。
让我们在人生的道路上，永不言弃，坚持到底。谢谢大家。"""

a = ContentAnalyzer()
result = a.analyze(text, scenario="speech")
print(f"分段数: {len(result.segments)}")
print(f"总字数: {result.total_chars}")
print(f"平均难度: {result.avg_difficulty}")
print(f"建议组块: {result.suggested_chunk_size} 段/次")
print(f"全局关键词: {result.keywords_global[:8]}")
for seg in result.segments:
    print(f"  [段{seg.index}] 难度{seg.difficulty:.1f} 字数{seg.char_count} kw={seg.keywords[:3]}")
    print(f"    提示: {seg.hint}")
    print(f"    内容: {seg.text[:50]}...")

# 3. 数据库模型
print("\n=== 数据库模型 ===")
db_card = DBMemoryCard(
    card_id="script_1_seg_0",
    script_id=1,
    segment_index=0,
    front="关键词",
    back="段落",
    scenario="speech",
)
print(f"DBMemoryCard: card_id={db_card.card_id} script_id={db_card.script_id}")

print("\n=== P0 验证通过 ===")
