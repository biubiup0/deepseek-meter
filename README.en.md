# deepseek-meter

> A Codex plugin that shows your DeepSeek account balance and what the current session costs, both after every turn and on demand.

English · [简体中文](README.md)

## What it looks like

After each turn, a one-line summary appears in the conversation:

```
DeepSeek · 本次花费 ¥0.0018 ｜ 12.0k tokens ｜ 余额 ¥20.59 ｜ deepseek-flash
```

(The summary text is Chinese: spend, tokens, balance, model.)

## Features

- **Automatic per-turn summary** via a `Stop` hook: spend, tokens, account balance, model.
- **`get_balance`** — reads the official DeepSeek `/user/balance` endpoint, including granted and topped-up balance.
- **`get_session_cost`** — model calls, input/output/cached/reasoning tokens, estimated spend, and how many calls hit peak pricing.
- **`get_usage_summary`** — rollup over the last N days (default 7), broken down per day.
- **Daily price-table refresh** — at most once every 24 hours the plugin pulls the official Chinese pricing page, validates it (peak must be 2× off-peak, cache-hit < cache-miss < output) and caches it. A failed fetch or parse keeps the previous table or the built-in default.
- **CNY pricing by default**, using DeepSeek's official Chinese price table with separate cache-hit, cache-miss, peak, and off-peak rates.
- **Read-only and dependency-free** — standard-library Python only, no installs, and nothing leaves your machine except the balance call to DeepSeek.

## Install

```sh
codex plugin marketplace add biubiup0/deepseek-meter
codex plugin add deepseek-meter@deepseek-meter
```

You can also add the marketplace from the **Plugins** tab in the Codex desktop app.

Manual install: copy `plugins/deepseek-meter` to `~/plugins/deepseek-meter`, add an entry to `~/.agents/plugins/marketplace.json` following the shape of this repo's copy, then run `codex plugin add deepseek-meter@personal`.

> On the first launch after installing, Codex asks to review the bundled hook (`Hooks need review`). Choose `Trust all and continue`, or review it first. The hook does not run until it is trusted.

## Usage

The automatic summary (once per turn):

```
DeepSeek · 本次花费 ¥0.0018 ｜ 12.0k tokens ｜ 余额 ¥20.59 ｜ deepseek-flash
```

**Timing:** the summary comes from a `Stop` hook, so it appears only after Codex has finished writing the reply for that turn — never before or in the middle of it. The hook has no in-progress status line and never makes Codex continue generating.

The three tools available in conversation:

| Tool | Arguments | Notes |
| --- | --- | --- |
| `get_balance` | `force` (optional bool) | Bypass the ~60s cache and query now |
| `get_session_cost` | `session_id`, `transcript_path` (optional) | Defaults to the most recent main session |
| `get_usage_summary` | `days` (optional, default 7) | Rollup across recent sessions |
| `refresh_prices` | none | Pull the official price table now and echo the current rates |

## Configuration

The DeepSeek API key is resolved in this order:

1. `DEEPSEEK_API_KEY` environment variable
2. `~/.codex/deepseek-meter/config.json` → `{"api_key": "sk-..."}`
3. `experimental_bearer_token` of the provider named by `model_provider` in `~/.codex/config.toml`

The key is never printed or copied; it is only sent to the official balance endpoint.

The price table refreshes itself once a day (cached as `prices-cache.json` in the plugin data directory). Override it manually with `~/.codex/deepseek-meter/prices.json`, which wins over the online table:

```json
{
  "currency": "CNY",
  "models": {
    "deepseek-flash": {
      "cache_hit": { "peak": 0.04, "off": 0.02 },
      "cache_miss": { "peak": 2.0, "off": 1.0 },
      "output": { "peak": 8.0, "off": 4.0 }
    }
  }
}
```

Only the fields you provide are overridden; set `currency` to `USD` to change the symbol. `DEEPSEEK_METER_CACHE_TTL` (seconds) controls the balance cache. Cache and log files live in the plugin data directory Codex provides via `PLUGIN_DATA` (usually `~/.codex/plugins/data/deepseek-meter-<marketplace>/`), falling back to `~/.codex/deepseek-meter/` for standalone runs.

## How it works

- **Balance** — `GET https://api.deepseek.com/user/balance`, first entry of `balance_infos`.
- **Prices** — fetched from the official Chinese pricing page at most once every 24 hours; a parsed table is accepted only if peak is exactly twice off-peak and cache-hit < cache-miss < output.
- **Spend** — every `token_usage_record` in the Codex session transcript (`~/.codex/sessions/**/rollout-*.jsonl`) is priced as `(input − cached) × cache-miss rate + cached × cache-hit rate + output × output rate`, then summed. Peak hours are Beijing time Mon–Fri 09:00–12:00 and 14:00–18:00; off-peak rates are half of peak.
- **Trigger** — a `Stop` hook runs once the reply is complete, so the summary always lands after the answer. Turns without model calls stay silent, and the hook briefly retries so a late-written usage record is not missed.

## Changelog

### v0.2.0

- Daily automatic price-table refresh with validation and a safe fallback
- New `refresh_prices` tool for on-demand updates
- `get_session_cost` reports which price table is in use and when it was updated
- Display timing tightened: no in-progress status line, summary appears only once the reply is finished

### v0.1.0

- First release: `Stop` hook summary (spend, tokens, balance, model) plus `get_balance`, `get_session_cost`, `get_usage_summary`

## Requirements and limitations

- Requires Codex (desktop or CLI) with plugin and `Stop` hook support. Verified on Codex CLI 0.154.
- Scripts run with `/usr/bin/python3` (Python 3.9+, standard library only). On other platforms, change the interpreter path in `hooks/hooks.json` and `.mcp.json`.
- Spend is an **estimate** from published rates and recorded tokens, not an invoice.
- Only local Codex sessions are counted; subagent transcripts (for example background review) are separate files and are not merged into the main session total.
- Balance lookups are cached for about a minute and fall back to the last good value when the API misbehaves.

## License

[MIT](LICENSE)
