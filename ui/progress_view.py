"""训练打卡记录视图"""
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QTextEdit, QInputDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen

from voicetrace.data.database import Database
from voicetrace.data.models import TrainingSession


class CalendarWidget(QWidget):
    """简易日历组件，高亮打卡日期"""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(200)
        self._dates = set()  # 打卡日期集合
        self._current_month = datetime.now().month
        self._current_year = datetime.now().year

    def set_dates(self, dates: list):
        self._dates = set(dates)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cell_w = w / 7
        cell_h = (h - 30) / 6  # 6行 + 标题行

        # 标题
        painter.setPen(QColor("#2b2b2b"))
        painter.drawText(0, 0, w, 30, Qt.AlignCenter, f"{self._current_year}年{self._current_month}月")

        # 星期标题
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        painter.setPen(QColor("#666666"))
        for i, day in enumerate(weekdays):
            painter.drawText(int(i * cell_w), 30, int(cell_w), 20, Qt.AlignCenter, day)

        # 计算当月天数和第一天星期
        import calendar
        first_weekday, days_in_month = calendar.monthrange(self._current_year, self._current_month)
        # calendar.monthrange 返回的星期一是0，调整为周一开始
        first_offset = first_weekday  # 0=周一

        # 绘制日期
        for day in range(1, days_in_month + 1):
            idx = first_offset + day - 1
            row = idx // 7
            col = idx % 7
            x = col * cell_w
            y = 50 + row * cell_h

            date_str = f"{self._current_year}-{self._current_month:02d}-{day:02d}"
            is_today = (day == datetime.now().day and
                       self._current_month == datetime.now().month and
                       self._current_year == datetime.now().year)
            is_checked = date_str in self._dates

            # 背景
            if is_checked:
                painter.fillRect(int(x + 2), int(y + 2), int(cell_w - 4), int(cell_h - 4), QColor("#c0392b"))
                painter.setPen(QColor("#ffffff"))
            elif is_today:
                painter.fillRect(int(x + 2), int(y + 2), int(cell_w - 4), int(cell_h - 4), QColor("#f0ebe2"))
                painter.setPen(QColor("#c0392b"))
            else:
                painter.setPen(QColor("#2b2b2b"))

            painter.drawText(int(x), int(y), int(cell_w), int(cell_h), Qt.AlignCenter, str(day))


class ProgressView(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 统计卡片
        stats_group = QGroupBox("训练统计")
        stats_layout = QHBoxLayout()

        self.total_label = QLabel("总训练: 0 次")
        self.total_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.total_label)

        self.duration_label = QLabel("总时长: 0 分钟")
        self.duration_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.duration_label)

        self.streak_label = QLabel("连续打卡: 0 天")
        self.streak_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #c0392b;")
        stats_layout.addWidget(self.streak_label)

        self.today_label = QLabel("今日: 0 次")
        self.today_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        stats_layout.addWidget(self.today_label)

        stats_layout.addStretch()
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # 日历
        cal_group = QGroupBox("打卡日历")
        cal_layout = QVBoxLayout()
        self.calendar = CalendarWidget()
        cal_layout.addWidget(self.calendar)

        cal_btn_layout = QHBoxLayout()
        self.prev_month_btn = QPushButton("上个月")
        self.next_month_btn = QPushButton("下个月")
        cal_btn_layout.addWidget(self.prev_month_btn)
        cal_btn_layout.addStretch()
        cal_btn_layout.addWidget(self.next_month_btn)
        cal_layout.addLayout(cal_btn_layout)

        cal_group.setLayout(cal_layout)
        layout.addWidget(cal_group)

        # 手动打卡
        manual_layout = QHBoxLayout()
        self.manual_btn = QPushButton("手动打卡")
        self.manual_btn.setStyleSheet("font-size: 14px;")
        manual_layout.addWidget(self.manual_btn)
        manual_layout.addStretch()
        layout.addLayout(manual_layout)

        # 训练记录表
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["日期", "稿件", "时长", "备注", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.table)

        # Connect
        self.prev_month_btn.clicked.connect(self._prev_month)
        self.next_month_btn.clicked.connect(self._next_month)
        self.manual_btn.clicked.connect(self._manual_checkin)

    def refresh(self):
        # 统计
        stats = self.db.get_training_stats()
        self.total_label.setText(f"总训练: {stats['total_sessions']} 次")
        self.duration_label.setText(f"总时长: {stats['total_duration'] / 60:.0f} 分钟")
        self.streak_label.setText(f"连续打卡: {stats['streak']} 天")
        self.today_label.setText(f"今日: {stats['today_count']} 次")

        # 日历
        dates = self.db.get_training_dates()
        self.calendar.set_dates(dates)

        # 记录表
        sessions = self.db.list_training_sessions(50)
        self.table.setRowCount(len(sessions))
        for i, s in enumerate(sessions):
            script_title = ""
            if s.script_id:
                script = self.db.get_script(s.script_id)
                if script:
                    script_title = script.title
            self.table.setItem(i, 0, QTableWidgetItem(s.date or ""))
            self.table.setItem(i, 1, QTableWidgetItem(script_title))
            self.table.setItem(i, 2, QTableWidgetItem(f"{s.duration:.0f}s" if s.duration else "0s"))
            self.table.setItem(i, 3, QTableWidgetItem(s.notes or ""))
            self.table.setItem(i, 4, QTableWidgetItem("—"))

    def _prev_month(self):
        self.calendar._current_month -= 1
        if self.calendar._current_month < 1:
            self.calendar._current_month = 12
            self.calendar._current_year -= 1
        self.calendar.update()

    def _next_month(self):
        self.calendar._current_month += 1
        if self.calendar._current_month > 12:
            self.calendar._current_month = 1
            self.calendar._current_year += 1
        self.calendar.update()

    def _manual_checkin(self):
        notes, ok = QInputDialog.getText(self, "手动打卡", "备注（可选）:")
        if ok:
            self.db.create_training_session(TrainingSession(
                duration=0,
                notes=notes or "手动打卡"
            ))
            self.refresh()
