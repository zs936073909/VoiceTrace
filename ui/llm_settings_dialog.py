"""LLM 统一设置对话框

集中配置全应用的 AI 服务：
- 文本大模型：用于文案写作、语音分析建议、实时陪练、台风训练总结
- 多模态大模型（可选）：用于台风训练实时画面分析

配置保存到 config/llm_config.json。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QGroupBox, QCheckBox, QTabWidget, QDoubleSpinBox,
    QSpinBox, QMessageBox
)

from voicetrace.core.llm_config_manager import AppLLMConfig, LLMConfigManager
from voicetrace.core.llm_service import get_default_api_url, get_default_model


PROVIDER_LABELS = {
    "nvidia": "NVIDIA NIM",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "moonshot": "Moonshot (Kimi)",
    "anthropic": "Anthropic",
    "custom": "自定义 OpenAI 兼容"
}


class LLMSettingsDialog(QDialog):
    """LLM 设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 大模型设置")
        self.setMinimumWidth(560)
        self._manager = LLMConfigManager()
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # 说明文字
        desc = QLabel(
            "统一配置 AI 服务。文案写作、语音分析、实时陪练、台风训练都会使用这里的设置。\n"
            "· 文本模式：只配置文本模型，所有 AI 功能基于结构化数据生成建议。\n"
            "· 多模态模式：在文本模型基础上启用多模态模型，台风训练会额外分析画面。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #7f8c8d;")
        layout.addWidget(desc)

        # Tab
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ---- 文本模型 Tab ----
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        text_layout.setSpacing(12)

        text_group = QGroupBox("文本大模型")
        text_inner = QVBoxLayout(text_group)

        # Provider
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("服务商:"))
        self.provider_combo = QComboBox()
        for key, label in PROVIDER_LABELS.items():
            self.provider_combo.addItem(label, key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        row1.addWidget(self.provider_combo, 1)
        text_inner.addLayout(row1)

        # API Key
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("必填")
        row2.addWidget(self.api_key_edit, 1)
        text_inner.addLayout(row2)

        # Model
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("模型:"))
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("meta/llama3-70b-instruct")
        row3.addWidget(self.model_edit, 1)
        text_inner.addLayout(row3)

        # API URL
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("API 地址:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("留空使用默认地址")
        row4.addWidget(self.url_edit, 1)
        text_inner.addLayout(row4)

        # 温度 / 最大 token
        row5 = QHBoxLayout()
        row5.addWidget(QLabel("Temperature:"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(0.6)
        row5.addWidget(self.temp_spin)
        row5.addWidget(QLabel("Max Tokens:"))
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(100, 8000)
        self.max_tokens_spin.setSingleStep(100)
        self.max_tokens_spin.setValue(1500)
        row5.addWidget(self.max_tokens_spin)
        row5.addStretch()
        text_inner.addLayout(row5)

        text_layout.addWidget(text_group)
        text_layout.addStretch()
        self.tabs.addTab(text_tab, "文本模型")

        # ---- 多模态模型 Tab ----
        mm_tab = QWidget()
        mm_layout = QVBoxLayout(mm_tab)
        mm_layout.setSpacing(12)

        self.use_mm_check = QCheckBox("启用多模态模式（台风训练额外分析画面）")
        self.use_mm_check.setChecked(False)
        self.use_mm_check.setToolTip("勾选后进入多模态模式：文本 LLM 生成总结，多模态 LLM 分析训练画面")
        self.use_mm_check.stateChanged.connect(self._on_mm_toggled)
        mm_layout.addWidget(self.use_mm_check)

        mm_group = QGroupBox("多模态大模型")
        mm_inner = QVBoxLayout(mm_group)

        row1m = QHBoxLayout()
        row1m.addWidget(QLabel("服务商:"))
        self.mm_provider_combo = QComboBox()
        for key, label in PROVIDER_LABELS.items():
            self.mm_provider_combo.addItem(label, key)
        self.mm_provider_combo.currentIndexChanged.connect(self._on_mm_provider_changed)
        row1m.addWidget(self.mm_provider_combo, 1)
        mm_inner.addLayout(row1m)

        row2m = QHBoxLayout()
        row2m.addWidget(QLabel("API Key:"))
        self.mm_api_key_edit = QLineEdit()
        self.mm_api_key_edit.setEchoMode(QLineEdit.Password)
        self.mm_api_key_edit.setPlaceholderText("启用多模态时必填")
        row2m.addWidget(self.mm_api_key_edit, 1)
        mm_inner.addLayout(row2m)

        row3m = QHBoxLayout()
        row3m.addWidget(QLabel("模型:"))
        self.mm_model_edit = QLineEdit()
        self.mm_model_edit.setPlaceholderText("gpt-4o")
        row3m.addWidget(self.mm_model_edit, 1)
        mm_inner.addLayout(row3m)

        row4m = QHBoxLayout()
        row4m.addWidget(QLabel("API 地址:"))
        self.mm_url_edit = QLineEdit()
        self.mm_url_edit.setPlaceholderText("留空使用默认地址")
        row4m.addWidget(self.mm_url_edit, 1)
        mm_inner.addLayout(row4m)

        mm_layout.addWidget(mm_group)
        mm_layout.addStretch()
        self.tabs.addTab(mm_tab, "多模态模型")

        # 按钮
        btn_layout = QHBoxLayout()
        self.test_btn = QPushButton("测试文本连接")
        self.test_btn.clicked.connect(self._test_text_connection)
        self.save_btn = QPushButton("保存")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.test_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def _load_config(self):
        cfg = self._manager.get_config()
        idx = self.provider_combo.findData(cfg.provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.api_key_edit.setText(cfg.api_key)
        self.model_edit.setText(cfg.model)
        self.url_edit.setText(cfg.api_url)
        self.temp_spin.setValue(cfg.temperature)
        self.max_tokens_spin.setValue(cfg.max_tokens)

        self.use_mm_check.setChecked(cfg.use_multimodal)
        idxm = self.mm_provider_combo.findData(cfg.multimodal_provider)
        if idxm >= 0:
            self.mm_provider_combo.setCurrentIndex(idxm)
        self.mm_api_key_edit.setText(cfg.multimodal_api_key)
        self.mm_model_edit.setText(cfg.multimodal_model)
        self.mm_url_edit.setText(cfg.multimodal_api_url)
        self._on_mm_toggled()

    def _on_provider_changed(self, index: int):
        provider = self.provider_combo.itemData(index)
        default_model = get_default_model(provider)
        default_url = get_default_api_url(provider)
        if not self.model_edit.text():
            self.model_edit.setText(default_model)
        self.model_edit.setPlaceholderText(default_model)
        self.url_edit.setPlaceholderText(default_url)

    def _on_mm_provider_changed(self, index: int):
        provider = self.mm_provider_combo.itemData(index)
        default_model = get_default_model(provider)
        default_url = get_default_api_url(provider)
        if not self.mm_model_edit.text():
            self.mm_model_edit.setText(default_model)
        self.mm_model_edit.setPlaceholderText(default_model)
        self.mm_url_edit.setPlaceholderText(default_url)

    def _on_mm_toggled(self):
        enabled = self.use_mm_check.isChecked()
        self.mm_provider_combo.setEnabled(enabled)
        self.mm_api_key_edit.setEnabled(enabled)
        self.mm_model_edit.setEnabled(enabled)
        self.mm_url_edit.setEnabled(enabled)

    def _build_config(self) -> AppLLMConfig:
        return AppLLMConfig(
            provider=self.provider_combo.currentData(),
            api_key=self.api_key_edit.text().strip(),
            model=self.model_edit.text().strip(),
            api_url=self.url_edit.text().strip(),
            temperature=self.temp_spin.value(),
            max_tokens=self.max_tokens_spin.value(),
            use_multimodal=self.use_mm_check.isChecked(),
            multimodal_provider=self.mm_provider_combo.currentData(),
            multimodal_api_key=self.mm_api_key_edit.text().strip(),
            multimodal_model=self.mm_model_edit.text().strip(),
            multimodal_api_url=self.mm_url_edit.text().strip()
        )

    def _test_text_connection(self):
        from voicetrace.core.llm_service import LLMService
        cfg = self._build_config().to_text_config()
        if not cfg.api_key:
            QMessageBox.warning(self, "未配置", "请先填写 API Key")
            return
        service = LLMService(cfg)
        reply = service.chat_completion(
            messages=[{"role": "user", "content": "你好，请回复：连接成功"}],
            max_tokens=50
        )
        if reply.success:
            QMessageBox.information(self, "测试成功", f"模型返回：{reply.content[:200]}")
        else:
            QMessageBox.critical(self, "测试失败", reply.error)

    def _save(self):
        cfg = self._build_config()
        try:
            self._manager.update_config(cfg)
            QMessageBox.information(self, "保存成功", "AI 配置已保存")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))


def show_llm_settings(parent=None) -> bool:
    """打开 LLM 设置对话框，返回是否保存"""
    dialog = LLMSettingsDialog(parent)
    return dialog.exec() == QDialog.Accepted
