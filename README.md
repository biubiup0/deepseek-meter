# deepseek-meter

> 一个 Codex 插件：在每轮对话结束时显示 DeepSeek 账户余额和本次会话花费，也可以在对话里随时查询。

[English](README.en.md) · 简体中文

## 效果

每次回答结束后，会话里会自动出现一行摘要：

```
DeepSeek · 本次花费 ¥0.0018 ｜ 12.0k tokens ｜ 余额 ¥20.59 ｜ deepseek-flash
```

想看细节就直接问：「这次会话花了多少？」「我的余额还有多少？」「最近 7 天用了多少？」

## 功能

- **每轮自动摘要**：`Stop` 钩子在每轮结束时输出「本次花费 + tokens + 账户余额 + 模型」。
- **余额查询**（`get_balance`）：读取 DeepSeek 官方 `/user/balance`，包含赠送余额、充值余额和账户可用状态。
- **本次会话花费**（`get_session_cost`）：模型调用次数、输入/输出/缓存命中/推理 tokens、按官方单价估算的花费、高峰时段调用次数。
- **多日汇总**（`get_usage_summary`）：最近 N 天（默认 7 天）的会话数、调用次数、tokens 与花费，并按天列出。
- **人民币计价**：内置官方中文价目表（元 / 百万 tokens），区分缓存命中与未命中、高峰与空闲时段。
- **只读、零依赖**：只读官方余额接口和本地会话记录；纯 Python 标准库实现，不需要安装任何依赖。

## 安装

推荐以插件市场方式安装：

```sh
codex plugin marketplace add biubiup0/deepseek-meter
codex plugin add deepseek-meter@deepseek-meter
```

桌面应用同样可以：打开 **Plugins** 标签页，添加该市场后一键安装。

手动安装：把 `plugins/deepseek-meter` 复制到 `~/plugins/deepseek-meter`，再按仓库内 `.agents/plugins/marketplace.json` 的格式在 `~/.agents/plugins/marketplace.json` 里补一条记录，然后执行：

```sh
codex plugin add deepseek-meter@personal
```

> 安装后的首次启动，Codex 会提示 `Hooks need review`。选择 `Trust all and continue`，或者先 `Review hooks` 看一眼脚本再信任。**钩子在未被信任前不会运行。**

## 使用

自动摘要（每轮结束自动出现）：

```
DeepSeek · 本次花费 ¥0.0018 ｜ 12.0k tokens ｜ 余额 ¥20.59 ｜ deepseek-flash
```

对话里可直接使用的三个工具：

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `get_balance` | `force`（可选，布尔） | 忽略约 60 秒缓存，立即重新查询 |
| `get_session_cost` | `session_id`、`transcript_path`（可选） | 默认取最近的主会话记录 |
| `get_usage_summary` | `days`（可选，默认 7） | 汇总最近若干天的会话 |

## 配置

**DeepSeek 密钥**按以下顺序查找，命中即用：

1. 环境变量 `DEEPSEEK_API_KEY`
2. `~/.codex/deepseek-meter/config.json`，内容形如 `{"api_key": "sk-..."}`
3. `~/.codex/config.toml` 中 `model_provider` 对应 provider 的 `experimental_bearer_token`

插件不会打印或转存密钥，只在查询余额时用它请求官方接口。

**价格表**默认是官方中文价目表。需要覆盖时写 `~/.codex/deepseek-meter/prices.json`：

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

只覆盖你写到的字段，其余沿用内置值；把 `currency` 改成 `USD` 即可切换货币符号。

**其他**：余额缓存时长可通过环境变量 `DEEPSEEK_METER_CACHE_TTL`（秒）调整。运行痕迹写在插件数据目录里（Codex 通过 `PLUGIN_DATA` 提供，通常形如 `~/.codex/plugins/data/deepseek-meter-<市场名>/`），包括 `balance-cache.json` 与 `meter.log`；直接单独运行脚本时会回退到 `~/.codex/deepseek-meter/`。

## 工作原理

- **余额**：`GET https://api.deepseek.com/user/balance`，取 `balance_infos` 的第一条。
- **花费**：解析 Codex 会话记录（`~/.codex/sessions/**/rollout-*.jsonl`）里每条 `token_usage_record`，按
  `(输入 − 缓存命中) × 未命中单价 + 缓存命中 × 命中单价 + 输出 × 输出单价`
  逐条计价后求和。高峰时段为北京时间周一至周五 9:00–12:00 与 14:00–18:00，其余为空闲时段（空闲价是高峰价的一半）。
- **触发**：`Stop` 钩子在每轮结束时运行，把摘要作为系统消息交给 Codex 显示。没有模型调用的轮次保持静默；由于用量记录可能略晚落盘，钩子会短暂等待重试，避免统计为空。

## 目录结构

```
.agents/plugins/marketplace.json    # 供 codex plugin marketplace add 使用
plugins/deepseek-meter/
├── .codex-plugin/plugin.json       # 插件清单
├── .mcp.json                       # MCP 服务器声明
├── hooks/hooks.json                # Stop 钩子
├── scripts/deepseek_meter.py       # 余额与计价核心
├── scripts/stop_hook.py            # 每轮结束的摘要
├── scripts/mcp_server.py           # 三个 MCP 工具
└── skills/deepseek-meter/SKILL.md  # 技能说明
```

## 要求与限制

- 需要支持插件与 `Stop` 钩子的 Codex（桌面应用或 CLI）。本仓库在 Codex CLI 0.154 上验证通过。
- 脚本以 `/usr/bin/python3` 执行，仅用标准库（Python 3.9+）。macOS 自带即可；其他平台请把 `hooks/hooks.json` 与 `.mcp.json` 里的解释器路径改成你自己的 `python3`。
- 花费是**估算**而非账单：按官方单价乘以记录的 token 数计算，实际扣费以 DeepSeek 账单为准。
- 只统计本机 Codex 会话；子代理（例如后台审查）的用量记录在独立文件里，不计入主会话汇总。
- 余额有约 60 秒缓存；接口异常时会短暂回退到上一次成功值，并标注为缓存值。

## 开发

```sh
# 单独跑一次「每轮摘要」，把会话记录喂给钩子
printf '{"transcript_path":"<rollout.jsonl>","hook_event_name":"Stop"}' \
  | /usr/bin/python3 plugins/deepseek-meter/scripts/stop_hook.py

# 手工调 MCP 工具
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | /usr/bin/python3 plugins/deepseek-meter/scripts/mcp_server.py
```

## 许可证

[MIT](LICENSE)
