#!/usr/bin/env python3
"""Shared helpers for the deepseek-meter Codex plugin.

Standard library only, works on Python 3.9+ (the system /usr/bin/python3).
Two data sources:

* Account balance  -> DeepSeek official ``GET /user/balance``.
* Session spend    -> Codex session transcripts, which record one
  ``token_usage_record`` per model call with input / cached / output tokens.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))

_data_env = os.environ.get("PLUGIN_DATA")
DATA_DIR = Path(_data_env) if _data_env else (CODEX_HOME / "deepseek-meter")

# User-editable files always live at a stable path, even when Codex runs the
# plugin with its own PLUGIN_DATA directory for cache and logs.
USER_DIR = CODEX_HOME / "deepseek-meter"
CONFIG_FILE = USER_DIR / "config.json"
PRICE_FILE = USER_DIR / "prices.json"
SETTINGS_FILE = USER_DIR / "settings.json"
CACHE_FILE = DATA_DIR / "balance-cache.json"
LOG_FILE = DATA_DIR / "meter.log"
PRICE_CACHE_FILE = DATA_DIR / "prices-cache.json"

BALANCE_URL = "https://api.deepseek.com/user/balance"
DEFAULT_CACHE_TTL = 60
PRICE_PAGE_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing"
PRICE_REFRESH_HOURS = 24

# Display toggles, editable through the ``configure`` MCP tool or by hand.
DEFAULT_SETTINGS = {
    "show_in_reply": True,
    "show_in_hook": True,
}

# CNY per 1M tokens, from the official Chinese pricing page
# (https://api-docs.deepseek.com/zh-cn/quick_start/pricing).
# Off-peak is half of peak. Peak hours are Beijing time (UTC+8) Mon-Fri
# 09:00-12:00 and 14:00-18:00, i.e. 01:00-04:00 and 06:00-10:00 UTC.
DEFAULT_PRICES = {
    "currency": "CNY",
    "models": {
        "deepseek-flash": {
            "cache_hit": {"peak": 0.04, "off": 0.02},
            "cache_miss": {"peak": 2.0, "off": 1.0},
            "output": {"peak": 8.0, "off": 4.0},
        },
        "deepseek-v4-pro": {
            "cache_hit": {"peak": 0.30, "off": 0.15},
            "cache_miss": {"peak": 9.0, "off": 4.5},
            "output": {"peak": 27.0, "off": 13.5},
        },
    },
    "aliases": {
        "deepseek-v4-flash": "deepseek-flash",
        "deepseek-v4-flash-vision-exp": "deepseek-flash",
        "deepseek-v4-pro-0813": "deepseek-v4-pro",
        "deepseek-reasoner": "deepseek-v4-pro",
        "deepseek-chat": "deepseek-flash",
    },
}


def _now() -> float:
    return time.time()


def log(message: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write("%s %s\n" % (stamp, message))
    except Exception:
        pass


def load_settings() -> dict:
    """Display toggles; missing or malformed values fall back to the defaults."""
    data = _read_json(SETTINGS_FILE) or _read_json(DATA_DIR / "settings.json") or {}
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        for key in DEFAULT_SETTINGS:
            if isinstance(data.get(key), bool):
                settings[key] = data[key]
    return settings


def save_settings(updates: dict) -> dict:
    """Persist the toggles and return the resulting settings."""
    settings = load_settings()
    if isinstance(updates, dict):
        for key in DEFAULT_SETTINGS:
            if isinstance(updates.get(key), bool):
                settings[key] = updates[key]
    _write_json(SETTINGS_FILE, settings)
    return settings


def _read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _write_json(path: Path, payload) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        tmp.replace(path)
    except Exception as exc:
        log("write %s failed: %s" % (path, exc))


def _merge_prices(base: dict, override) -> dict:
    if not isinstance(override, dict):
        return base
    if isinstance(override.get("currency"), str):
        base["currency"] = override["currency"]
    models = override.get("models")
    if isinstance(models, dict):
        for name, spec in models.items():
            if isinstance(spec, dict):
                base["models"][name] = spec
    aliases = override.get("aliases")
    if isinstance(aliases, dict):
        base["aliases"].update(aliases)
    return base


def _online_price_cache():
    """Price table fetched from the official pricing page by the daily refresh."""
    data = _read_json(PRICE_CACHE_FILE)
    if isinstance(data, dict) and isinstance(data.get("models"), dict) and data["models"]:
        return data
    return None


def load_prices() -> dict:
    """Defaults, then the daily online table, then user overrides on top."""
    prices = json.loads(json.dumps(DEFAULT_PRICES))
    _merge_prices(prices, _online_price_cache())
    _merge_prices(prices, _read_json(PRICE_FILE))
    _merge_prices(prices, _read_json(DATA_DIR / "prices.json"))
    return prices


def price_source() -> dict:
    """Where the active price table came from, for reports."""
    user = _read_json(PRICE_FILE) or _read_json(DATA_DIR / "prices.json")
    if isinstance(user, dict) and isinstance(user.get("models"), dict) and user["models"]:
        return {"kind": "user", "label": "本地覆盖文件 prices.json"}
    online = _online_price_cache()
    if online:
        fetched = float(online.get("fetched_at") or 0)
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(fetched)) if fetched else "时间未知"
        return {
            "kind": "online",
            "label": "官方在线价目表（%s 更新）" % stamp,
            "fetched_at": fetched,
        }
    return {"kind": "builtin", "label": "内置默认价目表"}


_MONEY_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*元")


def _flatten_html(raw: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text))


def parse_price_page(raw_html: str):
    """Parse the official Chinese pricing page into a price table.

    The page lists prices in this order, each row holding the off-peak and peak
    value for deepseek-flash followed by deepseek-v4-pro:
    cache-hit input, cache-miss input, output.
    """
    text = _flatten_html(raw_html)
    anchor = text.find("百万tokens输入")
    if anchor < 0:
        anchor = text.find("价格")
    if anchor < 0:
        return None

    numbers = [float(item) for item in _MONEY_RE.findall(text[anchor : anchor + 1200])]
    if len(numbers) < 12:
        return None
    flash_hit_off, pro_hit_off, flash_hit_peak, pro_hit_peak = numbers[0:4]
    flash_miss_off, pro_miss_off, flash_miss_peak, pro_miss_peak = numbers[4:8]
    flash_out_off, pro_out_off, flash_out_peak, pro_out_peak = numbers[8:12]

    def consistent(off, peak):
        return off > 0 and peak > 0 and abs(peak - 2 * off) <= max(0.01, off * 0.05)

    checks = [
        consistent(flash_hit_off, flash_hit_peak),
        consistent(pro_hit_off, pro_hit_peak),
        consistent(flash_miss_off, flash_miss_peak),
        consistent(pro_miss_off, pro_miss_peak),
        consistent(flash_out_off, flash_out_peak),
        consistent(pro_out_off, pro_out_peak),
        flash_hit_off < flash_miss_off < flash_out_off,
        pro_hit_off < pro_miss_off < pro_out_off,
    ]
    if not all(checks):
        return None

    return {
        "currency": "CNY",
        "source": PRICE_PAGE_URL,
        "models": {
            "deepseek-flash": {
                "cache_hit": {"off": flash_hit_off, "peak": flash_hit_peak},
                "cache_miss": {"off": flash_miss_off, "peak": flash_miss_peak},
                "output": {"off": flash_out_off, "peak": flash_out_peak},
            },
            "deepseek-v4-pro": {
                "cache_hit": {"off": pro_hit_off, "peak": pro_hit_peak},
                "cache_miss": {"off": pro_miss_off, "peak": pro_miss_peak},
                "output": {"off": pro_out_off, "peak": pro_out_peak},
            },
        },
    }


def refresh_prices_if_stale(force: bool = False, timeout: float = 6.0) -> dict:
    """Refresh the official price table at most once a day. Never raises."""
    cache = _read_json(PRICE_CACHE_FILE) or {}
    fetched_at = float(cache.get("fetched_at") or 0)
    age_hours = (time.time() - fetched_at) / 3600.0 if fetched_at else None
    have_cache = isinstance(cache.get("models"), dict) and bool(cache["models"])

    if not force and have_cache and age_hours is not None and age_hours < PRICE_REFRESH_HOURS:
        return {"ok": True, "updated": False, "age_hours": age_hours, "source": "cache"}

    try:
        request = urllib.request.Request(
            PRICE_PAGE_URL,
            headers={"User-Agent": "deepseek-meter", "Accept": "text/html"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
        parsed = parse_price_page(raw)
        if not parsed:
            raise ValueError("price page layout not recognised")
        parsed["fetched_at"] = time.time()
        _write_json(PRICE_CACHE_FILE, parsed)
        log("price table refreshed from %s" % PRICE_PAGE_URL)
        return {"ok": True, "updated": True, "age_hours": 0.0, "source": "online"}
    except Exception as exc:
        log("price refresh failed: %r" % (exc,))
        return {
            "ok": False,
            "updated": False,
            "age_hours": age_hours,
            "source": "cache" if have_cache else "builtin",
            "error": str(exc),
        }


def resolve_model(model: str, prices: dict) -> str:
    name = (model or "").strip()
    if not name:
        name = read_config_value("model") or "deepseek-flash"
    return prices.get("aliases", {}).get(name, name)


def _parse_toml_section(text: str, section: str) -> dict:
    """Minimal TOML reader for one flat table (Python 3.9 has no tomllib)."""
    values = {}
    header = "[%s]" % section
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            inside = line == header
            continue
        if not inside or not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _codex_config_text() -> str:
    path = CODEX_HOME / "config.toml"
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_config_value(key: str):
    for raw in _codex_config_text().splitlines():
        line = raw.strip()
        if line.startswith(key) and "=" in line and not line.startswith("["):
            value = line.split("=", 1)[1].split("#", 1)[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return None


def find_api_key() -> str:
    """Locate the DeepSeek API key without ever printing it."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key.strip()

    cfg = _read_json(CONFIG_FILE) or _read_json(DATA_DIR / "config.json")
    if isinstance(cfg, dict) and isinstance(cfg.get("api_key"), str):
        return cfg["api_key"].strip()

    provider = read_config_value("model_provider")
    section = "model_providers.%s" % (provider or "deepseek")
    values = _parse_toml_section(_codex_config_text(), section)
    for field in ("experimental_bearer_token", "api_key", "bearer_token", "api_key_env_var"):
        value = values.get(field)
        if not value:
            continue
        if field == "api_key_env_var":
            env_value = os.environ.get(value)
            if env_value:
                return env_value.strip()
            continue
        return value.strip()
    return ""


