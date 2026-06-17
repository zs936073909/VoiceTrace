from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QFileDialog, QMessageBox
)

from voicetrace.data.database import Database
from voicetrace.utils.export import export_csv, export_json, export_pdf


class ExportDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("导出报告")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("导出格式:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["CSV", "JSON", "PDF"])
        layout.addWidget(self.format_combo)

        layout.addWidget(QLabel("导出内容:"))
        self.content_combo = QComboBox()
        self.content_combo.addItems(["所有录音分析", "所有稿件", "所有对比记录"])
        layout.addWidget(self.content_combo)

        buttons = QHBoxLayout()
        export_btn = QPushButton("导出")
        cancel_btn = QPushButton("取消")
        export_btn.clicked.connect(self._export)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(export_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _export(self):
        fmt = self.format_combo.currentText()
        content_type = self.content_combo.currentText()

        if fmt == "CSV":
            filter_str = "CSV Files (*.csv)"
            default_ext = ".csv"
        elif fmt == "JSON":
            filter_str = "JSON Files (*.json)"
            default_ext = ".json"
        else:
            filter_str = "PDF Files (*.pdf)"
            default_ext = ".pdf"

        path, _ = QFileDialog.getSaveFileName(
            self, "保存报告", f"voicetrace_export{default_ext}", filter_str
        )
        if not path:
            return

        path = Path(path)

        try:
            data = self._collect_data(content_type)
            if not data:
                QMessageBox.information(self, "提示", "没有数据可导出")
                return

            if fmt == "CSV":
                success = export_csv(data, path)
            elif fmt == "JSON":
                success = export_json(data, path)
            else:
                title = f"VoiceTrace {content_type} 报告"
                success = export_pdf(data, path, title=title)

            if success:
                QMessageBox.information(self, "成功", f"已导出到:\n{path}")
                self.accept()
            else:
                QMessageBox.warning(self, "失败", "导出失败，请检查格式或数据")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出错: {e}")

    def _collect_data(self, content_type: str) -> list:
        if content_type == "所有录音分析":
            recordings = self.db.list_recordings()
            result = []
            for rec in recordings:
                script = self.db.get_script(rec.script_id)
                analysis = self.db.get_latest_analysis(rec.id)
                stumbles = self.db.get_stumbles(rec.id)
                row = {
                    "recording_id": rec.id,
                    "script_title": script.title if script else "",
                    "script_category": script.category if script else "",
                    "script_language": script.language if script else "",
                    "file_path": rec.file_path,
                    "duration": rec.duration,
                    "speech_rate": analysis.speech_rate if analysis else None,
                    "pause_count": analysis.pause_count if analysis else None,
                    "total_pause_duration": analysis.total_pause_duration if analysis else None,
                    "rms_energy": analysis.rms_energy if analysis else None,
                    "stumble_count": len(stumbles),
                }
                result.append(row)
            return result

        elif content_type == "所有稿件":
            scripts = self.db.list_scripts()
            return [
                {
                    "id": s.id,
                    "title": s.title,
                    "category": s.category,
                    "language": s.language,
                    "content_length": len(s.content) if s.content else 0,
                }
                for s in scripts
            ]

        elif content_type == "所有对比记录":
            recordings = self.db.list_recordings()
            result = []
            for rec in recordings:
                comp = self.db.get_latest_comparison(rec.id)
                if comp:
                    baseline = self.db.get_recording(comp.baseline_id)
                    result.append({
                        "recording_id": rec.id,
                        "baseline_id": comp.baseline_id,
                        "baseline_file": baseline.file_path if baseline else "",
                        "similarity_score": comp.similarity_score,
                        "differences": comp.differences_json,
                    })
            return result

        return []
