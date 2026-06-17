from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
    QLineEdit, QComboBox, QFormLayout, QDialog, QTextEdit, QLabel,
    QGroupBox, QSpinBox, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView
)
from PySide6.QtCore import Signal, Qt
from voicetrace.data.database import Database
from voicetrace.data.models import Script, CustomStandard


CATEGORY_LABELS = {
    "news_broadcast": "新闻播报",
    "improv_commentary": "即兴评述",
    "mock_host": "模拟主持",
    "custom": "自定义",
}


class ScriptDialog(QDialog):
    def __init__(self, parent=None, script: Script = None):
        super().__init__(parent)
        self.setWindowTitle("编辑稿件" if script else "新建稿件")
        self.setMinimumWidth(500)

        layout = QFormLayout(self)

        self.title_edit = QLineEdit()
        self.category_combo = QComboBox()
        for key, label in CATEGORY_LABELS.items():
            self.category_combo.addItem(label, key)
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "chinese")
        self.language_combo.addItem("英文", "english")
        self.language_combo.addItem("中英混合", "mixed")
        self.content_edit = QTextEdit()

        layout.addRow("标题:", self.title_edit)
        layout.addRow("分类:", self.category_combo)
        layout.addRow("语言:", self.language_combo)
        layout.addRow("内容:", self.content_edit)

        buttons = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)

        if script:
            self.title_edit.setText(script.title)
            idx = self.category_combo.findData(script.category)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            idx = self.language_combo.findData(script.language)
            if idx >= 0:
                self.language_combo.setCurrentIndex(idx)
            self.content_edit.setText(script.content or "")

    def get_script_data(self) -> dict:
        return {
            "title": self.title_edit.text(),
            "category": self.category_combo.currentData(),
            "language": self.language_combo.currentData(),
            "content": self.content_edit.toPlainText()
        }


class CustomStandardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加自定义标准")
        self.setMinimumWidth(350)

        layout = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "chinese")
        self.language_combo.addItem("英文", "english")
        self.language_combo.addItem("中英混合", "mixed")
        self.category_combo = QComboBox()
        for key, label in CATEGORY_LABELS.items():
            self.category_combo.addItem(label, key)
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 999)
        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, 999)

        layout.addRow("名称:", self.name_edit)
        layout.addRow("语言:", self.language_combo)
        layout.addRow("分类:", self.category_combo)
        layout.addRow("最小语速:", self.min_spin)
        layout.addRow("最大语速:", self.max_spin)

        buttons = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)


