---
name: deepseek-meter
description: Report DeepSeek account balance and estimated Codex session spend. Use when the user asks about DeepSeek balance, remaining credit, top-up status, what a session or task cost, token usage, or spend over the last days. Backed by the deepseek-meter MCP tools and a Stop hook that shows a summary after every turn.
---

# DeepSeek Meter

Two numbers matter here: the **account balance** on the DeepSeek platform, and
what the **current session** has cost. Both come from this plugin's MCP server.

## Tools

| Tool | Use it for |
| --- | --- |
| `get_balance` | "余额还有多少" / remaining credit. Pass `force: true` only when the user asks for a fresh number and the cached one looks wrong. |
| `get_session_cost` | What this conversation cost so far: token breakdown, cache hits, peak-hour calls, estimated spend. |
| `get_usage_summary` | Rollup across recent sessions, default 7 days. Pass `days` for a different window. |
| `refresh_prices` | Pull the official price table immediately instead of waiting for the daily refresh. Use when the user says prices changed or asks where the rates come from. |

Prefer calling a tool over guessing. Never invent a balance or a price.

## How to present results

- Lead with the two headline numbers, then offer detail: `余额 ¥110.00 · 本次花费 ¥0.4231`.
- Both numbers are in CNY: the balance comes from DeepSeek's balance API and the spend
  uses the official Chinese price table (yuan per 1M tokens). If a `prices.json`
  override switches `currency`, label the spend with the new symbol instead.
- Spend is an **estimate**: it multiplies recorded tokens by published per-1M-token
  prices, splitting cached and uncached input, and applying peak/off-peak rates
  (peak = 01:00-04:00 and 06:00-10:00 UTC, Monday-Friday). Say "估算" rather than
  presenting it as an invoice.
- If the balance lookup fails, report the error plainly instead of showing a stale
  number as if it were current.
- `get_session_cost` reports which price table it used; mention that line when the
  user asks whether the rates are current.

## Automatic display

The plugin also bundles a `Stop` hook (`hooks/hooks.json`). After each turn Codex
runs `scripts/stop_hook.py`, which prints a one-line summary such as
`DeepSeek · 本次花费 ¥0.0421 ｜ 268k tokens ｜ 余额 ¥110.00 ｜ deepseek-flash`.
The timing is deliberate: `Stop` fires only after the reply is complete, so the
summary is always the last thing the user sees and never appears before or in the
middle of the answer. The hook has no in-progress status line. It only reports — it
never continues the turn or blocks anything — and stays silent for turns with no
model calls.

## Configuration

- API key resolution order: `DEEPSEEK_API_KEY` env var →
  `~/.codex/deepseek-meter/config.json` (`{"api_key": "..."}`) → the
  `[model_providers.deepseek]` entry in `~/.codex/config.toml`. The key is never
  printed or stored by this plugin.
- `~/.codex/deepseek-meter/prices.json` overrides the built-in price table. Copy the
  shape from `scripts/deepseek_meter.py` (`DEFAULT_PRICES`) and change `currency`
  plus the `models` entries when prices change.
- The price table refreshes itself: at most once every 24 hours the plugin fetches the
  official Chinese pricing page, validates it (peak must be twice off-peak, cache-hit
  < cache-miss < output) and caches it in `prices-cache.json`. A failed fetch or parse
  keeps the previous table, or the built-in default, and is only logged.
- Cache and log files go to the plugin data directory Codex provides through
  `PLUGIN_DATA` (usually `~/.codex/plugins/data/deepseek-meter-<marketplace>/`),
  falling back to `~/.codex/deepseek-meter/` when the scripts run standalone.
