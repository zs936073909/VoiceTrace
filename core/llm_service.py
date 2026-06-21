"""LLM 服务层：统一多模型 Provider 接口

支持 Provider：
- nvidia: NVIDIA NIM API (https://integrate.api.nvidia.com/v1)
- openai: OpenAI / 兼容 OpenAI 的 API
- anthropic: Anthropic Claude API
- deepseek: DeepSeek API
- moonshot: Moonshot (Kimi) API
- custom: 任意兼容 OpenAI Chat Completions 的自定义端点

所有 Provider 最终都通过统一的 chat_completion 接口调用。
"""
import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any


try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class LLMProviderType(str, Enum):
    NVIDIA = "nvidia"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    MOONSHOT = "moonshot"
    CUSTOM = "custom"


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = "nvidia"
    api_key: str = ""
    model: str = "meta/llama3-70b-instruct"
    api_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 1500
    timeout: int = 60
    extra_headers: Optional[Dict[str, str]] = None

    def __post_init__(self):
        # 如果没有指定 api_url，根据 provider 使用默认地址
        if not self.api_url:
            self.api_url = get_default_api_url(self.provider)


def get_default_api_url(provider: str) -> str:
    """获取各 Provider 默认 API 地址"""
    urls = {
        LLMProviderType.NVIDIA: "https://integrate.api.nvidia.com/v1/chat/completions",
        LLMProviderType.OPENAI: "https://api.openai.com/v1/chat/completions",
        LLMProviderType.ANTHROPIC: "https://api.anthropic.com/v1/messages",
        LLMProviderType.DEEPSEEK: "https://api.deepseek.com/v1/chat/completions",
        LLMProviderType.MOONSHOT: "https://api.moonshot.cn/v1/chat/completions",
        LLMProviderType.CUSTOM: "",
    }
    return urls.get(provider, urls[LLMProviderType.CUSTOM])


def get_default_model(provider: str) -> str:
    """获取各 Provider 默认模型"""
    models = {
        LLMProviderType.NVIDIA: "meta/llama3-70b-instruct",
        LLMProviderType.OPENAI: "gpt-3.5-turbo",
        LLMProviderType.ANTHROPIC: "claude-3-haiku-20240307",
        LLMProviderType.DEEPSEEK: "deepseek-chat",
        LLMProviderType.MOONSHOT: "moonshot-v1-8k",
        LLMProviderType.CUSTOM: "",
    }
    return models.get(provider, "")


@dataclass
class LLMResponse:
    """LLM 调用结果"""
    success: bool
    content: str = ""
    error: str = ""
    raw_response: Any = None


def is_llm_available() -> bool:
    """检查 LLM 调用依赖是否可用"""
    return REQUESTS_AVAILABLE


class LLMService:
    """统一 LLM 服务"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()

    def set_config(self, config: LLMConfig):
        self.config = config

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None
    ) -> LLMResponse:
        """统一对话补全接口

        Args:
            messages: [{"role": "user"/"assistant", "content": "..."}]
            temperature: 覆盖配置的温度
            max_tokens: 覆盖配置的最大 token
            system_prompt: 系统提示词（部分 provider 支持）
        """
        if not REQUESTS_AVAILABLE:
            return LLMResponse(
                success=False,
                error="requests 库未安装。请运行: pip install requests"
            )

        if not self.config.api_key:
            return LLMResponse(
                success=False,
                error="API 密钥未配置"
            )

        if not self.config.api_url:
            return LLMResponse(
                success=False,
                error="API 地址未配置"
            )

        provider = self.config.provider.lower()
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        try:
            if provider == LLMProviderType.ANTHROPIC:
                return self._call_anthropic(messages, temp, tokens, system_prompt)
            else:
                # NVIDIA / OpenAI / DeepSeek / Moonshot / CUSTOM 都兼容 OpenAI 格式
                return self._call_openai_compatible(messages, temp, tokens, system_prompt)
        except requests.exceptions.Timeout:
            return LLMResponse(
                success=False,
                error="请求超时，请检查网络连接或增加超时时间"
            )
        except requests.exceptions.ConnectionError:
            return LLMResponse(
                success=False,
                error="无法连接到 API 服务器，请检查 API 地址和网络"
            )
        except Exception as e:
            return LLMResponse(
                success=False,
                error=f"LLM 调用失败: {str(e)}"
            )

    def _call_openai_compatible(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str]
    ) -> LLMResponse:
        """调用兼容 OpenAI 格式的 API"""
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        # NVIDIA 部分模型需要 accept: application/json
        headers.setdefault("Accept", "application/json")

        payload = {
            "model": self.config.model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        response = requests.post(
            self.config.api_url,
            headers=headers,
            json=payload,
            timeout=self.config.timeout
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        return LLMResponse(success=True, content=content.strip(), raw_response=data)

    def _call_anthropic(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str]
    ) -> LLMResponse:
        """调用 Anthropic Messages API"""
        headers = {
            "x-api-key": self.config.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = requests.post(
            self.config.api_url,
            headers=headers,
            json=payload,
            timeout=self.config.timeout
        )
        response.raise_for_status()
        data = response.json()

        content = data["content"][0]["text"]
        return LLMResponse(success=True, content=content.strip(), raw_response=data)


def quick_chat(
    prompt: str,
    provider: str = "nvidia",
    api_key: str = "",
    model: str = "",
    api_url: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1500,
    system_prompt: str = ""
) -> LLMResponse:
    """快速调用 LLM 的便捷函数"""
    config = LLMConfig(
        provider=provider,
        api_key=api_key,
        model=model or get_default_model(provider),
        api_url=api_url or get_default_api_url(provider),
        temperature=temperature,
        max_tokens=max_tokens
    )
    service = LLMService(config)
    return service.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        system_prompt=system_prompt or None
    )
