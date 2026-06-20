"""文案写作界面：基于模板或 AI 生成播音文案

支持两种生成方式：
1. 本地模板填充：选择模板 → 填写占位符 → 生成文案
2. 在线 AI 生成：配置 API → 输入主题 → AI 生成
"""
import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QGroupBox, QFormLayout, QLineEdit, QTextEdit,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QScrollArea, QSpinBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QSplitter, QFrame
)

from voicetrace.core.script_writer import ScriptWriter, is_ai_available
from voicetrace.data.models import Script


class ScriptWriterView(QWidget):
    """文案写作视图"""

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.writer = ScriptWriter()
        self._current_template: Optional[dict] = None
        self._init_ui()
        self._load_templates()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("文案写作")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #c0392b; padding: 8px;")
        subtitle = QLabel("基于模板快速生成，或使用 AI 智能创作播音文案。")
        subtitle.setStyleSheet("color: #666; padding: 0 8px 8px;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # 标签页：模板生成 / AI 生成
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ---- 标签页 1：模板生成 ----
        template_widget = QWidget()
        template_layout = QVBoxLayout(template_widget)

        # 模板选择
        select_group = QGroupBox("选择模板")
        select_layout = QFormLayout(select_group)

        self.category_combo = QComboBox()
        self.category_combo.addItems(["新闻播报", "即兴评述", "模拟主持", "演讲"])
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        select_layout.addRow("类别：", self.category_combo)

        self.language_combo = QComboBox()
        self.language_combo.addItems(["中文", "英文"])
        self.language_combo.currentIndexChanged.connect(self._on_category_changed)
        select_layout.addRow("语言：", self.language_combo)

        self.template_combo = QComboBox()
        self.template_combo.currentIndexChanged.connect(self._on_template_selected)
        select_layout.addRow("模板：", self.template_combo)

        template_layout.addWidget(select_group)

        # 占位符填写区
        self.placeholders_group = QGroupBox("填写内容")
        self.placeholders_layout = QFormLayout(self.placeholders_group)
        template_layout.addWidget(self.placeholders_group)

        # 写作提示
        self.tips_label = QLabel()
        self.tips_label.setStyleSheet("""
            QLabel {
                background-color: #fff3cd;
                color: #856404;
                padding: 10px;
                border-radius: 6px;
                border: 1px solid #ffeaa7;
            }
        """)
        self.tips_label.setWordWrap(True)
        template_layout.addWidget(self.tips_label)

        # 生成按钮
        generate_btn = QPushButton("生成文案")
        generate_btn.setMinimumHeight(40)
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: white;
                font-size: 15px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #a93226; }
        """)
        generate_btn.clicked.connect(self._generate_from_template)
        template_layout.addWidget(generate_btn)

        self.tabs.addTab(template_widget, "模板生成")

        # ---- 标签页 2：AI 生成 ----
        ai_widget = QWidget()
        ai_layout = QVBoxLayout(ai_widget)

        # API 配置
        config_group = QGroupBox("API 配置")
        config_form = QFormLayout(config_group)

        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText("https://api.openai.com/v1/chat/completions")
        config_form.addRow("API 地址：", self.api_url_edit)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        config_form.addRow("API 密钥：", self.api_key_edit)

        self.model_edit = QLineEdit("gpt-3.5-turbo")
        config_form.addRow("模型：", self.model_edit)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(0.7)
        config_form.addRow("创造性：", self.temp_spin)

        ai_layout.addWidget(config_group)

        # 生成参数
        params_group = QGroupBox("生成参数")
        params_form = QFormLayout(params_group)

        self.ai_category_combo = QComboBox()
        self.ai_category_combo.addItems(["新闻播报", "即兴评述", "模拟主持", "演讲稿"])
        params_form.addRow("文案类型：", self.ai_category_combo)

        self.ai_language_combo = QComboBox()
        self.ai_language_combo.addItems(["中文", "英文", "中英混合"])
        params_form.addRow("语言：", self.ai_language_combo)

        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("例如：人工智能对教育的影响")
        params_form.addRow("主题：", self.topic_edit)

        self.duration_combo = QComboBox()
        self.duration_combo.addItems(["1-2分钟", "2-3分钟", "3-5分钟", "5分钟以上"])
        params_form.addRow("时长：", self.duration_combo)

        self.style_combo = QComboBox()
        self.style_combo.addItems(["标准", "活泼", "严肃", "亲切", "激昂"])
        params_form.addRow("风格：", self.style_combo)

        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText("其他特殊要求（可选）")
        params_form.addRow("附加要求：", self.extra_edit)

        ai_layout.addWidget(params_group)

        # 生成按钮
        ai_generate_btn = QPushButton("AI 生成文案")
        ai_generate_btn.setMinimumHeight(40)
        ai_generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #8e44ad;
                color: white;
                font-size: 15px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #7d3c98; }
        """)
        ai_generate_btn.clicked.connect(self._generate_with_ai)
        ai_layout.addWidget(ai_generate_btn)

        if not is_ai_available():
            ai_warn = QLabel("⚠ requests 库未安装，AI 生成功能不可用。\n请运行: pip install requests")
            ai_warn.setStyleSheet("color: #e74c3c; padding: 8px;")
            ai_layout.addWidget(ai_warn)

        self.tabs.addTab(ai_widget, "AI 生成")

        # ---- 底部：生成结果 ----
        result_group = QGroupBox("生成结果")
        result_layout = QVBoxLayout(result_group)

        self.result_text = QTextEdit()
        self.result_text.setPlaceholderText("生成的文案将显示在这里...")
        self.result_text.setMinimumHeight(200)
        result_layout.addWidget(self.result_text)

        # 结果操作按钮
        result_btn_layout = QHBoxLayout()

        copy_btn = QPushButton("复制到剪贴板")
        copy_btn.clicked.connect(self._copy_result)
        result_btn_layout.addWidget(copy_btn)

        save_btn = QPushButton("保存为稿件")
        save_btn.setStyleSheet("background-color: #27ae60; color: white;")
        save_btn.clicked.connect(self._save_as_script)
        result_btn_layout.addWidget(save_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_result)
        result_btn_layout.addWidget(clear_btn)

        result_layout.addLayout(result_btn_layout)
        layout.addWidget(result_group)

    def _load_templates(self):
        """加载模板到下拉框"""
        self._on_category_changed()

    def _on_category_changed(self):
        """类别变化时刷新模板列表"""
        category_map = {
            0: "news_broadcast",
            1: "improv_commentary",
            2: "mock_host",
            3: "speech"
        }
        language_map = {0: "chinese", 1: "english"}

        category = category_map.get(self.category_combo.currentIndex(), "news_broadcast")
        language = language_map.get(self.language_combo.currentIndex(), "chinese")

        templates = self.writer.get_templates_by_category(category, language)
        self.template_combo.clear()
        for t in templates:
            self.template_combo.addItem(t["name"])
        if templates:
            self._on_template_selected(0)

    def _on_template_selected(self, index: int):
        """模板选择变化"""
        if index < 0:
            return
        name = self.template_combo.currentText()
        if not name:
            return

        template = self.writer.get_template(name)
        if not template:
            return

        self._current_template = template

        # 清空占位符区
        while self.placeholders_layout.count():
            item = self.placeholders_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 创建占位符输入框
        self._placeholder_inputs = {}
        placeholders = template.get("placeholders", {})
        for key, desc in placeholders.items():
            edit = QLineEdit()
            edit.setPlaceholderText(desc)
            self.placeholders_layout.addRow(f"{key}：", edit)
            self._placeholder_inputs[key] = edit

        # 显示写作提示
        tips = template.get("tips", "")
        self.tips_label.setText(f"💡 写作提示：{tips}" if tips else "")

    def _generate_from_template(self):
        """从模板生成文案"""
        if not self._current_template:
            QMessageBox.warning(self, "未选择模板", "请先选择一个模板")
            return

        values = {}
        for key, edit in self._placeholder_inputs.items():
            values[key] = edit.text().strip()

        # 检查必填项
        missing = [k for k, v in values.items() if not v]
        if missing:
            reply = QMessageBox.question(
                self, "存在空缺",
                f"以下占位符未填写：{', '.join(missing)}\n是否继续生成？（空缺将保留为占位符）",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        result = self.writer.generate_from_template(self._current_template["name"], values)
        if result.success:
            self.result_text.setPlainText(result.content)
        else:
            QMessageBox.warning(self, "生成失败", result.error)

    def _generate_with_ai(self):
        """使用 AI 生成文案"""
        if not is_ai_available():
            QMessageBox.warning(self, "功能不可用", "requests 库未安装")
            return

        api_url = self.api_url_edit.text().strip()
        api_key = self.api_key_edit.text().strip()
        if not api_url or not api_key:
            QMessageBox.warning(self, "配置缺失", "请填写 API 地址和密钥")
            return

        topic = self.topic_edit.text().strip()
        if not topic:
            QMessageBox.warning(self, "主题为空", "请输入文案主题")
            return

        category_map = {
            0: "news_broadcast",
            1: "improv_commentary",
            2: "mock_host",
            3: "speech"
        }
        language_map = {0: "chinese", 1: "english", 2: "mixed"}

        category = category_map.get(self.ai_category_combo.currentIndex(), "news_broadcast")
        language = language_map.get(self.ai_language_combo.currentIndex(), "chinese")

        prompt = self.writer.build_ai_prompt(
            category=category,
            topic=topic,
            language=language,
            duration=self.duration_combo.currentText(),
            style=self.style_combo.currentText(),
            extra_requirements=self.extra_edit.text().strip()
        )

        # 禁用按钮，显示生成中
        self.setEnabled(False)
        self.result_text.setPlainText("正在生成中，请稍候...")

        try:
            result = self.writer.generate_with_ai(
                prompt=prompt,
                api_url=api_url,
                api_key=api_key,
                model=self.model_edit.text().strip() or "gpt-3.5-turbo",
                temperature=self.temp_spin.value()
            )
            if result.success:
                self.result_text.setPlainText(result.content)
            else:
                self.result_text.setPlainText("")
                QMessageBox.warning(self, "生成失败", result.error)
        except Exception as e:
            QMessageBox.warning(self, "生成异常", str(e))
        finally:
            self.setEnabled(True)

    def _copy_result(self):
        """复制结果到剪贴板"""
        from PySide6.QtWidgets import QApplication
        text = self.result_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "已复制", "文案已复制到剪贴板")

    def _save_as_script(self):
        """保存为稿件"""
        text = self.result_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "内容为空", "没有可保存的文案")
            return

        # 推断类别和语言
        category_map = {
            0: "news_broadcast",
            1: "improv_commentary",
            2: "mock_host",
            3: "speech"
        }
        if self.tabs.currentIndex() == 0:
            category = category_map.get(self.category_combo.currentIndex(), "custom")
            language = "chinese" if self.language_combo.currentIndex() == 0 else "english"
            title = self.template_combo.currentText() or "AI生成文案"
        else:
            category = category_map.get(self.ai_category_combo.currentIndex(), "custom")
            lang_idx = self.ai_language_combo.currentIndex()
            language = "chinese" if lang_idx == 0 else "english" if lang_idx == 1 else "mixed"
            title = f"AI生成-{self.topic_edit.text()[:20]}"

        script = Script(
            title=title,
            category=category,
            language=language,
            content=text
        )
        try:
            script_id = self.db.create_script(script)
            QMessageBox.information(self, "保存成功", f"稿件已保存到稿件管理\nID: {script_id}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _clear_result(self):
        """清空结果"""
        self.result_text.setPlainText("")
