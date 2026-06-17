from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QVBoxLayout, QWidget, QLabel, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from voicetrace import DATA_DIR, DB_PATH, RECORDINGS_DIR
from voicetrace.data.database import Database
from voicetrace.ui.script_manager import ScriptManager
from voicetrace.ui.recording_panel import RecordingPanel
from voicetrace.ui.analysis_view import AnalysisView
from voicetrace.ui.comparison_view import ComparisonView
from voicetrace.ui.follow_read_view import FollowReadView
from voicetrace.ui.progress_view import ProgressView
from voicetrace.ui.export_dialog import ExportDialog
from voicetrace.ui.styles import LIGHT_THEME, DARK_THEME


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VoiceTrace (声迹) — 语音档案智能追踪系统")
        self.setMinimumSize(1100, 800)

        self.db = Database(DB_PATH)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 稿件管理
        self.script_manager = ScriptManager(self.db)
        self.tabs.addTab(self.script_manager, "稿件管理")

        # 录音
        self.recording_panel = RecordingPanel(self.db, RECORDINGS_DIR)
        self.tabs.addTab(self.recording_panel, "录音")

        # 分析
        self.analysis_view = AnalysisView(self.db)
        self.tabs.addTab(self.analysis_view, "分析")

        # 跟读模式
        self.follow_read_view = FollowReadView(self.db, RECORDINGS_DIR)
        self.tabs.addTab(self.follow_read_view, "跟读模式")

        # 对比
        self.comparison_view = ComparisonView(self.db)
        self.tabs.addTab(self.comparison_view, "对比")

        # 训练打卡
        self.progress_view = ProgressView(self.db)
        self.tabs.addTab(self.progress_view, "训练打卡")

        # 导出
        export_widget = QWidget()
        export_layout = QVBoxLayout(export_widget)
        export_label = QLabel("导出数据为 CSV / JSON / PDF 文件")
        export_label.setAlignment(Qt.AlignCenter)
        export_label.setStyleSheet("font-size: 16px; margin: 20px;")
        export_layout.addWidget(export_label)

        export_btn = QPushButton("打开导出对话框")
        export_btn.setMinimumHeight(40)
        export_btn.clicked.connect(self._open_export)
        export_layout.addWidget(export_btn)
        export_layout.addStretch()
        self.tabs.addTab(export_widget, "导出")

        # 信号连接
        # script_selected 信号: (id, title, content)
        self.script_manager.script_selected.connect(self._on_script_selected)
        self.recording_panel.recording_saved.connect(self._on_recording_saved)

        # 标签页切换
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 菜单栏
        self._setup_menu()

    def _setup_menu(self):
        # 视图菜单 — 主题切换
        view_menu = self.menuBar().addMenu("视图")
        self.theme_action = QAction("切换深色主题 (Ctrl+D)", self)
        self.theme_action.setShortcut("Ctrl+D")
        self.theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(self.theme_action)

        # 帮助菜单
        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction("关于 VoiceTrace", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _toggle_theme(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        current = app.styleSheet()
        if current == DARK_THEME:
            app.setStyleSheet(LIGHT_THEME)
            self.theme_action.setText("切换深色主题 (Ctrl+D)")
        else:
            app.setStyleSheet(DARK_THEME)
            self.theme_action.setText("切换浅色主题 (Ctrl+D)")

    def _show_about(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            "关于 VoiceTrace",
            "<h3>VoiceTrace 声迹</h3>"
            "<p>语音档案智能追踪系统 v1.0</p>"
            "<p>面向播音主持专业学习者及语音训练需求的桌面应用。</p>"
            "<p>功能：稿件管理 / 录音 / 分析 / 跟读模式 / 对比 / 训练打卡 / 数据导出</p>"
            "<p style='color: #888;'>快捷键：Ctrl+R 开始/停止录音 · 空格 标记卡顿 · Ctrl+D 切换主题</p>"
        )

    def _on_script_selected(self, script_id: int, title: str, content: str):
        self.recording_panel.set_script(script_id, title, content)

    def _on_recording_saved(self, recording_id: int):
        # 刷新所有依赖录音的视图
        self.analysis_view.refresh_recordings()
        self.comparison_view.refresh_recordings()
        self.follow_read_view.refresh_recordings()
        self.progress_view.refresh()

    def _on_tab_changed(self, index: int):
        widget = self.tabs.widget(index)
        if widget is self.analysis_view:
            self.analysis_view.refresh_recordings()
        elif widget is self.comparison_view:
            self.comparison_view.refresh_recordings()
        elif widget is self.follow_read_view:
            self.follow_read_view.refresh_recordings()
        elif widget is self.progress_view:
            self.progress_view.refresh()

    def _open_export(self):
        dialog = ExportDialog(self.db, self)
        dialog.exec()

    def closeEvent(self, event):
        self.db.close()
        super().closeEvent(event)
