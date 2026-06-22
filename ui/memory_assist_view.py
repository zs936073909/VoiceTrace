"""
背诵训练视图
============

基于 FSRS 间隔重复算法 + 主动回忆 + 测试效应的背诵训练界面。

核心功能：
1. 稿件选择与自动分段（基于内容分析引擎）
2. 记忆训练模式：
   - 预览模式：完整显示段落 + 关键词
   - 提示模式：仅显示首字 + 关键词（主动回忆）
   - 默写模式：空白，仅显示提示音（测试效应）
3. FSRS 评分（Again/Hard/Good/Easy）→ 自动调度下次复习
4. 智能复习队列：到期卡片优先，新卡穿插
5. 模拟演讲环境：计时 + 节奏提示 + 可选干扰音
6. 进度统计：今日完成、待复习、记忆稳定性趋势

理论依据：
- 主动回忆（Active Recall）：提取过程本身强化记忆
- 测试效应（Testing Effect）：测试比重复阅读更有效
- 编码特异性：模拟演讲环境增强情境依赖记忆
"""
from __future__ import annotations

import logging
import time
import json
import os
import random
import threading
from datetime import datetime
from typing import Optional, List, Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QGroupBox, QTextEdit, QProgressBar, QMessageBox, QSpinBox,
    QButtonGroup, QRadioButton, QSlider, QFrame, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QFont, QColor, QShortcut, QKeySequence

from voicetrace.data.database import Database
from voicetrace.data.models import Script, MemoryCard as DBMemoryCard, ReviewLog
from voicetrace.core.memory_scheduler import (
    MemoryScheduler, Rating, MemoryCard, State, get_default_scheduler
)
from voicetrace.core.content_analyzer import ContentAnalyzer, AnalysisResult, Segment

logger = logging.getLogger(__name__)


# 场景标签
SCENARIO_LABELS = {
    "speech": "演讲稿",
    "host": "主持词",
    "emergency": "应急话术",
}

RATING_LABELS = {
    Rating.Again: "重来 (1)",
    Rating.Hard: "困难 (2)",
    Rating.Good: "良好 (3)",
    Rating.Easy: "简单 (4)",
}

RATING_COLORS = {
    Rating.Again: "#c0392b",
    Rating.Hard: "#e67e22",
    Rating.Good: "#27ae60",
    Rating.Easy: "#2980b9",
}

RATING_HINTS = {
    Rating.Again: "完全忘记，需要重新学习",
    Rating.Hard: "想起来了但很吃力",
    Rating.Good: "正常回忆，略有停顿",
    Rating.Easy: "脱口而出，毫无压力",
}


