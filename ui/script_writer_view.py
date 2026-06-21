"""文案写作界面：基于模板或 AI 生成播音文案

支持两种生成方式：
1. 本地模板填充：选择模板 → 填写占位符 → 生成文案
2. 在线 AI 生成：配置 API → 输入主题 → AI 生成

UI 风格：Editorial / Magazine —— 清晰层级、充足留白、卡片分组，
输入控件始终可见且易于操作。
"""
import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QFormLayout, QLineEdit, QTextEdit,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QScrollArea, QSpinBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QSplitter, QFrame, QSizePolicy
)

from voicetrace.core.script_writer import ScriptWriter, is_ai_available
from voicetrace.data.models import Script


class _Card(QFrame):
    """卡片容器：带标题和垂直布局"""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("writerCard")
        self.setProperty("class", "writer-card")
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(14)
        self.main_layout.setContentsMargins(18, 16, 18, 18)

        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("writerCardTitle")
            self.main_layout.addWidget(self.title_label)


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
        self.setObjectName("scriptWriterView")
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(20, 16, 20, 20)

        # 标题区
        header = QWidget()
        header.setObjectName("writerHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setSpacing(4)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("文案写作")
        title.setObjectName("writerTitle")
        subtitle = QLabel("基于模板快速生成，或使用 AI 智能创作播音文案。")
        subtitle.setObjectName("writerSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        # 标签页：模板生成 / AI 生成
        self.tabs = QTabWidget()
        self.tabs.setObjectName("writerTabs")
        layout.addWidget(self.tabs, 1)

        # ---- 标签页 1：模板生成 ----
        template_widget = self._build_template_tab()
        self.tabs.addTab(template_widget, "模板生成")

        # ---- 标签页 2：AI 生成 ----
        ai_widget = self._build_ai_tab()
        self.tabs.addTab(ai_widget, "AI 生成")

        # ---- 底部：生成结果 ----
        result_card = _Card("生成结果")
        self.result_text = QTextEdit()
        self.result_text.setObjectName("writerResult")
        self.result_text.setPlaceholderText("生成的文案将显示在这里...")
        self.result_text.setMinimumHeight(180)
        result_card.main_layout.addWidget(self.result_text, 1)

        # 结果操作按钮
        result_btn_layout = QHBoxLayout()
        result_btn_layout.setSpacing(12)

        copy_btn = QPushButton("复制到剪贴板")
        copy_btn.setObjectName("writerActionBtn")
        copy_btn.clicked.connect(self._copy_result)
        result_btn_layout.addWidget(copy_btn)

        save_btn = QPushButton("保存为稿件")
        save_btn.setObjectName("writerPrimaryBtn")
        save_btn.clicked.connect(self._save_as_script)
        result_btn_layout.addWidget(save_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("writerActionBtn")
        clear_btn.clicked.connect(self._clear_result)
        result_btn_layout.addWidget(clear_btn)

        result_btn_layout.addStretch()
        result_card.main_layout.addLayout(result_btn_layout)
        layout.addWidget(result_card, 1)

    def _build_template_tab(self) -> QWidget:
        """构建模板生成标签页"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setSpacing(18)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setAlignment(Qt.AlignTop)

        # 模板选择卡片
        select_card = _Card("选择模板")
        select_form = self._create_form_layout()

        self.category_combo = QComboBox()
        self.category_combo.addItems(["新闻播报", "即兴评述", "模拟主持", "演讲"])
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        select_form.addRow("类别：", self.category_combo)

        self.language_combo = QComboBox()
        self.language_combo.addItems(["中文", "英文"])
        self.language_combo.currentIndexChanged.connect(self._on_category_changed)
        select_form.addRow("语言：", self.language_combo)

        self.template_combo = QComboBox()
        self.template_combo.currentIndexChanged.connect(self._on_template_selected)
        select_form.addRow("模板：", self.template_combo)

        select_card.main_layout.addLayout(select_form)

        # 模板描述/空状态提示
        self.template_desc_label = QLabel()
        self.template_desc_label.setObjectName("writerSubtitle")
        self.template_desc_label.setWordWrap(True)
        self.template_desc_label.setVisible(False)
        select_card.main_layout.addWidget(self.template_desc_label)

        root_layout.addWidget(select_card)

        # 占位符填写卡片
        placeholders_card = _Card("填写内容")
        self.placeholders_layout = QFormLayout()
        self.placeholders_layout.setSpacing(14)
        self.placeholders_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.placeholders_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        placeholders_card.main_layout.addLayout(self.placeholders_layout)
        root_layout.addWidget(placeholders_card)

        # 写作提示
        self.tips_label = QLabel()
        self.tips_label.setObjectName("writerTips")
        self.tips_label.setWordWrap(True)
        self.tips_label.setVisible(False)
        root_layout.addWidget(self.tips_label)

        # 生成按钮
        generate_btn = QPushButton("生成文案")
        generate_btn.setObjectName("writerPrimaryBtn")
        generate_btn.setMinimumHeight(44)
        generate_btn.clicked.connect(self._generate_from_template)
        root_layout.addWidget(generate_btn)

        scroll.setWidget(root)
        return scroll

    def _build_ai_tab(self) -> QWidget:
        """构建 AI 生成标签页"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setSpacing(18)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setAlignment(Qt.AlignTop)

        # API 配置卡片
        config_card = _Card("API 配置")
        config_form = self._create_form_layout()

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

        config_card.main_layout.addLayout(config_form)
        root_layout.addWidget(config_card)

        # 生成参数卡片
        params_card = _Card("生成参数")
        params_form = self._create_form_layout()

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

        params_card.main_layout.addLayout(params_form)
        root_layout.addWidget(params_card)

        # AI 不可用提示
        if not is_ai_available():
            ai_warn = QLabel("⚠ requests 库未安装，AI 生成功能不可用。\n请运行: pip install requests")
            ai_warn.setObjectName("writerWarning")
            ai_warn.setWordWrap(True)
            root_layout.addWidget(ai_warn)

        # 生成按钮
        ai_generate_btn = QPushButton("AI 生成文案")
        ai_generate_btn.setObjectName("writerAIBtn")
        ai_generate_btn.setMinimumHeight(44)
        ai_generate_btn.clicked.connect(self._generate_with_ai)
        root_layout.addWidget(ai_generate_btn)

        scroll.setWidget(root)
        return scroll

    def _create_form_layout(self) -> QFormLayout:
        """创建统一的表单布局"""
        form = QFormLayout()
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        return form

    def _create_line_edit(self, placeholder: str = "") -> QLineEdit:
        """创建统一风格的单行输入框"""
        edit = QLineEdit()
        edit.setMinimumHeight(34)
        if placeholder:
            edit.setPlaceholderText(placeholder)
        return edit

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
        language_map = {0: "中文", 1: "英文"}
        language_code_map = {0: "chinese", 1: "english"}

        category = category_map.get(self.category_combo.currentIndex(), "news_broadcast")
        language = language_map.get(self.language_combo.currentIndex(), "中文")
        language_code = language_code_map.get(self.language_combo.currentIndex(), "chinese")

        templates = self.writer.get_templates_by_category(category, language_code)
        self.template_combo.clear()

        # 清空占位符区
        self._clear_placeholders()
        self.tips_label.setVisible(False)

        if not templates:
            self.template_desc_label.setText(
                f"⚠️ 当前分类「{self.category_combo.currentText()}」下暂无{language}模板。\n"
                f"请尝试切换语言或分类。"
            )
            self.template_desc_label.setVisible(True)
            self._current_template = None
            return

        self.template_desc_label.setVisible(False)
        for t in templates:
            self.template_combo.addItem(t["name"])
        self._on_template_selected(0)

    def _clear_placeholders(self):
        """清空占位符输入区"""
        while self.placeholders_layout.count():
            item = self.placeholders_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
        self._placeholder_inputs = {}

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
        self._clear_placeholders()

        # 显示模板描述
        desc = template.get("tips", "")
        if desc:
            self.template_desc_label.setText(f"📄 {template['name']}：{desc[:120]}{'...' if len(desc) > 120 else ''}")
            self.template_desc_label.setVisible(True)

        # 创建占位符输入框
        placeholders = template.get("placeholders", {})
        if not placeholders:
            no_ph_label = QLabel("该模板无需填写占位符，直接点击生成即可。")
            no_ph_label.setObjectName("writerSubtitle")
            self.placeholders_layout.addRow(no_ph_label)
        else:
            for key, desc in placeholders.items():
                edit = self._create_line_edit(desc)
                self.placeholders_layout.addRow(f"{key}：", edit)
                self._placeholder_inputs[key] = edit

        # 显示写作提示
        tips = template.get("tips", "")
        if tips:
            self.tips_label.setText(f"💡 写作提示：{tips}")
            self.tips_label.setVisible(True)
        else:
            self.tips_label.setVisible(False)

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
