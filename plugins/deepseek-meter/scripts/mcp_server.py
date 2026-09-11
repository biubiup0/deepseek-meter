#!/usr/bin/env python3
"""Minimal MCP stdio server exposing DeepSeek balance and spend tools.

Implements the subset of Model Context Protocol that Codex uses:
``initialize``, ``tools/list``, ``tools/call`` and ``ping``. Transport is
newline-delimited JSON-RPC 2.0 over stdio.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deepseek_meter as meter  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "deepseek-meter"
SERVER_VERSION = "0.1.0"

TOOLS = [
    {
        "name": "get_balance",
        "description": (
            "Read the DeepSeek platform account balance from the official "
            "/user/balance endpoint. Results are cached briefly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {
                    "type": "boolean",
                    "description": "Bypass the short-lived cache and query the API now.",
                }
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "get_session_cost",
        "description": (
            "Estimate what the current (or a given) Codex session cost, based on the "
            "token usage recorded in the session transcript and DeepSeek's official prices."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Codex session id. Defaults to the most recent session.",
                },
                "transcript_path": {
                    "type": "string",
                    "description": "Explicit rollout transcript path, if known.",
                },
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "get_usage_summary",
        "description": (
            "Aggregate DeepSeek spend and token usage across Codex sessions from the "
            "last N days (default 7)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "number",
                    "description": "How many days back to include. Default 7.",
                }
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "refresh_prices",
        "description": (
            "Fetch the official DeepSeek price table now instead of waiting for the daily "
            "refresh, and report the active rates."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
]


def newest_transcript():
    root = meter.CODEX_HOME / "sessions"
    if not root.exists():
        return None
    files = sorted(
        root.glob("**/rollout-*.jsonl"),
        key=lambda item: item.stat().st_mtime,
    )
    return meter._prefer_main(files)


def recent_transcripts(days: float):
    root = meter.CODEX_HOME / "sessions"
    if not root.exists():
        return []
    cutoff = meter._now() - max(1, days) * 86400
    found = []
    for path in root.glob("**/rollout-*.jsonl"):
        try:
            if path.stat().st_mtime >= cutoff:
                found.append(path)
        except Exception:
            continue
    return sorted(found, key=lambda item: item.stat().st_mtime)


def tool_get_balance(args: dict) -> str:
    balance = meter.fetch_balance(force=bool(args.get("force")), timeout=8.0)
    if not balance.get("ok"):
        return "无法读取余额：%s" % balance.get("error")
    lines = [
        "DeepSeek 账户余额：%s%s"
        % (meter._symbol(balance.get("currency")), balance.get("total_balance")),
        "- 赠送余额：%s%s"
        % (meter._symbol(balance.get("currency")), balance.get("granted_balance")),
        "- 充值余额：%s%s"
        % (meter._symbol(balance.get("currency")), balance.get("topped_up_balance")),
        "- 账户可用：%s" % ("是" if balance.get("is_available") else "否"),
        "- 充值页面：%s" % meter.TOPUP_URL,
    ]
    if balance.get("cached"):
        lines.append("- 数据来自短时缓存" + ("（接口暂时不可用）" if balance.get("stale") else ""))
    return "\n".join(lines)


def tool_get_session_cost(args: dict) -> str:
    meter.refresh_prices_if_stale()
    transcript = args.get("transcript_path")
    if not transcript:
        path = None
        session_id = args.get("session_id")
        if session_id:
            path = meter.find_transcript(session_id)
        if path is None:
            path = newest_transcript()
        transcript = str(path) if path else None
    session, turn = meter.summarize_session_and_turn(transcript)
    if not session.get("calls"):
        return "没有找到本会话的 token 用量记录。"
    balance = meter.fetch_balance(timeout=6.0)
    blocks = []
    if turn.get("calls"):
        blocks.append(meter.detail_text(turn, balance))
    if session.get("calls") and int(session.get("turn_count") or 0) > 1:
        blocks.append(meter.detail_text(session, balance))
    return "\n\n".join(blocks)


def tool_get_usage_summary(args: dict) -> str:
    meter.refresh_prices_if_stale()
    try:
        days = float(args.get("days") or 7)
    except Exception:
        days = 7.0
    paths = recent_transcripts(days)
    if not paths:
        return "最近 %g 天没有找到会话记录。" % days

    total_cost = 0.0
    total_tokens = 0
    total_calls = 0
    per_day = {}
    for path in paths:
        summary = meter.summarize_transcript(path)
        if not summary.get("calls"):
            continue
        total_cost += summary.get("cost") or 0.0
        total_tokens += int(summary.get("total_tokens") or 0)
        total_calls += int(summary.get("calls") or 0)
        day = (summary.get("started_at") or "")[:10]
        bucket = per_day.setdefault(day, {"cost": 0.0, "tokens": 0})
        bucket["cost"] += summary.get("cost") or 0.0
        bucket["tokens"] += int(summary.get("total_tokens") or 0)

    currency = meter.load_prices().get("currency", "CNY")
    symbol = meter._symbol(currency)
    lines = [
        "最近 %g 天：%d 个会话 · %d 次模型调用 · %s tokens · 估算花费 %s%.4f"
        % (days, len(paths), total_calls, meter._short_number(total_tokens), symbol, total_cost)
    ]
    for day in sorted(per_day, reverse=True)[:10]:
        bucket = per_day[day]
        lines.append(
            "- %s：%s tokens · %s%.4f" % (day, meter._short_number(bucket["tokens"]), symbol, bucket["cost"])
        )
    balance = meter.fetch_balance(timeout=6.0)
    lines.append("- %s" % meter.balance_text(balance))
    return "\n".join(lines)


def tool_refresh_prices(args: dict) -> str:
    result = meter.refresh_prices_if_stale(force=True, timeout=10.0)
    source = meter.price_source()
    prices = meter.load_prices()
    symbol = meter._symbol(prices.get("currency"))

    if result.get("updated"):
        lines = ["价目表已从官方页面更新：%s" % source["label"]]
    elif result.get("ok"):
        lines = ["价目表已是最新：%s" % source["label"]]
    else:
        lines = ["在线更新失败（%s），继续使用：%s" % (result.get("error"), source["label"])]

    for model in ("deepseek-flash", "deepseek-v4-pro"):
        spec = (prices.get("models") or {}).get(model)
        if not spec:
            continue
        lines.append(
            "- %s：缓存命中输入 %s%s / 未命中输入 %s%s / 输出 %s%s"
            % (
                model,
                symbol,
                spec["cache_hit"]["off"],
                symbol,
                spec["cache_miss"]["off"],
                symbol,
                spec["output"]["off"],
            )
        )
    lines.append(
        "以上为每百万 tokens 的空闲价；高峰时段（北京时间周一至周五 9:00-12:00、14:00-18:00）为两倍。"
    )
    return "\n".join(lines)


HANDLERS = {
    "get_balance": tool_get_balance,
    "get_session_cost": tool_get_session_cost,
    "get_usage_summary": tool_get_usage_summary,
    "refresh_prices": tool_refresh_prices,
}


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def result(message_id, text: str, is_error: bool = False) -> None:
    send(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            },
        }
    )


def handle(message: dict) -> None:
    method = message.get("method")
    message_id = message.get("id")

    if method == "initialize":
        params = message.get("params") or {}
        version = params.get("protocolVersion") or PROTOCOL_VERSION
        send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": (
                        "DeepSeek account balance and Codex session spend. "
                        "Use get_balance for the account balance, get_session_cost for the "
                        "current session spend, and get_usage_summary for a multi-day rollup."
                    ),
                },
            }
        )
        return

    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return

    if method == "ping":
        send({"jsonrpc": "2.0", "id": message_id, "result": {}})
        return

    if method == "tools/list":
        send({"jsonrpc": "2.0", "id": message_id, "result": {"tools": TOOLS}})
        return

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            result(message_id, "未知工具：%s" % name, is_error=True)
            return
        try:
            result(message_id, handler(args if isinstance(args, dict) else {}))
        except Exception as exc:
            meter.log("tool %s failed: %r" % (name, exc))
            result(message_id, "工具执行失败：%r" % (exc,), is_error=True)
        return

    if message_id is not None:
        send(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {"code": -32601, "message": "Method not found: %s" % method},
            }
        )


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception:
            continue
        if not isinstance(message, dict):
            continue
        try:
            handle(message)
        except Exception as exc:
            meter.log("mcp handler failed: %r" % (exc,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
