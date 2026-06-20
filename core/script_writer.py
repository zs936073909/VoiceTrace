"""文案生成核心模块

支持两种生成方式：
1. 本地模板填充：基于 config/script_templates.json 的结构化模板
2. 在线 AI 生成：调用兼容 OpenAI 格式的 API（用户配置）

设计参考：
- OpenAI Chat Completions API 格式
- 本地模板系统参考 jinja2 风格的占位符替换
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


@dataclass
class GenerationResult:
    """文案生成结果"""
    success: bool
    content: str = ""
    error: str = ""
    source: str = ""  # 'template' or 'ai'


class ScriptWriter:
    """文案生成器"""

    def __init__(self, templates_path: Optional[Path] = None):
        if templates_path is None:
            templates_path = Path(__file__).parent.parent / "config" / "script_templates.json"
        self.templates_path = templates_path
        self._templates_cache: Optional[List[dict]] = None

    def load_templates(self) -> List[dict]:
        """加载所有模板"""
        if self._templates_cache is not None:
            return self._templates_cache
        try:
            with open(self.templates_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._templates_cache = data.get("templates", [])
        except (FileNotFoundError, json.JSONDecodeError):
            self._templates_cache = []
        return self._templates_cache

    def get_templates_by_category(self, category: str, language: str = "chinese") -> List[dict]:
        """按类别和语言筛选模板"""
        templates = self.load_templates()
        return [
            t for t in templates
            if t.get("category") == category and t.get("language") == language
        ]

    def get_template(self, name: str) -> Optional[dict]:
        """按名称获取模板"""
        templates = self.load_templates()
        for t in templates:
            if t.get("name") == name:
                return t
        return None

    def generate_from_template(
        self,
        template_name: str,
        values: Dict[str, str]
    ) -> GenerationResult:
        """基于模板填充生成文案

        Args:
            template_name: 模板名称
            values: 占位符键值对

        Returns:
            GenerationResult
        """
        template = self.get_template(template_name)
        if not template:
            return GenerationResult(
                success=False,
                error=f"未找到模板: {template_name}"
            )

        structure = template.get("structure", {})
        if not structure:
            return GenerationResult(
                success=False,
                error="模板结构为空"
            )

        sections = []
        for section_name, content in structure.items():
            if isinstance(content, str):
                filled = self._fill_placeholders(content, values)
                sections.append(f"【{section_name}】\n{filled}")
            elif isinstance(content, list):
                filled_items = [self._fill_placeholders(item, values) for item in content]
                sections.append(f"【{section_name}】\n" + "\n".join(filled_items))

        result_content = "\n\n".join(sections)

        # 附加写作提示
        tips = template.get("tips", "")
        if tips:
            result_content += f"\n\n--- 写作提示 ---\n{tips}"

        return GenerationResult(
            success=True,
            content=result_content,
            source="template"
        )

    def _fill_placeholders(self, text: str, values: Dict[str, str]) -> str:
        """填充 {placeholder} 格式的占位符"""
        for key, val in values.items():
            text = text.replace(f"{{{key}}}", val)
        return text

    def generate_with_ai(
        self,
        prompt: str,
        api_url: str,
        api_key: str,
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.7,
        max_tokens: int = 1500,
        timeout: int = 30
    ) -> GenerationResult:
        """使用在线 AI API 生成文案

        兼容 OpenAI Chat Completions API 格式。
        用户可配置任何兼容的 API 端点（如 OpenAI、DeepSeek、Moonshot 等）。

        Args:
            prompt: 生成提示词
            api_url: API 端点 URL
            api_key: API 密钥
            model: 模型名称
            temperature: 创造性（0-1）
            max_tokens: 最大生成 token 数
            timeout: 超时秒数
        """
        if not REQUESTS_AVAILABLE:
            return GenerationResult(
                success=False,
                error="requests 库未安装。请运行: pip install requests",
                source="ai"
            )

        if not api_url or not api_key:
            return GenerationResult(
                success=False,
                error="请配置 API 地址和密钥",
                source="ai"
            )

        system_prompt = (
            "你是一位专业的播音主持文案专家，擅长撰写新闻播报、即兴评述、"
            "模拟主持和演讲稿。请根据用户的要求生成结构清晰、语言规范的文案，"
            "适合口语表达，注意节奏感和断句。"
        )

        try:
            response = requests.post(
                api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens
                },
                timeout=timeout
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return GenerationResult(
                success=True,
                content=content,
                source="ai"
            )
        except requests.exceptions.Timeout:
            return GenerationResult(
                success=False,
                error="请求超时，请检查网络连接或增加超时时间",
                source="ai"
            )
        except requests.exceptions.ConnectionError:
            return GenerationResult(
                success=False,
                error="无法连接到 API 服务器，请检查 API 地址",
                source="ai"
            )
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "未知"
            return GenerationResult(
                success=False,
                error=f"API 返回错误 (HTTP {status_code})：{str(e)}",
                source="ai"
            )
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return GenerationResult(
                success=False,
                error=f"解析 API 响应失败：{str(e)}",
                source="ai"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                error=f"生成失败：{str(e)}",
                source="ai"
            )

    def build_ai_prompt(
        self,
        category: str,
        topic: str,
        language: str = "chinese",
        duration: str = "2-3分钟",
        style: str = "标准",
        extra_requirements: str = ""
    ) -> str:
        """构建 AI 生成提示词"""
        category_names = {
            "news_broadcast": "新闻播报",
            "improv_commentary": "即兴评述",
            "mock_host": "模拟主持",
            "speech": "演讲稿"
        }
        cat_name = category_names.get(category, category)

        prompt = f"""请为我撰写一篇{cat_name}文案。

主题：{topic}
语言：{'中文' if language == 'chinese' else '英文' if language == 'english' else '中英混合'}
时长：{duration}
风格：{style}

要求：
1. 结构清晰，包含开头、主体、结尾
2. 语言规范，适合口语表达
3. 注意节奏感和断句，便于播音
4. 内容充实，有具体细节
"""
        if extra_requirements:
            prompt += f"5. {extra_requirements}\n"

        prompt += "\n请直接输出文案内容，不要附加解释。"
        return prompt


def is_ai_available() -> bool:
    """检查 AI 在线生成是否可用"""
    return REQUESTS_AVAILABLE
