# Agent 接入技能（Skills）

本目录提供随 MCP 一起分发的 **Agent 技能**，用于教会上游 Agent（Hermes / Claude Code 等）
**如何正确使用本爬虫 MCP 的工具**，避免两类常见误用：

- Agent 不知道有 MCP 工具，遇到抓取需求自己去写 Python（`requests`/`playwright`/`scrapling`）脚本；
- Agent 遇到登录墙时尝试"绕过"，而不是走 `begin_login` 扫码登录。

## crawler-mcp

`crawler-mcp/SKILL.md` —— 定义 5 个 MCP 工具（`crawl_url` / `read_crawl_result` /
`begin_login` / `poll_login` / `cancel_login`）的用途、返回结构、决策流程与铁律：
**直接调用 MCP 工具，绝不自己写代码抓取或登录；绝不绕过登录墙或验证码。**

### 安装

把技能目录拷贝到 Agent 运行时的技能目录即可被自动加载：

```bash
# Claude Code（项目级或用户级）
cp -r skills/crawler-mcp .claude/skills/crawler-mcp
# 或用户级：~/.claude/skills/crawler-mcp

# Hermes / 其他 Agent 运行时：拷到其对应的 skills 目录
```

技能通过 `SKILL.md` 的 frontmatter `description` 中的触发词（抓取网页 / 商品页 /
京东 / 淘宝 / 登录墙 / 扫码登录 …）被相关任务自动激活，无需手动调用。

> 技能只描述"如何使用工具"，不改变 MCP 行为；确保 Agent 已连接本 MCP（见根目录
> `README.md` 的"接入 MCP 客户端"）。
