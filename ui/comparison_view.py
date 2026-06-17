import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QTextEdit, QMessageBox
)

from voicetrace.data.database import Database
from voicetrace.core.comparator import Comparator
from voicetrace.data.models import Comparison


class ComparisonView(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.comparator = Comparator()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Recording selection
        select_layout = QHBoxLayout()

        select_layout.addWidget(QLabel("当前录音:"))
        self.current_combo = QComboBox()
        self.current_combo.setMinimumWidth(250)
        select_layout.addWidget(self.current_combo)

        select_layout.addWidget(QLabel("基准录音:"))
        self.baseline_combo = QComboBox()
        self.baseline_combo.setMinimumWidth(250)
        select_layout.addWidget(self.baseline_combo)

        self.compare_btn = QPushButton("对比")
        select_layout.addWidget(self.compare_btn)
        select_layout.addStretch()

        layout.addLayout(select_layout)

        # Results
        self.similarity_label = QLabel("相似度: --")
        self.similarity_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.similarity_label)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        layout.addWidget(self.report_text)

        # Connect
        self.compare_btn.clicked.connect(self._run_comparison)

    def refresh_recordings(self):
        """Populate both combo boxes from database."""
        for combo in (self.current_combo, self.baseline_combo):
            combo.clear()
        recordings = self.db.list_recordings()
        for rec in recordings:
            script = self.db.get_script(rec.script_id)
            title = script.title if script else "未知"
            label = f"#{rec.id} {title}"
            if rec.duration:
                label += f" ({rec.duration:.1f}s)"
            self.current_combo.addItem(label, rec.id)
            self.baseline_combo.addItem(label, rec.id)

    def _run_comparison(self):
        current_id = self.current_combo.currentData()
        baseline_id = self.baseline_combo.currentData()

        if current_id is None or baseline_id is None:
            QMessageBox.warning(self, "提示", "请选择两个录音进行对比")
            return

        if current_id == baseline_id:
            QMessageBox.warning(self, "提示", "请选择不同的录音进行对比")
            return

        # Get analyses
        current_analysis = self.db.get_latest_analysis(current_id)
        baseline_analysis = self.db.get_latest_analysis(baseline_id)

        if not current_analysis:
            QMessageBox.warning(self, "提示", "当前录音尚未分析，请先在分析标签页进行分析")
            return
        if not baseline_analysis:
            QMessageBox.warning(self, "提示", "基准录音尚未分析，请先在分析标签页进行分析")
            return

        try:
            # Compute similarity
            similarity = self.comparator.compute_similarity(
                current_analysis.mfcc_features or b"",
                baseline_analysis.mfcc_features or b""
            )

            # Generate report
            report = self.comparator.generate_report(
                current_rate=current_analysis.speech_rate or 0,
                baseline_rate=baseline_analysis.speech_rate or 0,
                current_pauses=current_analysis.pause_count or 0,
                baseline_pauses=baseline_analysis.pause_count or 0,
                similarity_score=similarity
            )

            # Save comparison to database
            comparison = Comparison(
                recording_id=current_id,
                baseline_id=baseline_id,
                similarity_score=similarity,
                differences_json=json.dumps(report, ensure_ascii=False)
            )
            self.db.create_comparison(comparison)

            # Update UI
            self.similarity_label.setText(f"相似度: {similarity:.1%}")

            html = self._format_report(report)
            self.report_text.setHtml(html)

        except Exception as e:
            QMessageBox.critical(self, "对比失败", f"对比出错: {e}")

    def _format_report(self, report: dict) -> str:
        improvements = report.get("improvements", [])
        regressions = report.get("regressions", [])

        html = "<html><body style='font-size: 14px; line-height: 1.6;'>"

        html += f"<h3>对比报告</h3>"
        html += f"<p><b>相似度:</b> {report['similarity_score']:.1%}</p>"
        html += f"<p><b>语速变化:</b> {report['rate_delta']:+.0f} 字/分钟</p>"
        html += f"<p><b>卡顿变化:</b> {report['pause_delta']:+d} 次</p>"

        if improvements:
            html += "<h4 style='color: #2e7d32;'>进步</h4><ul>"
            for item in improvements:
                html += f"<li>{item}</li>"
            html += "</ul>"

        if regressions:
            html += "<h4 style='color: #c62828;'>退步</h4><ul>"
            for item in regressions:
                html += f"<li>{item}</li>"
            html += "</ul>"

        if not improvements and not regressions:
            html += "<p>无明显变化</p>"

        html += "</body></html>"
        return html