class ScriptManager(QWidget):
    script_selected = Signal(int, str, str)  # id, title, content

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 工具栏
        toolbar = QHBoxLayout()
        self.add_btn = QPushButton("新建稿件")
        self.edit_btn = QPushButton("编辑")
        self.delete_btn = QPushButton("删除")
        self.std_btn = QPushButton("自定义标准")
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.edit_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.std_btn)
        layout.addLayout(toolbar)

        # 稿件列表
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)

        # 稿件内容预览
        preview_group = QGroupBox("稿件预览")
        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("选择一个稿件查看内容")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("padding: 10px; background: rgba(0,0,0,0.03); border-radius: 4px;")
        preview_layout.addWidget(self.preview_label)
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)

        # Connect
        self.add_btn.clicked.connect(self._add_script)
        self.edit_btn.clicked.connect(self._edit_script)
        self.delete_btn.clicked.connect(self._delete_script)
        self.std_btn.clicked.connect(self._manage_standards)

    def refresh(self):
        self.list_widget.clear()
        self.scripts = self.db.list_scripts()
        for script in self.scripts:
            cat_label = CATEGORY_LABELS.get(script.category, script.category)
            self.list_widget.addItem(f"{script.title} [{cat_label}]")

    def _on_selection_changed(self, row):
        if 0 <= row < len(self.scripts):
            script = self.scripts[row]
            self.script_selected.emit(script.id, script.title, script.content or "")
            preview = script.content[:500] + "..." if script.content and len(script.content) > 500 else (script.content or "（空）")
            self.preview_label.setText(preview)

    def _add_script(self):
        dialog = ScriptDialog(self)
        if dialog.exec():
            data = dialog.get_script_data()
            script = Script(
                title=data["title"],
                category=data["category"],
                language=data["language"],
                content=data["content"]
            )
            self.db.create_script(script)
            self.refresh()

    def _edit_script(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        script = self.scripts[row]
        dialog = ScriptDialog(self, script)
        if dialog.exec():
            data = dialog.get_script_data()
            script.title = data["title"]
            script.category = data["category"]
            script.language = data["language"]
            script.content = data["content"]
            self.db.update_script(script)
            self.refresh()

    def _delete_script(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        script = self.scripts[row]
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除稿件「{script.title}」吗？\n关联的录音和分析数据也会被删除。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.db.delete_script(script.id)
            self.refresh()

    def _manage_standards(self):
        """管理自定义标准"""
        dialog = QDialog(self)
        dialog.setWindowTitle("自定义语速标准")
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)

        # 当前标准列表
        self.std_table = QTableWidget()
        self.std_table.setColumnCount(5)
        self.std_table.setHorizontalHeaderLabels(["名称", "语言", "分类", "最小", "最大"])
        self.std_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.std_table)

        # 内置标准说明
        info = QLabel("内置标准:\n"
                      "新闻播报: 中文 250-300 CPM / 英文 170-190 WPM\n"
                      "即兴评述: 中文 200-280 CPM / 英文 140-180 WPM\n"
                      "模拟主持: 中文 220-300 CPM / 英文 150-190 WPM")
        info.setStyleSheet("padding: 8px; background: rgba(0,0,0,0.03); border-radius: 4px; font-size: 12px;")
        layout.addWidget(info)

        # 按钮
        btn_layout = QHBoxLayout()
        add_std_btn = QPushButton("添加标准")
        del_std_btn = QPushButton("删除选中")
        add_std_btn.clicked.connect(lambda: self._add_custom_std(dialog))
        del_std_btn.clicked.connect(lambda: self._del_custom_std(dialog))
        btn_layout.addWidget(add_std_btn)
        btn_layout.addWidget(del_std_btn)
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self._refresh_std_table(dialog)
        dialog.exec()

    def _refresh_std_table(self, parent_dialog):
        standards = self.db.list_custom_standards()
        parent_dialog.std_table.setRowCount(len(standards))
        for i, s in enumerate(standards):
            parent_dialog.std_table.setItem(i, 0, QTableWidgetItem(s.name))
            parent_dialog.std_table.setItem(i, 1, QTableWidgetItem(s.language))
            parent_dialog.std_table.setItem(i, 2, QTableWidgetItem(s.category))
            parent_dialog.std_table.setItem(i, 3, QTableWidgetItem(str(s.rate_min)))
            parent_dialog.std_table.setItem(i, 4, QTableWidgetItem(str(s.rate_max)))
            parent_dialog.std_table.item(i, 0).setData(Qt.UserRole, s.id)

    def _add_custom_std(self, parent_dialog):
        dialog = CustomStandardDialog(parent_dialog)
        if dialog.exec():
            std = CustomStandard(
                name=dialog.name_edit.text(),
                language=dialog.language_combo.currentData(),
                category=dialog.category_combo.currentData(),
                rate_min=dialog.min_spin.value(),
                rate_max=dialog.max_spin.value(),
                unit="CPM" if dialog.language_combo.currentData() == "chinese" else "WPM"
            )
            self.db.create_custom_standard(std)
            self._refresh_std_table(parent_dialog)

    def _del_custom_std(self, parent_dialog):
        row = parent_dialog.std_table.currentRow()
        if row < 0:
            return
        std_id = parent_dialog.std_table.item(row, 0).data(Qt.UserRole)
        self.db.delete_custom_standard(std_id)
        self._refresh_std_table(parent_dialog)