def is_peak(moment: datetime) -> bool:
    """Peak hours: 01:00-04:00 and 06:00-10:00 UTC, Monday through Friday."""
    utc = moment.astimezone(timezone.utc)
    if utc.weekday() > 4:
        return False
    hour = utc.hour
    return (1 <= hour < 4) or (6 <= hour < 10)


def _parse_timestamp(value: str) -> datetime:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except Exception:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _rate(spec: dict, key: str, moment: datetime) -> float:
    tier = spec.get(key) or {}
    field = "peak" if is_peak(moment) else "off"
    try:
        return float(tier.get(field, 0.0) or 0.0)
    except Exception:
        return 0.0


def price_usage(usage: dict, moment: datetime, model: str, prices: dict) -> float:
    """Return the USD cost of one usage record."""
    name = resolve_model(model, prices)
    spec = prices.get("models", {}).get(name)
    if not spec:
        return 0.0
    total_in = int(usage.get("input_tokens") or 0)
    cached = int(usage.get("cached_input_tokens") or 0)
    cached = max(0, min(cached, total_in))
    fresh = total_in - cached
    output = int(usage.get("output_tokens") or 0)

    million = 1_000_000.0
    return (
        fresh * _rate(spec, "cache_miss", moment)
        + cached * _rate(spec, "cache_hit", moment)
        + output * _rate(spec, "output", moment)
    ) / million


