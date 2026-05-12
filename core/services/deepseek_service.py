"""
DeepSeek Chat API（OpenAI 兼容接口）封装，用于 AI 预问诊多轮对话与结构化摘要提取。
"""
from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from django.conf import settings

if TYPE_CHECKING:
    from core.models import Department

logger = logging.getLogger(__name__)

TRIAGE_SYSTEM_PROMPT_BASE = """你是智慧医疗系统中的「AI 预问诊分诊助手」（你不是执业医师，不能替代医生诊断）。

你的职责：
- 用通俗易懂、温和、专业的简体中文与患者多轮对话，了解症状、起病时间与缓急、部位与性质、程度、加重或缓解因素、伴随症状、相关既往史与近期用药等；
- 每次回复可主动追问 1～2 个关键缺失信息，避免一次堆砌过多问题；
- 严禁给出疾病确诊、具体用药方案或「不必就医」等可能延误诊疗的结论；应适时提醒患者最终以线下医生面诊与检查为准；
- 不做恐吓性表述；若出现胸痛、呼吸困难、意识障碍、大出血等急危描述，应明确建议立即就近急诊。

对话中不要输出 JSON 或病历标题；用自然对话即可。"""

STRUCTURE_EXTRACT_SYSTEM_PROMPT_TEMPLATE = """你是医疗文书辅助工具。根据用户提供的「医患预问诊对话记录」，只输出一个 JSON 对象，不要输出 Markdown 代码块、不要其它解释文字。

{dept_rules}

除了生成供医生阅读的 chief_complaint 和 present_illness 之外，请额外生成一个 patient_summary 字段，供患者端直接阅读。

JSON 必须严格包含且仅包含六个字符串字段：
- "title"：病情关键词标题，2～10 个汉字为宜，概括患者最核心症状或就诊原因（禁止标点、数字、空格作标题主体；若信息极少可填「待查」）；
- "symptom_keyword"：症状关键词，2～4 个汉字，只保留最核心的症状或就诊原因，例如「头痛」「咳嗽」「腹痛」「胸闷」；禁止标点、数字、空格；信息不足填 ""（空字符串）；
- "chief_complaint"：主诉，用一句话概括患者最主要的问题与病程（若信息不足填「待补充」）；
- "present_illness"：现病史，用连贯段落概括起病情况、症状特点、演变、已自行处理或就诊情况（若信息不足填「待补充」）；
- "patient_summary"：患者端病情总结，使用带有人文关怀的第一人称客服口吻，100～150 字左右，将患者的症状用口语串联成一段通顺的总结，例如“根据您的描述，您目前主要感到……，持续了……，建议您……”。不要使用病历格式、编号或项目符号；
- "recommended_dept_name"：必须从上述【可选科室列表】中挑选一个**完全一致**的名称字符串；若对话信息与任何科室均不吻合、或列表为空，则必须填 ""（空字符串）。

不要编造对话中未出现的具体诊断、药名或检查结果。"""


def _format_dept_rules_for_extract(department_names: list[str]) -> str:
    if not department_names:
        return (
            "【可选科室列表】当前为空。recommended_dept_name 必须固定为 \"\"（空字符串）。"
        )
    joined = "、".join(department_names)
    return f"【可选科室列表】（你只能从中选一个名称原样写入 recommended_dept_name，不可自造科室名）：\n{joined}"


def _triage_system_prompt_appendix(department_names: list[str]) -> str:
    if not department_names:
        return ""
    joined = "、".join(department_names)
    return (
        f"\n\n本院已开通线上挂号的科室名称如下（供你了解分诊背景；与患者对话时用自然语言即可，勿整段照读清单）：{joined}"
    )


def resolve_recommended_department(recommended_name: str) -> Department | None:
    """根据模型给出的科室名字符串，在库中匹配一条科室（尽量稳健）。"""
    from core.models import Department

    raw = (recommended_name or "").strip()
    if not raw:
        return None
    qs = Department.objects.filter(is_active=True)
    # 第一道防线：完全精准匹配
    d = qs.filter(name__iexact=raw).first()
    if d:
        return d
    # 第二道防线：模糊包含匹配
    d = qs.filter(name__icontains=raw).first()
    if d:
        return d
    # 第三道防线：反向包含匹配
    for cand in qs.order_by("name"):
        if cand.name and cand.name in raw:
            return cand
    return None


class DeepSeekServiceError(Exception):
    """调用 DeepSeek API 失败。"""


