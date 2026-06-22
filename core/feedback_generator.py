"""基于录音分析结果生成 LLM 智能反馈

把 analyzer 输出的结构化数据转换成自然语言训练建议。
支持本地规则建议（fallback）和 LLM 智能建议两种模式。
"""
import json
from typing import Dict, Any, Optional

from voicetrace.core.llm_service import LLMService, LLMConfig, is_llm_available


class FeedbackGenerator:
    """分析结果反馈生成器"""

    def __init__(self, llm_config: Optional[LLMConfig] = None):
        self.llm_config = llm_config
        self._llm_service = LLMService(llm_config) if llm_config else None

    def set_llm_config(self, config: LLMConfig):
        self.llm_config = config
        self._llm_service = LLMService(config)

    def generate(
        self,
        result: Dict[str, Any],
        script_content: str = "",
        script_language: str = "chinese",
        script_category: str = "news_broadcast",
        use_llm: bool = True
    ) -> Dict[str, str]:
        """生成反馈

        Returns:
            {"summary": "简短总结", "suggestions": "详细建议", "drills": "针对性练习"}
        """
        if use_llm and self._llm_service and is_llm_available():
            llm_feedback = self._generate_llm_feedback(
                result, script_content, script_language, script_category
            )
            if llm_feedback["success"]:
                return {
                    "summary": llm_feedback.get("summary", ""),
                    "suggestions": llm_feedback.get("suggestions", ""),
                    "drills": llm_feedback.get("drills", ""),
                    "source": "llm"
                }

        # fallback: 使用本地规则生成建议
        local = self._generate_local_feedback(result, script_language, script_category)
        return {**local, "source": "local"}

    def _generate_llm_feedback(
        self,
        result: Dict[str, Any],
        script_content: str,
        script_language: str,
        script_category: str
    ) -> Dict[str, Any]:
        """调用 LLM 生成反馈"""
        prompt = self._build_feedback_prompt(result, script_content, script_language, script_category)

        system_prompt = (
            "你是一位资深的播音主持训练导师，擅长根据录音分析数据给出精准、"
            "可执行的训练建议。请用中文回答，分点清晰，语气鼓励但专业。"
        )

        response = self._llm_service.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system_prompt,
            temperature=0.6,
            max_tokens=2000
        )

        if not response.success:
            return {"success": False, "error": response.error}

        return self._parse_llm_response(response.content)

    def _build_feedback_prompt(
        self,
        result: Dict[str, Any],
        script_content: str,
        script_language: str,
        script_category: str
    ) -> str:
        """构建反馈 prompt"""
        rate = result.get("speech_rate", 0)
        pause_count = result.get("pause_count", 0)
        total_pause = result.get("total_pause_duration", 0)
        duration = result.get("duration", 0)
        energy = result.get("rms_energy", 0)
        prosody = result.get("prosody") or {}
        alignment = result.get("alignment") or {}
        sentences_json = result.get("sentence_analysis_json", "[]")

        unit = "CPM" if script_language == "chinese" else "WPM"

        # 计算一些衍生指标
        pause_ratio = total_pause / duration if duration > 0 else 0
        missing_count = 0
        if alignment and alignment.get("sentences"):
            for s in alignment["sentences"]:
                for t in s.get("tokens", []):
                    if t.get("is_missing"):
                        missing_count += 1

        sentences = []
        try:
            sentences = json.loads(sentences_json)
        except json.JSONDecodeError:
            pass

        problem_sentences = []
        for s in sentences:
            s_rate = s.get("rate", 0)
            s_pauses = s.get("pause_count", 0)
            s_pause_dur = s.get("pause_duration", 0)
            if s_rate > rate * 1.3 or s_rate < rate * 0.7 or s_pauses >= 2 or s_pause_dur > 1.0:
                problem_sentences.append({
                    "index": s.get("index", 0),
                    "text": s.get("sentence", "")[:60],
                    "rate": round(s_rate, 1),
                    "pauses": s_pauses,
                    "pause_duration": round(s_pause_dur, 2)
                })

        prompt = f"""请根据以下播音练习的录音分析数据，给出专业训练反馈。

## 基础信息
- 语言：{'中文' if script_language == 'chinese' else '英文'}
- 稿件类型：{script_category}
- 录音时长：{duration:.1f} 秒

## 核心指标
- 语速：{rate:.0f} {unit}
- 卡顿次数：{pause_count} 次
- 总停顿时长：{total_pause:.1f} 秒（占时长 {pause_ratio:.1%}）
- 声音能量：{energy:.4f}
- 字级对齐漏读/错读：{missing_count} 处
"""

        if prosody:
            prompt += f"""
## 韵律指标
- 平均基频：{prosody.get('f0_mean', '--')} Hz
- 基频标准差：{prosody.get('f0_std', '--')} Hz
- 平均强度：{prosody.get('intensity_mean', '--')} dB
- 谐噪比 HNR：{prosody.get('hnr_mean', '--')} dB
- 声调得分：{prosody.get('tone_score', '--')}
"""

        if problem_sentences:
            prompt += "\n## 问题句子（前5句）\n"
            for ps in problem_sentences[:5]:
                prompt += f"- 第 {ps['index']} 句：{ps['text']}... （语速 {ps['rate']}，卡顿 {ps['pauses']} 次，停顿 {ps['pause_duration']}s）\n"

        if script_content:
            prompt += f"\n## 练习稿件（前300字）\n{script_content[:300]}\n"

        prompt += """
## 输出要求
请严格按以下 JSON 格式输出（不要包含 markdown 代码块标记）：
{
  "summary": "30字以内的整体评价",
  "suggestions": "分点列出3-5条具体改进建议，每条建议说明问题、原因和练习方法",
  "drills": "给出2-3个今天就能做的针对性练习动作"
}
"""
        return prompt

    def _parse_llm_response(self, content: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON"""
        # 先尝试直接解析
        try:
            data = json.loads(content)
            return {
                "success": True,
                "summary": data.get("summary", ""),
                "suggestions": data.get("suggestions", ""),
                "drills": data.get("drills", "")
            }
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        import re
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return {
                    "success": True,
                    "summary": data.get("summary", ""),
                    "suggestions": data.get("suggestions", ""),
                    "drills": data.get("drills", "")
                }
            except json.JSONDecodeError:
                pass

        # 如果都不是 JSON，把全部内容作为 suggestions
        return {
            "success": True,
            "summary": "已生成智能反馈",
            "suggestions": content,
            "drills": ""
        }

    def _generate_local_feedback(
        self,
        result: Dict[str, Any],
        script_language: str,
        script_category: str
    ) -> Dict[str, str]:
        """本地规则反馈（不依赖 LLM）"""
        rate = result.get("speech_rate", 0)
        pause_count = result.get("pause_count", 0)
        total_pause = result.get("total_pause_duration", 0)
        duration = result.get("duration", 0)
        energy = result.get("rms_energy", 0)
        prosody = result.get("prosody") or {}

        unit = "CPM" if script_language == "chinese" else "WPM"

        summary_parts = []
        suggestions = []
        drills = []

        # 语速
        if 200 <= rate <= 300:
            summary_parts.append("语速适中")
        elif rate > 300:
            summary_parts.append("语速偏快")
            suggestions.append(f"语速偏快（{rate:.0f} {unit}），建议在关键数据、金句处放慢，增加语义停顿。")
            drills.append("选一段 100 字稿件，先用正常语速读，再刻意放慢 20% 读，录下来对比。")
        else:
            summary_parts.append("语速偏慢")
            suggestions.append(f"语速偏慢（{rate:.0f} {unit}），尝试减少不必要的停顿，保持语流连贯。")
            drills.append("用节拍器设定 120 BPM，每拍读一个字，练习 1 分钟后再自由发挥。")

        # 停顿
        if duration > 0:
            pause_ratio = total_pause / duration
            if pause_count == 0:
                summary_parts.append("语流连贯")
            elif pause_ratio > 0.25:
                summary_parts.append("停顿偏多")
                suggestions.append(f"停顿占比偏高（{pause_ratio:.1%}），建议提前通读稿件，减少因忘词导致的空白。")
                drills.append("把稿件分成意群，用斜线标出换气点，只在这些地方停顿。")
            else:
                summary_parts.append("停顿合理")

        # 音量
        if energy < 0.15:
            summary_parts.append("音量偏小")
            suggestions.append("声音能量偏低，建议提高发声力度或拉近麦克风距离。")
            drills.append("练习「气泡音+叹气」找发声支撑，录音时保持 20cm 距离。")
        elif energy > 0.3:
            summary_parts.append("音量充沛")

        # 韵律
        f0_std = prosody.get("f0_std")
        if f0_std is not None:
            if f0_std < 15:
                suggestions.append("语调较平，可在强调处提高音高、句尾适当降调，增加层次感。")
                drills.append("朗读同一句话，分别用「陈述/疑问/感叹」三种语气录下来对比。")
            elif f0_std > 45:
                suggestions.append("语调起伏过大，注意控制情绪表达，避免过度夸张。")

        hnr = prosody.get("hnr_mean")
        if hnr is not None and hnr < 10:
            suggestions.append("录音环境噪音较明显，建议改善环境或使用降噪功能。")

        return {
            "summary": ", ".join(summary_parts) if summary_parts else "分析完成",
            "suggestions": "\n".join(f"{i+1}. {s}" for i, s in enumerate(suggestions)) if suggestions else "暂无特别建议，保持良好状态。",
            "drills": "\n".join(f"{i+1}. {d}" for i, d in enumerate(drills)) if drills else "坚持每日录音练习，观察趋势变化。"
        }