def find_transcript(session_id: str):
    """Best-effort lookup of a rollout transcript by session id."""
    if not session_id:
        return None
    root = CODEX_HOME / "sessions"
    if not root.exists():
        return None
    matches = sorted(
        root.glob("**/rollout-*%s*.jsonl" % session_id),
        key=lambda item: item.stat().st_mtime,
    )
    return _prefer_main(matches)


def is_subagent_transcript(path) -> bool:
    """Subagent transcripts (for example guardian review) are separate files."""
    try:
        with open(path, encoding="utf-8") as handle:
            first = json.loads(handle.readline() or "{}")
    except Exception:
        return False
    payload = first.get("payload") or {}
    source = payload.get("source")
    if isinstance(source, dict) and "subagent" in source:
        return True
    thread_source = payload.get("thread_source")
    return bool(thread_source) and thread_source != "user"


def _prefer_main(paths):
    """Pick the newest main-thread transcript, falling back to any match."""
    if not paths:
        return None
    main = [path for path in paths if not is_subagent_transcript(path)]
    return (main or paths)[-1]


def _collect_usage_records(path):
    """Read every ``token_usage_record`` as (timestamp, turn_id, usage, model)."""
    records = []
    if not path:
        return records
    try:
        handle = open(path, encoding="utf-8")
    except Exception as exc:
        log("cannot read transcript %s: %s" % (path, exc))
        return records

    with handle:
        for line in handle:
            line = line.strip()
            if not line or "token_usage_record" not in line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            if record.get("type") != "token_usage_record":
                continue
            payload = record.get("payload") or {}
            usage = payload.get("usage") or {}
            if not isinstance(usage, dict):
                continue
            records.append(
                (record.get("timestamp"), payload.get("turn_id"), usage, payload.get("model"))
            )
    return records


