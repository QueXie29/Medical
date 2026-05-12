"""通用工具：操作审计日志等。"""

from __future__ import annotations

import logging
from ipaddress import ip_address

from core.models import OperationLog

logger = logging.getLogger(__name__)


def get_client_ip(request) -> str | None:
    """
    获取客户端 IP：优先 `request.META['HTTP_X_FORWARDED_FOR']` 第一项，
    否则使用 `request.META['REMOTE_ADDR']`。
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        part = xff.split(",")[0].strip()
        if part:
            return part
    return request.META.get("REMOTE_ADDR") or None


def _normalize_ip_for_field(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        ip_address(raw)
        return raw
    except ValueError:
        return None


def record_operation_log(
    request,
    action_type: str,
    module: str,
    description: str,
    *,
    actor=None,
) -> None:
    """
    写入一条 `OperationLog`。IP 来自 `HTTP_X_FORWARDED_FOR` 或 `REMOTE_ADDR`。
    action_type 使用 OperationLog.ActionType 取值：CREATE / UPDATE / DELETE / LOGIN。
    若传入 `actor`（如注册成功时尚未 session 登录），则以其作为操作人；否则用当前登录用户。
    失败时仅记录日志，不中断业务。
    """
    if actor is not None:
        user = actor
    else:
        user = (
            request.user
            if getattr(request, "user", None) and request.user.is_authenticated
            else None
        )
    ip = _normalize_ip_for_field(get_client_ip(request))
    print(f"--- 准备写入日志: {action_type} | {module} | {description} ---")
    try:
        OperationLog.objects.create(
            user=user,
            action_type=action_type,
            module=module,
            description=(description or "")[:2000],
            ip_address=ip,
        )
    except Exception as e:
        print(f"!!! 日志写入失败: {e} !!!")
        logger.exception("record_operation_log failed: %s %s", module, action_type)