class MemoryAssistView(QWidget):
    """背诵训练主视图"""

    review_completed = Signal(str, int)  # card_id, rating

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.scheduler = get_default_scheduler()
        self.analyzer = ContentAnalyzer()

        # 当前状态
        self._current_script: Optional[Script] = None
        self._current_analysis: Optional[AnalysisResult] = None
        self._current_card: Optional[MemoryCard] = None
        self._current_segment: Optional[Segment] = None
        self._review_start_time: float = 0.0
        self._session_reviews: List[Dict] = []
        self._show_answer: bool = False

        # 模拟演讲环境
        self._noise_player: Optional[QMediaPlayer] = None
        self._noise_output: Optional[QAudioOutput] = None
        self._timer_active: bool = False
        self._elapsed_seconds: float = 0.0

        # 计时器
        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._on_ui_tick)

        self._setup_ui()
        self._refresh_scripts()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 顶部说明
        info = QLabel(
            "背诵训练 · 基于FSRS间隔重复 + 主动回忆\n"
            "选择稿件 → 自动分段 → 记忆训练 → 评分调度"
        )
        info.setStyleSheet(
            "font-size: 14px; padding: 10px; "
            "background: rgba(192,57,43,0.05); border-radius: 6px; "
            "color: #2b2b2b;"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # 主区域：左右分栏
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：稿件选择 + 训练控制
        left = self._build_left_panel()
        splitter.addWidget(left)

        # 右侧：训练卡片 + 评分
        right = self._build_right_panel()
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        # 底部：今日统计
        stats_bar = self._build_stats_bar()
        layout.addWidget(stats_bar)

        # 快捷键
        self._setup_shortcuts()

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # 稿件选择
        script_group = QGroupBox("稿件选择")
        sg_layout = QVBoxLayout(script_group)

        select_row = QHBoxLayout()
        select_row.addWidget(QLabel("稿件:"))
        self.script_combo = QComboBox()
        self.script_combo.setMinimumWidth(220)
        select_row.addWidget(self.script_combo, 1)
        sg_layout.addLayout(select_row)

        # 场景选择
        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel("场景:"))
        self.scenario_combo = QComboBox()
        for key, label in SCENARIO_LABELS.items():
            self.scenario_combo.addItem(label, key)
        scene_row.addWidget(self.scenario_combo, 1)
        sg_layout.addLayout(scene_row)

        # 分析按钮
        self.analyze_btn = QPushButton("分析稿件并生成记忆卡片")
        self.analyze_btn.setMinimumHeight(36)
        self.analyze_btn.clicked.connect(self._on_analyze)
        sg_layout.addWidget(self.analyze_btn)

        # 分段预览
        self.segments_preview = QTextEdit()
        self.segments_preview.setReadOnly(True)
        self.segments_preview.setPlaceholderText("点击「分析稿件」查看自动分段结果")
        self.segments_preview.setMinimumHeight(120)
        sg_layout.addWidget(self.segments_preview)

        layout.addWidget(script_group)

        # 训练模式
        mode_group = QGroupBox("训练模式")
        mg_layout = QVBoxLayout(mode_group)

        self.mode_group = QButtonGroup(self)
        self.mode_preview = QRadioButton("预览模式（完整显示 + 关键词）")
        self.mode_hint = QRadioButton("提示模式（首字 + 关键词，主动回忆）")
        self.mode_hint.setChecked(True)
        self.mode_recall = QRadioButton("默写模式（空白，仅提示音，测试效应）")

        self.mode_group.addButton(self.mode_preview, 0)
        self.mode_group.addButton(self.mode_hint, 1)
        self.mode_group.addButton(self.mode_recall, 2)
        mg_layout.addWidget(self.mode_preview)
        mg_layout.addWidget(self.mode_hint)
        mg_layout.addWidget(self.mode_recall)

        layout.addWidget(mode_group)

        # 模拟演讲环境
        env_group = QGroupBox("模拟演讲环境")
        eg_layout = QVBoxLayout(env_group)

        noise_row = QHBoxLayout()
        self.noise_check = QRadioButton("无干扰")
        self.noise_check.setChecked(True)
        self.noise_low = QRadioButton("轻度（白噪音）")
        self.noise_mid = QRadioButton("中度（人群低语）")
        self.noise_high = QRadioButton("重度（嘈杂环境）")
        noise_row.addWidget(self.noise_check)
        noise_row.addWidget(self.noise_low)
        noise_row.addWidget(self.noise_mid)
        noise_row.addWidget(self.noise_high)
        eg_layout.addLayout(noise_row)

        timer_row = QHBoxLayout()
        timer_row.addWidget(QLabel("目标时长:"))
        self.target_time_spin = QSpinBox()
        self.target_time_spin.setRange(0, 600)
        self.target_time_spin.setValue(0)
        self.target_time_spin.setSuffix(" 秒")
        self.target_time_spin.setSpecialValueText("不限")
        timer_row.addWidget(self.target_time_spin)
        timer_row.addStretch()
        eg_layout.addLayout(timer_row)

        layout.addWidget(env_group)

        # 开始训练按钮
        self.start_train_btn = QPushButton("开始训练（复习到期卡片）")
        self.start_train_btn.setMinimumHeight(44)
        self.start_train_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; font-size: 15px; font-weight: bold; }"
            "QPushButton:hover { background-color: #a93226; }"
        )
        self.start_train_btn.clicked.connect(self._on_start_training)
        layout.addWidget(self.start_train_btn)

        layout.addStretch()
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # 训练卡片
        card_group = QGroupBox("记忆卡片")
        cg_layout = QVBoxLayout(card_group)

        # 卡片元信息
        meta_row = QHBoxLayout()
        self.card_index_label = QLabel("— / —")
        self.card_index_label.setStyleSheet("font-size: 13px; color: #7f8c8d;")
        self.card_state_label = QLabel("状态: —")
        self.card_state_label.setStyleSheet("font-size: 13px; color: #7f8c8d;")
        self.card_stability_label = QLabel("S: —")
        self.card_stability_label.setStyleSheet("font-size: 13px; color: #7f8c8d;")
        meta_row.addWidget(self.card_index_label)
        meta_row.addWidget(self.card_state_label)
        meta_row.addWidget(self.card_stability_label)
        meta_row.addStretch()
        cg_layout.addLayout(meta_row)

        # 提示区
        self.hint_label = QLabel("提示: —")
        self.hint_label.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #2c3e50; "
            "padding: 8px; background: rgba(44,62,80,0.05); border-radius: 4px;"
        )
        self.hint_label.setWordWrap(True)
        cg_layout.addWidget(self.hint_label)

        # 卡片内容（正面/背面）
        self.card_content = QTextEdit()
        self.card_content.setReadOnly(True)
        self.card_content.setMinimumHeight(180)
        self.card_content.setPlaceholderText("点击「开始训练」后显示卡片内容")
        cg_layout.addWidget(self.card_content)

        # 显示答案按钮
        self.show_answer_btn = QPushButton("显示答案 (空格)")
        self.show_answer_btn.setMinimumHeight(36)
        self.show_answer_btn.setEnabled(False)
        self.show_answer_btn.clicked.connect(self._on_show_answer)
        cg_layout.addWidget(self.show_answer_btn)

        # 评分按钮组
        rating_row = QHBoxLayout()
        self.rating_buttons: Dict[Rating, QPushButton] = {}
        for rating in [Rating.Again, Rating.Hard, Rating.Good, Rating.Easy]:
            btn = QPushButton(RATING_LABELS[rating])
            btn.setMinimumHeight(44)
            btn.setEnabled(False)
            btn.setToolTip(RATING_HINTS[rating])
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {RATING_COLORS[rating]}; "
                f"color: white; font-size: 14px; font-weight: bold; }}"
                f"QPushButton:disabled {{ background-color: #bdc3c7; }}"
                f"QPushButton:hover:enabled {{ background-color: {RATING_COLORS[rating]}; "
                f"border: 2px solid #2c3e50; }}"
            )
            btn.clicked.connect(lambda _, r=rating: self._on_rate(r))
            rating_row.addWidget(btn)
            self.rating_buttons[rating] = btn
        cg_layout.addLayout(rating_row)

        # 计时显示
        self.timer_label = QLabel("00:00")
        self.timer_label.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #2c3e50; "
            "padding: 4px; alignment: center;"
        )
        self.timer_label.setAlignment(Qt.AlignCenter)
        cg_layout.addWidget(self.timer_label)

        # 节奏提示
        self.pace_label = QLabel("节奏: —")
        self.pace_label.setStyleSheet(
            "font-size: 12px; color: #7f8c8d; padding: 2px;"
        )
        self.pace_label.setAlignment(Qt.AlignCenter)
        cg_layout.addWidget(self.pace_label)

        layout.addWidget(card_group, 1)

        # 复习队列预览
        queue_group = QGroupBox("复习队列")
        qg_layout = QVBoxLayout(queue_group)
        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(["#", "段落", "状态", "到期"])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue_table.setMaximumHeight(140)
        qg_layout.addWidget(self.queue_table)
        layout.addWidget(queue_group)

        return panel

    def _build_stats_bar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            "QFrame { background: #2c3e50; border-radius: 6px; }"
            "QLabel { color: #f8f6f1; }"
        )
        bar.setFixedHeight(56)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 16, 8)

        self.stats_total = QLabel("总计: 0")
        self.stats_due = QLabel("待复习: 0")
        self.stats_new = QLabel("新卡: 0")
        self.stats_done = QLabel("今日完成: 0")
        self.stats_avg_r = QLabel("平均R: —")

        for lbl in [self.stats_total, self.stats_due, self.stats_new,
                    self.stats_done, self.stats_avg_r]:
            lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
            layout.addWidget(lbl)
            layout.addStretch(1)

        # 评估报告按钮
        self.eval_btn = QPushButton("评估报告")
        self.eval_btn.setStyleSheet(
            "QPushButton { background: #34495e; color: #f8f6f1; "
            "padding: 4px 12px; border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background: #4a6278; }"
        )
        self.eval_btn.clicked.connect(self._on_show_eval_report)
        layout.addWidget(self.eval_btn)

        return bar

    def _setup_shortcuts(self):
        # 1-4 评分
        for i, rating in enumerate([Rating.Again, Rating.Hard, Rating.Good, Rating.Easy], 1):
            sc = QShortcut(QKeySequence(str(i)), self)
            sc.activated.connect(lambda r=rating: self._on_rate(r))
        # 空格显示答案
        sc_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc_space.activated.connect(self._on_show_answer)

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _refresh_scripts(self):
        self.script_combo.clear()
        scripts = self.db.list_scripts()
        for s in scripts:
            self.script_combo.addItem(f"#{s.id} {s.title}", s.id)

    def refresh(self):
        """外部调用：刷新数据"""
        self._refresh_scripts()
        self._refresh_stats()

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_analyze(self):
        """分析稿件并生成/更新记忆卡片"""
        script_id = self.script_combo.currentData()
        if script_id is None:
            QMessageBox.warning(self, "提示", "请先选择稿件")
            return

        script = self.db.get_script(script_id)
        if not script:
            QMessageBox.warning(self, "提示", "稿件不存在")
            return

        if not script.content or not script.content.strip():
            QMessageBox.warning(self, "提示", "稿件内容为空")
            return

        scenario = self.scenario_combo.currentData()
        try:
            result = self.analyzer.analyze(
                script.content,
                language=script.language,
                scenario=scenario,
            )
        except Exception as e:
            QMessageBox.critical(self, "分析失败", f"内容分析出错: {e}")
            return

        self._current_script = script
        self._current_analysis = result

        # 生成/更新记忆卡片到数据库
        saved_count = 0
        for seg in result.segments:
            card_id = f"script_{script.id}_seg_{seg.index}"
            db_card = self.db.get_memory_card(card_id)
            if db_card:
                # 已存在：仅更新内容字段，保留 FSRS 状态
                db_card.front = seg.hint
                db_card.back = seg.text
                db_card.hint = seg.hint
                db_card.scenario = scenario
                db_card.tags_json = json.dumps({
                    "keywords": seg.keywords,
                    "difficulty": seg.difficulty,
                    "char_count": seg.char_count,
                }, ensure_ascii=False)
                self.db.upsert_memory_card(db_card)
            else:
                # 新卡
                db_card = DBMemoryCard(
                    card_id=card_id,
                    script_id=script.id,
                    segment_index=seg.index,
                    front=seg.hint,
                    back=seg.text,
                    hint=seg.hint,
                    scenario=scenario,
                    tags_json=json.dumps({
                        "keywords": seg.keywords,
                        "difficulty": seg.difficulty,
                        "char_count": seg.char_count,
                    }, ensure_ascii=False),
                )
                self.db.upsert_memory_card(db_card)
                saved_count += 1

        # 显示分段预览
        self._show_segments_preview(result)
        self._refresh_queue_table()
        self._refresh_stats()

        QMessageBox.information(
            self, "分析完成",
            f"共分段 {len(result.segments)} 段\n"
            f"新增卡片 {saved_count} 张，已存在 {len(result.segments) - saved_count} 张\n"
            f"平均难度 {result.avg_difficulty:.1f}/5\n"
            f"建议每次记忆 {result.suggested_chunk_size} 段\n\n"
            f"点击「开始训练」开始背诵练习。"
        )

    def _show_segments_preview(self, result: AnalysisResult):
        html_parts = [
            f"<div style='font-size:13px; line-height:1.6;'>",
            f"<b>分段数:</b> {len(result.segments)} | "
            f"<b>总字数:</b> {result.total_chars} | "
            f"<b>平均难度:</b> {result.avg_difficulty:.1f}/5<br>",
            f"<b>全局关键词:</b> {', '.join(result.keywords_global[:8])}<br><hr>",
        ]
        for seg in result.segments:
            kw_str = " / ".join(seg.keywords[:4]) if seg.keywords else "—"
            html_parts.append(
                f"<p><b>[段{seg.index}]</b> 难度{seg.difficulty:.1f} · "
                f"字数{seg.char_count} · 关键词: {kw_str}<br>"
                f"<span style='color:#7f8c8d;'>提示: {seg.hint}</span><br>"
                f"<span style='color:#2c3e50;'>{seg.text[:80]}{'...' if len(seg.text) > 80 else ''}</span></p>"
            )
        html_parts.append("</div>")
        self.segments_preview.setHtml("".join(html_parts))

    def _on_start_training(self):
        """开始训练：构建复习队列"""
        script_id = self.script_combo.currentData()
        if script_id is None:
            QMessageBox.warning(self, "提示", "请先选择稿件")
            return

        cards = self.db.list_memory_cards(script_id=script_id)
        if not cards:
            reply = QMessageBox.question(
                self, "未生成卡片",
                "该稿件尚未生成记忆卡片，是否现在分析并生成？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._on_analyze()
                cards = self.db.list_memory_cards(script_id=script_id)
            if not cards:
                return

        # 构建复习队列：到期卡片优先，新卡穿插
        queue = self._build_review_queue(cards)
        if not queue:
            QMessageBox.information(
                self, "无需复习",
                "当前没有到期卡片，请稍后再来。"
            )
            return

        self._review_queue = queue
        self._queue_index = 0
        self._session_reviews = []

        # 启动计时
        self._elapsed_seconds = 0.0
        self._timer_active = True
        self._ui_timer.start(1000)

        # 启动干扰音
        self._start_noise()

        # 显示第一张卡片
        self._show_current_card()

    def _build_review_queue(self, db_cards: List[DBMemoryCard]) -> List[DBMemoryCard]:
        """构建复习队列：到期卡片 + 新卡（按段顺序）"""
        now = time.time()
        due_cards: List[DBMemoryCard] = []
        new_cards: List[DBMemoryCard] = []

        for dc in db_cards:
            card = self._db_to_memory_card(dc)
            if self.scheduler.is_due(card, now):
                due_cards.append(dc)

        # 排序：到期卡片按到期时间升序，新卡按段顺序
        due_cards.sort(key=lambda dc: self.scheduler.due_at(self._db_to_memory_card(dc), now) or 0)
        new_cards = [dc for dc in db_cards if dc.state == State.New.value]
        new_cards.sort(key=lambda dc: dc.segment_index)

        # 合并：到期卡片优先，新卡每次最多 5 张
        queue = due_cards + new_cards[:5]
        return queue

    def _db_to_memory_card(self, dc: DBMemoryCard) -> MemoryCard:
        return MemoryCard(
            card_id=dc.card_id,
            script_id=dc.script_id,
            segment_index=dc.segment_index,
            front=dc.front,
            back=dc.back,
            hint=dc.hint,
            state=dc.state,
            step=dc.step,
            stability=dc.stability,
            difficulty=dc.difficulty,
            last_review=dc.last_review,
            reps=dc.reps,
            lapses=dc.lapses,
            scenario=dc.scenario,
        )

    def _show_current_card(self):
        """显示当前卡片"""
        if self._queue_index >= len(self._review_queue):
            self._finish_session()
            return

        dc = self._review_queue[self._queue_index]
        self._current_card = self._db_to_memory_card(dc)
        self._show_answer = False
        self._review_start_time = time.time()

        # 元信息
        idx = self._queue_index + 1
        total = len(self._review_queue)
        state_name = State(self._current_card.state).name
        self.card_index_label.setText(f"{idx} / {total}")
        self.card_state_label.setText(f"状态: {state_name}")
        self.card_stability_label.setText(
            f"S: {self._current_card.stability:.1f}天 · "
            f"D: {self._current_card.difficulty:.1f} · "
            f"R: {self.scheduler.get_retrievability(self._current_card):.0%}"
        )

        # 根据模式显示内容
        mode = self.mode_group.checkedId()
        if mode == 0:  # 预览模式
            self.hint_label.setText(f"提示: {dc.hint}")
            self.card_content.setPlainText(dc.back)
            self._show_answer = True
            self.show_answer_btn.setEnabled(False)
            self._enable_rating(True)
        elif mode == 1:  # 提示模式
            self.hint_label.setText(f"提示: {dc.hint}")
            self.card_content.setPlainText("（请主动回忆，按空格显示答案）")
            self.show_answer_btn.setEnabled(True)
            self._enable_rating(False)
        else:  # 默写模式
            self.hint_label.setText("（默写模式：仅凭记忆回忆）")
            self.card_content.setPlainText("（按空格显示答案核对）")
            self.show_answer_btn.setEnabled(True)
            self._enable_rating(False)

    def _on_show_answer(self):
        """显示答案"""
        if not self._current_card or self._show_answer:
            return
        self._show_answer = True
        dc = self._review_queue[self._queue_index]
        self.card_content.setPlainText(dc.back)
        self.show_answer_btn.setEnabled(False)
        self._enable_rating(True)

    def _enable_rating(self, enabled: bool):
        for btn in self.rating_buttons.values():
            btn.setEnabled(enabled)

    def _on_rate(self, rating: Rating):
        """评分"""
        if not self._current_card or not self._show_answer:
            return

        review_duration = time.time() - self._review_start_time
        log = self.scheduler.review(
            self._current_card,
            rating,
            review_duration=review_duration,
        )

        # 持久化
        dc = self._review_queue[self._queue_index]
        dc.state = self._current_card.state
        dc.step = self._current_card.step
        dc.stability = self._current_card.stability
        dc.difficulty = self._current_card.difficulty
        dc.last_review = self._current_card.last_review
        dc.reps = self._current_card.reps
        dc.lapses = self._current_card.lapses
        self.db.upsert_memory_card(dc)

        # 写入复习日志
        db_log = ReviewLog(
            card_id=dc.card_id,
            rating=int(rating),
            review_duration=review_duration,
            state_before=log.state_before,
            state_after=log.state_after,
            stability_before=log.stability_before,
            stability_after=log.stability_after,
            retrievability=log.retrievability,
        )
        self.db.create_review_log(db_log)

        # 记录本次会话
        self._session_reviews.append({
            "card_id": dc.card_id,
            "rating": int(rating),
            "duration": review_duration,
            "stability_after": dc.stability,
        })

        self.review_completed.emit(dc.card_id, int(rating))

        # 下一张
        self._queue_index += 1
        self._refresh_queue_table()
        self._refresh_stats()
        self._show_current_card()

    def _finish_session(self):
        """完成本次训练"""
        self._timer_active = False
        self._ui_timer.stop()
        self._stop_noise()

        if not self._session_reviews:
            return

        total = len(self._session_reviews)
        again = sum(1 for r in self._session_reviews if r["rating"] == 1)
        good = sum(1 for r in self._session_reviews if r["rating"] >= 3)
        avg_dur = sum(r["duration"] for r in self._session_reviews) / total
        avg_s = sum(r["stability_after"] for r in self._session_reviews) / total

        QMessageBox.information(
            self, "训练完成",
            f"本次训练完成 {total} 张卡片\n\n"
            f"重来: {again} 次 ({again/total:.0%})\n"
            f"良好+: {good} 次 ({good/total:.0%})\n"
            f"平均用时: {avg_dur:.1f} 秒/张\n"
            f"平均稳定性: {avg_s:.1f} 天\n\n"
            f"下次到期卡片将自动出现在复习队列中。"
        )

        # 清空当前卡片显示
        self.card_content.setPlainText("训练完成，点击「开始训练」继续")
        self.hint_label.setText("提示: —")
        self.card_index_label.setText("— / —")
        self.card_state_label.setText("状态: —")
        self.card_stability_label.setText("S: —")
        self._enable_rating(False)

    # ------------------------------------------------------------------
    # 计时与干扰音
    # ------------------------------------------------------------------

    def _on_ui_tick(self):
        self._elapsed_seconds += 1.0
        m = int(self._elapsed_seconds // 60)
        s = int(self._elapsed_seconds % 60)
        self.timer_label.setText(f"{m:02d}:{s:02d}")

        # 节奏提示：根据当前卡片累计用时给出提示
        if self._current_card is not None and self._timer_active:
            card_elapsed = self._elapsed_seconds - self._review_start_time
            target_per_card = 30.0  # 默认每张 30 秒
            if self._current_segment and self._current_segment.char_count > 0:
                # 按字数估算：每字 0.4 秒（约 150 字/分钟）
                target_per_card = max(15.0, self._current_segment.char_count * 0.4)

            if card_elapsed > target_per_card * 1.5:
                self.pace_label.setText("节奏: 偏慢，加快回忆")
                self.pace_label.setStyleSheet("color: #c0392b; font-weight: bold;")
            elif card_elapsed > target_per_card:
                self.pace_label.setText("节奏: 稍慢")
                self.pace_label.setStyleSheet("color: #e67e22;")
            else:
                self.pace_label.setText("节奏: 良好")
                self.pace_label.setStyleSheet("color: #27ae60;")

        # 目标时长检查
        target = self.target_time_spin.value()
        if target > 0 and self._elapsed_seconds >= target:
            self._finish_session()

    def _start_noise(self):
        """启动干扰音（基于 NumPy 实时生成，无需外部音频文件）

        三种级别：
        - low: 白噪音（轻柔沙沙声，模拟安静环境底噪）
        - mid: 粉噪音 + 低频调制（人群低语感）
        - high: 棕噪音 + 随机尖峰（嘈杂环境感）
        """
        if self.noise_check.isChecked():
            return

        try:
            import numpy as np
            import tempfile
            import wave
            import struct
        except ImportError:
            logger.warning("NumPy 未安装，无法生成干扰音")
            return

        level = "low" if self.noise_low.isChecked() else \
                "mid" if self.noise_mid.isChecked() else "high"

        # 参数
        sample_rate = 22050
        duration = 10.0  # 10 秒循环
        n_samples = int(sample_rate * duration)

        rng = np.random.default_rng(42)

        if level == "low":
            # 白噪音，低音量
            samples = rng.standard_normal(n_samples) * 0.08
        elif level == "mid":
            # 粉噪音：低频加强的白噪音
            white = rng.standard_normal(n_samples)
            # 简单低通滤波（累积求和归一化）
            pink = np.cumsum(white)
            pink = pink / np.max(np.abs(pink)) * 0.15
            # 加低频调制（模拟人群起伏）
            t = np.arange(n_samples) / sample_rate
            modulation = 0.5 + 0.5 * np.sin(2 * np.pi * 0.3 * t)
            samples = pink * modulation
        else:
            # 棕噪音 + 随机尖峰
            white = rng.standard_normal(n_samples)
            brown = np.cumsum(white) * 0.02
            brown = brown / np.max(np.abs(brown)) * 0.18
            # 随机尖峰（模拟突发声响）
            spikes = np.zeros(n_samples)
            spike_count = int(duration * 1.5)  # 平均每 6-7 秒一次
            for _ in range(spike_count):
                idx = rng.integers(0, n_samples)
                width = rng.integers(500, 2000)
                end = min(idx + width, n_samples)
                amp = rng.uniform(0.1, 0.25)
                spikes[idx:end] += amp * np.linspace(1, 0, end - idx)
            samples = brown + spikes

        # 限幅 + 淡入淡出
        samples = np.clip(samples, -0.95, 0.95)
        fade = int(sample_rate * 0.3)
        samples[:fade] *= np.linspace(0, 1, fade)
        samples[-fade:] *= np.linspace(1, 0, fade)

        # 写入临时 WAV
        try:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False, prefix=f"voicetrace_noise_{level}_"
            )
            tmp.close()
            with wave.open(tmp.name, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                int16 = (samples * 32767).astype(np.int16)
                wf.writeframes(int16.tobytes())

            # 播放
            if self._noise_player is None:
                self._noise_player = QMediaPlayer(self)
                self._noise_output = QAudioOutput(self)
                self._noise_player.setAudioOutput(self._noise_output)
            self._noise_player.setSource(QUrl.fromLocalFile(tmp.name))
            self._noise_output.setVolume(0.6)
            self._noise_player.setLoops(QMediaPlayer.Infinite)
            self._noise_player.play()
            self._noise_file = tmp.name
            logger.info(f"干扰音已启动: {level}")
        except Exception as exc:
            logger.warning(f"干扰音播放失败: {exc}")
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def _stop_noise(self):
        if self._noise_player:
            try:
                self._noise_player.stop()
            except Exception:
                pass
        # 清理临时文件
        noise_file = getattr(self, "_noise_file", None)
        if noise_file and os.path.exists(noise_file):
            try:
                os.unlink(noise_file)
            except Exception:
                pass
            self._noise_file = None

    # ------------------------------------------------------------------
    # 统计与队列刷新
    # ------------------------------------------------------------------

    def _refresh_queue_table(self):
        script_id = self.script_combo.currentData()
        if script_id is None:
            self.queue_table.setRowCount(0)
            return

        cards = self.db.list_memory_cards(script_id=script_id)
        now = time.time()
        self.queue_table.setRowCount(len(cards))
        for i, dc in enumerate(cards):
            card = self._db_to_memory_card(dc)
            due = self.scheduler.is_due(card, now)
            state_name = State(dc.state).name
            if dc.state == State.New.value:
                due_text = "新卡"
            elif dc.last_review:
                interval = self.scheduler.next_interval_days(card, now)
                due_text = f"{interval}天后" if not due else "已到期"
            else:
                due_text = "—"

            self.queue_table.setItem(i, 0, QTableWidgetItem(str(dc.segment_index)))
            text_preview = (dc.back or "")[:30] + ("..." if len(dc.back or "") > 30 else "")
            self.queue_table.setItem(i, 1, QTableWidgetItem(text_preview))
            self.queue_table.setItem(i, 2, QTableWidgetItem(state_name))
            due_item = QTableWidgetItem(due_text)
            if due:
                due_item.setForeground(QColor("#c0392b"))
            self.queue_table.setItem(i, 3, QTableWidgetItem(due_text))

    def _refresh_stats(self):
        script_id = self.script_combo.currentData()
        if script_id is None:
            cards = []
        else:
            cards = self.db.list_memory_cards(script_id=script_id)

        now = time.time()
        total = len(cards)
        due = 0
        new = 0
        rs = []
        for dc in cards:
            card = self._db_to_memory_card(dc)
            if self.scheduler.is_due(card, now):
                due += 1
            if dc.state == State.New.value:
                new += 1
            if dc.state != State.New.value:
                rs.append(self.scheduler.get_retrievability(card, now))

        # 今日完成数
        today = datetime.now().strftime("%Y-%m-%d")
        all_logs = self.db.list_review_logs(limit=10000)
        done_today = sum(1 for log in all_logs if log.reviewed_at and log.reviewed_at.startswith(today))

        self.stats_total.setText(f"总计: {total}")
        self.stats_due.setText(f"待复习: {due}")
        self.stats_new.setText(f"新卡: {new}")
        self.stats_done.setText(f"今日完成: {done_today}")
        avg_r = sum(rs) / len(rs) if rs else 0.0
        self.stats_avg_r.setText(f"平均R: {avg_r:.0%}")

    def _on_show_eval_report(self):
        """显示记忆效率评估报告"""
        script_id = self.script_combo.currentData()
        try:
            from voicetrace.core.memory_evaluator import MemoryEvaluator
            evaluator = MemoryEvaluator(self.db, self.scheduler)
            metrics = evaluator.compute_metrics(script_id=script_id)
            suggestion = evaluator.suggest_strategy(metrics)

            # 状态分布文本
            state_text = "\n".join(
                f"  {k}: {v} 张" for k, v in metrics.by_state.items()
            ) or "  （无数据）"

            # 评分分布文本
            rating_text = "\n".join(
                f"  {k}: {v} 次" for k, v in metrics.by_rating.items()
            ) or "  （无数据）"

            report = (
                f"=== 记忆效率评估报告 ===\n\n"
                f"【基础指标】\n"
                f"  总卡片数: {metrics.total_cards}\n"
                f"  总复习次数: {metrics.total_reviews}\n"
                f"  已掌握: {metrics.mastered_count} 张\n"
                f"  待复习: {metrics.due_count} 张\n"
                f"  新卡: {metrics.new_count} 张\n\n"
                f"【效率指标】\n"
                f"  保留率: {metrics.retention_rate:.1%}\n"
                f"  遗忘率: {metrics.lapse_rate:.1%}\n"
                f"  平均稳定性: {metrics.avg_stability:.1f} 天\n"
                f"  平均难度: {metrics.avg_difficulty:.1f}\n"
                f"  平均可检索性: {metrics.avg_retrievability:.1%}\n"
                f"  平均复习耗时: {metrics.avg_review_duration:.1f} 秒\n\n"
                f"【状态分布】\n{state_text}\n\n"
                f"【评分分布】\n{rating_text}\n\n"
                f"【策略建议】\n{suggestion}"
            )

            if metrics.period_start and metrics.period_end:
                report += f"\n\n【统计区间】\n  {metrics.period_start} ~ {metrics.period_end}"

            QMessageBox.information(self, "记忆效率评估报告", report)
        except Exception as exc:
            logger.warning(f"评估报告生成失败: {exc}")
            QMessageBox.warning(self, "错误", f"评估报告生成失败: {exc}")
