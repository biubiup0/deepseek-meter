# deepseek-meter

> 一个 Codex 插件：在每轮对话结束时显示 DeepSeek 账户余额和本次会话花费，也可以在对话里随时查询。

[English](README.en.md) · 简体中文

## 效果

每次回答结束后，会话里会自动出现一行摘要：

```
DeepSeek · 本轮 12.4k tokens（入 11.9k / 出 0.5k，缓存命中 11.2k）｜ 花费 ¥0.0021 ｜ 余额 ¥20.59
```

token 数字是**这一轮**（一次请求/回答）的消耗，方便你知道每次运算花了多少。正文这一行和钩子摘要都可以单独开关，见下文「显示开关」。

想看细节就直接问：「这次会话花了多少？」「我的余额还有多少？」「最近 7 天用了多少？」

## 功能

- **每轮自动摘要**：`Stop` 钩子在每轮结束时输出「本次花费 + tokens + 账户余额 + 模型」。
- **本轮 token 明细**：摘要显示的是这一次运算的输入 / 输出 / 缓存命中 tokens，而不是整个会话的累计值；钩子会绑定本轮 turn id，即使用量记录稍晚落盘也不会串到上一轮。
- **显示开关**：正文末尾那一行、以及每轮钩子摘要，可以分别开关；设置写在 `~/.codex/deepseek-meter/settings.json`，用 `configure` 工具或直接改文件都行。
- **余额查询**（`get_balance`）：读取 DeepSeek 官方 `/user/balance`，包含赠送余额、充值余额和账户可用状态。
- **本次会话花费**（`get_session_cost`）：模型调用次数、输入/输出/缓存命中/推理 tokens、按官方单价估算的花费、高峰时段调用次数。
- **多日汇总**（`get_usage_summary`）：最近 N 天（默认 7 天）的会话数、调用次数、tokens 与花费，并按天列出。
- **价目表每天自动更新**：最多每 24 小时从官方中文价格页拉取一次最新单价，校验（高峰价须为空闲价两倍、且命中 < 未命中 < 输出）通过后才启用；拉取或解析失败时沿用上一次的表或内置默认值，不会因为网络问题报错。
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
DeepSeek · 本轮 12.4k tokens（入 11.9k / 出 0.5k，缓存命中 11.2k）｜ 花费 ¥0.0021 ｜ 余额 ¥20.59
```

**显示时机**：摘要由 `Stop` 钩子产生，只在 Codex 把这一轮内容输出完毕、本轮结束时出现，位置在回答之后；不会插进回答中间，也不会提前显示。钩子不设置进行中提示，也不会让 Codex 继续生成内容。

对话里可直接使用的三个工具：

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `get_balance` | `force`（可选，布尔） | 忽略约 60 秒缓存，立即重新查询 |
| `get_session_cost` | `session_id`、`transcript_path`（可选） | 同时给出「本轮」和「整个会话」两份明细 |
| `get_usage_summary` | `days`（可选，默认 7） | 汇总最近若干天的会话 |
| `refresh_prices` | 无 | 立刻拉取官方价目表并回显当前单价 |
| `get_status_line` | 无 | 返回回复末尾该带的那一行；正文显示关闭时返回空字符串 |
| `configure` | `show_in_reply`、`show_in_hook`（布尔，可选） | 读取或修改下面两个开关 |

## 配置

**DeepSeek 密钥**按以下顺序查找，命中即用：

1. 环境变量 `DEEPSEEK_API_KEY`
2. `~/.codex/deepseek-meter/config.json`，内容形如 `{"api_key": "sk-..."}`
3. `~/.codex/config.toml` 中 `model_provider` 对应 provider 的 `experimental_bearer_token`

插件不会打印或转存密钥，只在查询余额时用它请求官方接口。

**显示开关**写在 `~/.codex/deepseek-meter/settings.json`：

```json
{
  "show_in_reply": true,
  "show_in_hook": true
}
```

- `show_in_reply`：控制回复末尾那一行（由 `get_status_line` 读取，返回空则不加）。
- `show_in_hook`：控制 `Stop` 钩子每轮结束后的摘要，关掉后钩子直接静默退出。

改法有两种：直接编辑这个文件，或者让 Codex 调用 `configure` 工具（例如「把正文显示关掉、钩子保留」）。改完立即生效，不需要重装插件。

**价格表**默认是官方中文价目表，并且每天自动更新一次（结果缓存在插件数据目录的 `prices-cache.json`）。需要手动覆盖时写 `~/.codex/deepseek-meter/prices.json`，它的优先级高于在线价目表：

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
- **价目表**：最多每 24 小时抓取一次官方中文价格页并解析缓存；解析结果必须通过「高峰 = 空闲 × 2」和「命中 < 未命中 < 输出」的校验才会生效。
- **花费**：解析 Codex 会话记录（`~/.codex/sessions/**/rollout-*.jsonl`）里每条 `token_usage_record`，按
  `(输入 − 缓存命中) × 未命中单价 + 缓存命中 × 命中单价 + 输出 × 输出单价`
  逐条计价后求和。高峰时段为北京时间周一至周五 9:00–12:00 与 14:00–18:00，其余为空闲时段（空闲价是高峰价的一半）。
- **触发**：`Stop` 钩子在每轮结束时运行——也就是 Codex 把内容输出完毕、本轮停止之后——把摘要作为系统消息交给 Codex 显示，所以它总是出现在回答之后。没有模型调用的轮次保持静默；由于用量记录可能略晚落盘，钩子会短暂等待重试，避免统计为空。

## 更新日志

### v0.5.0

- 去掉充值链接：摘要、`get_balance`、`get_session_cost` 都不再附带 `platform.deepseek.com/top_up`
- 新增两个显示开关 `show_in_reply` / `show_in_hook`（`~/.codex/deepseek-meter/settings.json`）
- 新增 `get_status_line` 与 `configure` 工具：正文那一行改由工具按开关返回，关闭时不输出

### v0.4.0

- MCP 工具标记为只读（`readOnlyHint`），并在 `.mcp.json` 设 `default_tools_approval_mode = "writes"`，余额与用量查询不再需要逐次审批
- 配合用户级 `~/.codex/AGENTS.md` 的规则，可以把摘要作为**回复的最后一行**输出，不必依赖钩子在界面里的呈现位置

### v0.3.0

- 摘要改为显示**本轮**（一次运算）的 tokens：输入 / 输出 / 缓存命中，绑定 turn id，不会串到上一轮
- 余额后面新增**充值**条目，直达官方充值页 `https://platform.deepseek.com/top_up`
- `get_session_cost` 同时返回「本轮」和「整个会话」两份明细

### v0.2.0

- 价目表改为**每天自动更新**：每 24 小时从官方价格页拉取并校验一次，失败自动沿用旧表
- 新增 `refresh_prices` 工具，可随时手动刷新并回显当前单价
- `get_session_cost` 会标明当前使用的价目表来源与更新时间
- 调整显示时机：移除进行中提示，摘要只在 Codex 输出完毕、本轮结束后显示

### v0.1.0

- 首个版本：`Stop` 钩子显示「花费 + tokens + 余额 + 模型」，并提供 `get_balance`、`get_session_cost`、`get_usage_summary`

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
