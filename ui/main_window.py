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
from voicetrace.ui.export_dialog import ExportDialog
from voicetrace.ui.posture_view import PostureView
from voicetrace.ui.script_writer_view import ScriptWriterView
from voicetrace.ui.realtime_coach_view import RealtimeCoachView
from voicetrace.ui.llm_settings_dialog import show_llm_settings
from voicetrace.ui.styles import LIGHT_THEME, DARK_THEME


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VoiceTrace (声迹) — 语音档案智能追踪系统")
        self.setMinimumSize(1100, 800)

        self.db = Database(DB_PATH)

        # 模式：simple（默认）或 pro
        self._app_mode = "simple"

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 所有视图先创建，但按模式选择性显示
        self.script_manager = ScriptManager(self.db)
        self.script_writer_view = ScriptWriterView(self.db)
        self.recording_panel = RecordingPanel(self.db, RECORDINGS_DIR)
        self.analysis_view = AnalysisView(self.db)
        self.follow_read_view = FollowReadView(self.db, RECORDINGS_DIR)
        self.comparison_view = ComparisonView(self.db)
        self.realtime_coach_view = RealtimeCoachView(self.db)
        self.posture_view = PostureView(self.db)

        # 导出占位页
        self._export_widget = QWidget()
        export_layout = QVBoxLayout(self._export_widget)
        export_label = QLabel("导出数据为 CSV / JSON / PDF 文件")
        export_label.setAlignment(Qt.AlignCenter)
        export_label.setStyleSheet("font-size: 16px; margin: 20px;")
        export_layout.addWidget(export_label)

        export_btn = QPushButton("打开导出对话框")
        export_btn.setMinimumHeight(40)
        export_btn.clicked.connect(self._open_export)
        export_layout.addWidget(export_btn)
        export_layout.addStretch()

        # 按当前模式构建标签页
        self._build_tabs()

        # 信号连接
        # script_selected 信号: (id, title, content)
        self.script_manager.script_selected.connect(self._on_script_selected)
        self.recording_panel.recording_saved.connect(self._on_recording_saved)

        # 标签页切换
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 菜单栏
        self._setup_menu()

    def _build_tabs(self):
        """根据当前模式重建标签页"""
        self.tabs.clear()

        # 简单/专业模式都显示的核心功能
        self.tabs.addTab(self.script_manager, "稿件管理")
        self.tabs.addTab(self.script_writer_view, "文案写作")
        self.tabs.addTab(self.recording_panel, "录音")
        self.tabs.addTab(self.analysis_view, "分析")
        self.tabs.addTab(self.posture_view, "台风训练")

        if self._app_mode == "pro":
            self.tabs.addTab(self.follow_read_view, "跟读模式")
            self.tabs.addTab(self.comparison_view, "对比")
            self.tabs.addTab(self.realtime_coach_view, "实时陪练")
            self.tabs.addTab(self._export_widget, "导出")

    def _setup_menu(self):
        # 设置菜单
        settings_menu = self.menuBar().addMenu("设置")
        llm_action = QAction("AI 大模型设置 (Ctrl+L)", self)
        llm_action.setShortcut("Ctrl+L")
        llm_action.triggered.connect(self._open_llm_settings)
        settings_menu.addAction(llm_action)

        # 视图菜单 — 模式切换 + 主题切换
        view_menu = self.menuBar().addMenu("视图")

        self.mode_action = QAction("切换到专业模式 (Ctrl+P)", self)
        self.mode_action.setShortcut("Ctrl+P")
        self.mode_action.triggered.connect(self._toggle_mode)
        view_menu.addAction(self.mode_action)

        view_menu.addSeparator()

        self.theme_action = QAction("切换深色主题 (Ctrl+D)", self)
        self.theme_action.setShortcut("Ctrl+D")
        self.theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(self.theme_action)

        # 帮助菜单
        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction("关于 VoiceTrace", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _open_llm_settings(self):
        show_llm_settings(self)

    def _toggle_mode(self):
        """切换简单/专业模式"""
        if self._app_mode == "simple":
            self._app_mode = "pro"
            self.mode_action.setText("切换到简单模式 (Ctrl+P)")
        else:
            self._app_mode = "simple"
            self.mode_action.setText("切换到专业模式 (Ctrl+P)")
        self._build_tabs()

    def _toggle_theme(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        current = app.styleSheet()
        if current == DARK_THEME:
            app.setStyleSheet(LIGHT_THEME)
            self.theme_action.setText("切换深色主题 (Ctrl+D)")
            self.posture_view.set_theme("light")
        else:
            app.setStyleSheet(DARK_THEME)
            self.theme_action.setText("切换浅色主题 (Ctrl+D)")
            self.posture_view.set_theme("dark")

    def _show_about(self):
        from PySide6.QtWidgets import QMessageBox
        mode_text = "专业模式" if self._app_mode == "pro" else "简单模式"
        QMessageBox.about(
            self,
            "关于 VoiceTrace",
            "<h3>VoiceTrace 声迹</h3>"
            "<p>语音档案智能追踪系统 v2.0</p>"
            "<p>面向播音主持专业学习者及语音训练需求的桌面应用。</p>"
            "<p>核心功能：稿件管理 / 文案写作 / 录音 / 分析 / 台风训练</p>"
            "<p>专业功能：跟读模式 / 对比 / 实时陪练 / 数据导出</p>"
            f"<p>当前模式：<b>{mode_text}</b>（可在「视图」菜单切换）</p>"
            "<p style='color: #888;'>快捷键：Ctrl+R 开始/停止录音 · 空格 标记卡顿 · Ctrl+D 切换主题 · Ctrl+P 切换模式</p>"
            "<p style='color: #888;'>台风训练需安装 MediaPipe：pip install mediapipe opencv-python</p>"
        )

    def _on_script_selected(self, script_id: int, title: str, content: str):
        self.recording_panel.set_script(script_id, title, content)

    def _on_recording_saved(self, recording_id: int):
        # 刷新所有依赖录音的视图
        self.analysis_view.refresh_recordings()
        if self._app_mode == "pro":
            self.comparison_view.refresh_recordings()
            self.follow_read_view.refresh_recordings()

    def _on_tab_changed(self, index: int):
        widget = self.tabs.widget(index)
        if widget is self.analysis_view:
            self.analysis_view.refresh_recordings()
        elif widget is self.comparison_view:
            self.comparison_view.refresh_recordings()
        elif widget is self.follow_read_view:
            self.follow_read_view.refresh_recordings()
        elif widget is self.posture_view:
            self.posture_view._refresh_history()

    def _open_export(self):
        dialog = ExportDialog(self.db, self)
        dialog.exec()

    def closeEvent(self, event):
        self.db.close()
        super().closeEvent(event)