def _aggregate_records(records, scope: str, transcript, turn_id=None) -> dict:
    prices = load_prices()
    result = {
        "scope": scope,
        "turn_id": None,
        "turn_count": 0,
        "calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0,
        "model": "",
        "peak_calls": 0,
        "started_at": None,
        "ended_at": None,
        "transcript": str(transcript) if transcript else None,
    }

    turns = []
    for _timestamp, turn_id, _usage, _model in records:
        if turn_id and (not turns or turns[-1] != turn_id):
            turns.append(turn_id)
    result["turn_count"] = len(turns)

    if scope == "turn":
        target = turn_id or (turns[-1] if turns else None)
        result["turn_id"] = target
        records = [item for item in records if target and item[1] == target]

    for timestamp, _turn_id, usage, model in records:
        moment = _parse_timestamp(timestamp)
        resolved = model or result["model"]
        result["calls"] += 1
        result["input_tokens"] += int(usage.get("input_tokens") or 0)
        result["cached_input_tokens"] += int(usage.get("cached_input_tokens") or 0)
        result["output_tokens"] += int(usage.get("output_tokens") or 0)
        result["reasoning_output_tokens"] += int(usage.get("reasoning_output_tokens") or 0)
        result["total_tokens"] += int(usage.get("total_tokens") or 0)
        result["cost"] += price_usage(usage, moment, resolved, prices)
        if is_peak(moment):
            result["peak_calls"] += 1
        if result["started_at"] is None:
            result["started_at"] = timestamp
        result["ended_at"] = timestamp
        if model:
            result["model"] = model

    if not result["model"]:
        result["model"] = read_config_value("model") or "deepseek-flash"
    result["currency"] = prices.get("currency", "CNY")
    return result


def summarize_transcript(path, scope: str = "session", turn_id=None) -> dict:
    """Summarise usage. ``scope='turn'`` keeps only the most recent turn.

    A turn is one request/answer pair — what a single run of the agent consumed.
    Pass ``turn_id`` to pin the summary to one specific turn (the Stop hook does
    this so the numbers always describe the run that just finished).
    ``scope='session'`` covers the whole conversation transcript.
    """
    return _aggregate_records(_collect_usage_records(path), scope, path, turn_id)


def summarize_session_and_turn(path):
    """Both scopes from a single read of the transcript."""
    records = _collect_usage_records(path)
    return _aggregate_records(records, "session", path), _aggregate_records(records, "turn", path)


