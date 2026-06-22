"""LLM 配置管理器

统一管理全应用的 LLM 配置，包括：
- provider（nvidia/openai/deepseek/moonshot/anthropic/custom）
- api_key
- model
- api_url
- temperature / max_tokens
- 是否启用多模态
- 多模态 model / api_url（可选）

配置持久化到 config/llm_config.json，各 UI 模块共享。
"""
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from voicetrace.core.llm_service import LLMConfig, get_default_api_url, get_default_model

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "llm_config.json"


@dataclass
class AppLLMConfig:
    """应用级 LLM 配置"""
    # 通用文本配置
    provider: str = "nvidia"
    api_key: str = ""
    model: str = "meta/llama3-70b-instruct"
    api_url: str = ""
    temperature: float = 0.6
    max_tokens: int = 1500

    # 多模态配置（可选，用于台风训练图像分析）
    use_multimodal: bool = False
    multimodal_provider: str = "openai"
    multimodal_api_key: str = ""
    multimodal_model: str = "gpt-4o"
    multimodal_api_url: str = ""

    def to_text_config(self) -> LLMConfig:
        """生成文本 LLM 配置"""
        return LLMConfig(
            provider=self.provider,
            api_key=self.api_key,
            model=self.model or get_default_model(self.provider),
            api_url=self.api_url or get_default_api_url(self.provider),
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )

    def to_multimodal_config(self) -> Optional[LLMConfig]:
        """生成多模态 LLM 配置（如果启用）"""
        if not self.use_multimodal:
            return None
        if not self.multimodal_api_key:
            return None
        return LLMConfig(
            provider=self.multimodal_provider,
            api_key=self.multimodal_api_key,
            model=self.multimodal_model or get_default_model(self.multimodal_provider),
            api_url=self.multimodal_api_url or get_default_api_url(self.multimodal_provider),
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppLLMConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class LLMConfigManager:
    """LLM 配置管理器"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or CONFIG_PATH
        self.config = AppLLMConfig()
        self._load()

    def _load(self):
        """从文件加载配置"""
        if not self.config_path.exists():
            logger.info(f"LLM 配置文件不存在，使用默认配置: {self.config_path}")
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.config = AppLLMConfig.from_dict(data)
            logger.info("LLM 配置加载成功")
        except Exception as exc:
            logger.warning(f"加载 LLM 配置失败: {exc}")

    def save(self):
        """保存配置到文件"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("LLM 配置保存成功")
        except Exception as exc:
            logger.error(f"保存 LLM 配置失败: {exc}")
            raise

    def get_config(self) -> AppLLMConfig:
        return self.config

    def update_config(self, config: AppLLMConfig):
        self.config = config
        self.save()

    def get_text_config(self) -> LLMConfig:
        return self.config.to_text_config()

    def get_multimodal_config(self) -> Optional[LLMConfig]:
        return self.config.to_multimodal_config()

    def is_text_available(self) -> bool:
        """文本 LLM 是否可用"""
        return bool(self.config.api_key)

    def is_multimodal_available(self) -> bool:
        """多模态 LLM 是否可用"""
        return self.config.use_multimodal and bool(self.config.multimodal_api_key)

    def get_ai_mode(self) -> str:
        """获取当前 AI 模式：'text' 或 'multimodal'"""
        return "multimodal" if self.config.use_multimodal and bool(self.config.multimodal_api_key) else "text"


# 全局单例
_llm_config_manager: Optional[LLMConfigManager] = None


def get_llm_config_manager() -> LLMConfigManager:
    """获取全局 LLM 配置管理器"""
    global _llm_config_manager
    if _llm_config_manager is None:
        _llm_config_manager = LLMConfigManager()
    return _llm_config_manager