class DeepSeekService:
    """封装多轮对话与结构化病历摘要提取。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = (api_key or getattr(settings, "DEEPSEEK_API_KEY", "") or "").strip()
        self.base_url = (
            base_url or getattr(settings, "DEEPSEEK_API_BASE", "https://api.deepseek.com")
        ).rstrip("/")
        self.model = model or getattr(settings, "DEEPSEEK_MODEL", "deepseek-chat")
        self.timeout = timeout if timeout is not None else int(
            getattr(settings, "DEEPSEEK_TIMEOUT", 120)
        )

    def _post_chat_completions(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise DeepSeekServiceError(
                "未配置 DeepSeek API 密钥，请设置环境变量 DEEPSEEK_API_KEY。"
            )

        url = f"{self.base_url}/v1/chat/completions"
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.5,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HIS-System/1.0",
        )
        req.add_header("Connection", "keep-alive")

        ssl_context = ssl.create_default_context()

        max_retries = 3
        raw: str | None = None
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(
                    req, timeout=self.timeout, context=ssl_context
                ) as resp:
                    raw = resp.read().decode("utf-8")
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                logger.warning("DeepSeek HTTPError %s: %s", e.code, body[:500])
                raise DeepSeekServiceError(
                    f"DeepSeek 接口返回错误（HTTP {e.code}）。"
                ) from e
            except (urllib.error.URLError, ssl.SSLError, ConnectionResetError) as e:
                logger.warning(
                    "[DeepSeek API] 网络请求异常 (尝试 %s/%s): %s",
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt == max_retries - 1:
                    logger.error(
                        "[DeepSeek API] 达到最大重试次数，预问诊请求彻底失败。"
                    )
                    raise DeepSeekServiceError(
                        "无法连接 DeepSeek 服务，请稍后重试。"
                    ) from e
                time.sleep(2**attempt)

        if raw is None:
            raise DeepSeekServiceError("无法连接 DeepSeek 服务，请稍后重试。")

        try:
            data = json.loads(raw)
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            logger.warning("DeepSeek 响应解析失败: %s", raw[:500])
            raise DeepSeekServiceError("DeepSeek 返回格式异常。") from e

    def chat_turn(
        self,
        conversation_messages: list[dict[str, str]],
        department_names: list[str] | None = None,
    ) -> str:
        """
        多轮对话中的一轮：在已有 user/assistant 历史后追加模型回复。
        conversation_messages 仅含 role 为 user 或 assistant 的消息（按时间顺序）。
        """
        dept_names = department_names or []
        system_content = TRIAGE_SYSTEM_PROMPT_BASE + _triage_system_prompt_appendix(
            dept_names
        )
        api_messages = [{"role": "system", "content": system_content}]
        for m in conversation_messages:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                api_messages.append({"role": role, "content": content})
        return self._post_chat_completions(api_messages)

    def extract_structured_summary(
        self,
        conversation_messages: list[dict[str, str]],
        department_names: list[str] | None = None,
    ) -> tuple[dict[str, Any], str, Department | None]:
        """
        根据完整对话生成结构化病历摘要，供写入 AIReport.structured_content。
        返回 (dict, raw_llm_text, 匹配到的推荐科室或 None)。
        """
        dept_names = list(department_names or [])
        lines = []
        for m in conversation_messages:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if role == "user":
                lines.append(f"患者：{content}")
            elif role == "assistant":
                lines.append(f"助手：{content}")
        transcript = "\n".join(lines) if lines else "（无有效对话）"

        dept_rules = _format_dept_rules_for_extract(dept_names)
        system_prompt = STRUCTURE_EXTRACT_SYSTEM_PROMPT_TEMPLATE.format(
            dept_rules=dept_rules
        )

        extract_messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"以下为患者与预问诊助手的对话记录，请按要求只输出 JSON：\n\n{transcript}",
            },
        ]
        raw = self._post_chat_completions(extract_messages)
        parsed = self._parse_summary_json(raw)
        rdn = str(parsed.get("recommended_dept_name", "") or "").strip()
        resolved = resolve_recommended_department(rdn) if rdn else None
        return parsed, raw, resolved

    @staticmethod
    def _parse_summary_json(text: str) -> dict[str, Any]:
        text = text.strip()
        fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return {
                "title": "",
                "chief_complaint": "待补充",
                "present_illness": "待补充",
                "patient_summary": "",
                "symptom_keyword": "",
                "recommended_dept_name": "",
                "parse_error": True,
            }
        title = str(obj.get("title", "") or "").strip()
        cc = str(obj.get("chief_complaint", "") or "待补充").strip() or "待补充"
        pi = str(obj.get("present_illness", "") or "待补充").strip() or "待补充"
        patient_summary = str(obj.get("patient_summary", "") or "").strip()
        rdn = str(obj.get("recommended_dept_name", "") or "").strip()

        sk_raw = str(obj.get("symptom_keyword", "") or "").strip()
        sk = re.sub(r"[^\u4e00-\u9fff]", "", sk_raw)
        if len(sk) > 4:
            sk = sk[:4]
        if sk and len(sk) < 2:
            sk = ""
        if not sk and title:
            sk = re.sub(r"[^\u4e00-\u9fff]", "", title)[:4]
            if len(sk) < 2:
                sk = ""

        return {
            "title": title,
            "chief_complaint": cc,
            "present_illness": pi,
            "patient_summary": patient_summary,
            "recommended_dept_name": rdn,
            "symptom_keyword": sk,
        }