def fetch_balance(ttl: int = DEFAULT_CACHE_TTL, timeout: float = 8.0, force: bool = False) -> dict:
    """Return ``{"ok": bool, ...}`` with cached-first balance data."""
    cache = _read_json(CACHE_FILE)
    if (
        not force
        and isinstance(cache, dict)
        and cache.get("ok")
        and (_now() - float(cache.get("fetched_at") or 0)) < max(0, ttl)
    ):
        cache["cached"] = True
        return cache

    key = find_api_key()
    if not key:
        result = {"ok": False, "error": "no DeepSeek API key found"}
        _write_json(CACHE_FILE, dict(result, fetched_at=_now()))
        return result

    request = urllib.request.Request(
        BALANCE_URL,
        headers={"Authorization": "Bearer %s" % key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        infos = payload.get("balance_infos") or []
        first = infos[0] if infos else {}
        result = {
            "ok": True,
            "is_available": bool(payload.get("is_available", True)),
            "currency": first.get("currency"),
            "total_balance": first.get("total_balance"),
            "granted_balance": first.get("granted_balance"),
            "topped_up_balance": first.get("topped_up_balance"),
            "fetched_at": _now(),
            "cached": False,
        }
    except urllib.error.HTTPError as exc:
        result = {"ok": False, "error": "HTTP %s" % exc.code, "fetched_at": _now()}
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "fetched_at": _now()}

    if result.get("ok"):
        _write_json(CACHE_FILE, result)
    else:
        log("balance fetch failed: %s" % result.get("error"))
        if isinstance(cache, dict) and cache.get("ok"):
            stale = dict(cache)
            stale["cached"] = True
            stale["stale"] = True
            return stale
    return result


def _symbol(currency: str) -> str:
    text = (currency or "").upper()
    if text in ("CNY", "RMB"):
        return "¥"
    if text == "USD":
        return "$"
    return ""


def _short_number(value: int) -> str:
    if value >= 1_000_000:
        return "%.1fM" % (value / 1_000_000.0)
    if value >= 1_000:
        return "%.1fk" % (value / 1_000.0)
    return str(value)


def balance_text(balance: dict) -> str:
    if not balance or not balance.get("ok"):
        reason = (balance or {}).get("error") or "unavailable"
        return "余额不可用(%s)" % reason
    symbol = _symbol(balance.get("currency"))
    return "余额 %s%s" % (symbol, balance.get("total_balance"))


def spend_text(summary: dict) -> str:
    symbol = _symbol(summary.get("currency"))
    return "本次花费 %s%.4f" % (symbol, summary.get("cost") or 0.0)


def one_line(summary: dict, balance: dict) -> str:
    """Compact single line shown in the Codex UI after each turn."""
    label = "本轮" if summary.get("scope") == "turn" else "会话累计"
    symbol = _symbol(summary.get("currency"))
    parts = [
        "DeepSeek · %s %s tokens（入 %s / 出 %s，缓存命中 %s）"
        % (
            label,
            _short_number(int(summary.get("total_tokens") or 0)),
            _short_number(int(summary.get("input_tokens") or 0)),
            _short_number(int(summary.get("output_tokens") or 0)),
            _short_number(int(summary.get("cached_input_tokens") or 0)),
        ),
        "花费 %s%.4f" % (symbol, summary.get("cost") or 0.0),
        balance_text(balance),
    ]
    line = " ｜ ".join(parts)
    if balance and balance.get("stale"):
        line += " · 余额为缓存值"
    return line


def detail_text(summary: dict, balance: dict) -> str:
    scope_label = "本轮（一次运算）" if summary.get("scope") == "turn" else "整个会话"
    lines = [
        "DeepSeek 用量 · %s" % scope_label,
        "- 模型：%s" % (summary.get("model") or "unknown"),
        "- 模型调用：%d 次" % int(summary.get("calls") or 0),
        "- 输入 tokens：%s（其中缓存命中 %s）"
        % (
            _short_number(int(summary.get("input_tokens") or 0)),
            _short_number(int(summary.get("cached_input_tokens") or 0)),
        ),
        "- 输出 tokens：%s（其中推理 %s）"
        % (
            _short_number(int(summary.get("output_tokens") or 0)),
            _short_number(int(summary.get("reasoning_output_tokens") or 0)),
        ),
        "- 总 tokens：%s" % _short_number(int(summary.get("total_tokens") or 0)),
        "- 按官方价估算花费：%s%.4f"
        % (_symbol(summary.get("currency")), summary.get("cost") or 0.0),
        "- 账户%s" % balance_text(balance).replace("余额 ", "余额："),
    ]
    if summary.get("peak_calls") is not None:
        lines.append("- 高峰期调用：%d 次" % int(summary.get("peak_calls") or 0))
    lines.append("- 价目表：%s" % price_source()["label"])
    if summary.get("transcript"):
        lines.append("- 会话记录：%s" % Path(summary["transcript"]).name)
    return "\n".join(lines)
