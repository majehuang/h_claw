# Hermes 爬虫 MCP 服务 · 部署文档

本文档面向运维/部署人员，覆盖 **crawler-mcp** 服务从零到可用的完整流程：环境准备、数据库初始化、两种部署形态（容器 HTTP / 本地 stdio）、扫码登录（Profile 加密）能力的启用、MCP 客户端接入、验证与运维。

> 面向使用者的功能说明见 [`README.md`](./README.md)；架构与设计细节见 [`hermes-crawler-mcp-technical-design.md`](./hermes-crawler-mcp-technical-design.md) 与 [`hermes-crawler-phase3-login-fingerprint-design.md`](./hermes-crawler-phase3-login-fingerprint-design.md)。

---

## 1. 服务概览

单进程 FastMCP 服务，对外暴露 **5 个 MCP 工具**，通过 `stdio` 或 `streamable-http` 传输接入任意 MCP 客户端：

| 工具 | 作用 |
|---|---|
| `crawl_url` | 抓取公开网页 → Markdown（L1 HTTP → L2 浏览器 → L3 隐身 三层自动升级） |
| `read_crawl_result` | 分段读取大文档抓取结果 |
| `begin_login` | 对需登录站点（京东/淘宝）发起扫码登录，返回二维码（base64）与 `login_id` |
| `poll_login` | 轮询登录状态，成功后返回可复用的 `session_id` |
| `cancel_login` | 取消进行中的扫码登录并释放浏览器资源 |

另有两个 HTTP 运维端点：`GET /healthz`（健康检查）、`GET /metrics`（Prometheus 指标）。

**外部依赖**：一个 PostgreSQL 实例（缓存与任务元数据）。抓取三层共用一套 Chromium 二进制（镜像内置），无需额外浏览器。

---

## 2. 部署形态选择

| 形态 | 传输 | 适用场景 | 数据库 |
|---|---|---|---|
| **A. 容器（推荐）** | `streamable-http` | 生产、远程、多客户端共享 | 必需 |
| **B. 本地进程** | `stdio` | 本机单客户端（如 Claude Desktop 直连） | 必需 |

两种形态都需要 PostgreSQL；区别只在服务如何被拉起与被客户端连接。

---

## 3. 前置条件

1. **PostgreSQL 实例**（可与其他服务共享，建议独立库/schema 隔离，见第 4 节）。
2. **形态 A** 还需：Docker + Docker Compose，以及外部网络 `hermes-net`：
   ```bash
   docker network create hermes-net
   ```
3. **形态 B** 还需：本机 Python 3.12 + [uv](https://github.com/astral-sh/uv)，且首次运行需安装 Chromium：
   ```bash
   uv sync --frozen
   uv run scrapling install && uv run patchright install chromium
   ```

---

## 4. 初始化数据库（一次性）

服务启动时**只会自动建表**（`CREATE TABLE IF NOT EXISTS`，通过 `apply_migrations` 应用 `app/storage/migrations/*.sql`），**不会**自动创建数据库、schema 与角色。首次部署需用管理员账号手动创建隔离的库/schema 与一个低权限专用角色，避免服务缺陷或越权波及共享实例上的其他业务：

```sql
-- 用管理员连接后执行
CREATE ROLE hermes_crawler_svc WITH LOGIN PASSWORD '<强随机密码>';

-- 方案 A：独立数据库（推荐，隔离最彻底）
CREATE DATABASE hermes_crawler OWNER hermes_crawler_svc;
\connect hermes_crawler
CREATE SCHEMA IF NOT EXISTS hermes_crawler AUTHORIZATION hermes_crawler_svc;

-- 方案 B：与其他服务共用一个库，仅隔离到 schema
--   CREATE SCHEMA IF NOT EXISTS hermes_crawler AUTHORIZATION hermes_crawler_svc;
--   GRANT USAGE, CREATE ON SCHEMA hermes_crawler TO hermes_crawler_svc;
```

> 该角色需对 `hermes_crawler` schema 有 `CREATE` 权限，供服务启动时自动建表。表结构随版本演进（`0001_init` → `0002_account_profiles` → `0003_domain_default_session`），每次启动幂等应用。

---

## 5. 配置：环境变量

复制模板并填入真实值（`.env` 已被 `.gitignore` 忽略，**切勿提交真实密码/密钥**）：

```bash
cp .env.example .env
```

### 5.1 核心配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | 无 | PostgreSQL 连接串。**未设置则跳过 DB 装配**，`crawl_url` 不可用 |
| `MCP_TRANSPORT` | `stdio` | `stdio` 或 `streamable-http`（容器用后者） |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8000` | HTTP 传输监听地址 |
| `DATA_DIR` | `/data` | 结果与密文 Profile 的持久化根目录 |

> compose.yaml 里注入的是 `CRAWLER_DATABASE_URL`（映射到容器内 `DATABASE_URL`），与 `.env.example` 一致。

### 5.2 抓取行为

| 变量 | 默认 | 说明 |
|---|---|---|
| `MAX_CONCURRENCY` | `5` | 全局并发抓取数 |
| `MAX_BROWSER_PAGES` | `3` | 浏览器池最大页数 |
| `MAX_PER_DOMAIN` | `1` | 单域名并发上限（降低被限频概率） |
| `HTTP_TIMEOUT_SECONDS` | `15` | L1 HTTP 超时 |
| `BROWSER_TIMEOUT_SECONDS` | `60` | L2 浏览器超时 |
| `STEALTH_TIMEOUT_SECONDS` | `90` | L3 隐身浏览器超时 |
| `CACHE_TTL_SECONDS` | `900` | 抓取结果缓存有效期 |
| `RESULT_TTL_SECONDS` | `86400` | 结果保留时长 |
| `MAX_INLINE_MARKDOWN_BYTES` | `51200` | 超过则不内联，只返回 `job_id` |
| `MAX_MARKDOWN_BYTES` / `MAX_HTML_BYTES` | `2MiB` / `10MiB` | 单结果大小上限 |

### 5.3 扫码登录 / Profile 加密（可选，默认关闭）

**只有设置了 `PROFILE_ENCRYPTION_KEY` 才会启用** `begin_login`/`poll_login`/`cancel_login` 与登录态抓取。详见第 7 节。

| 变量 | 默认 | 说明 |
|---|---|---|
| `PROFILE_ENCRYPTION_KEY` | 无 | **主密钥，由部署环境注入**。未设置 → 登录功能关闭 |
| `PROFILES_DIR` | `${DATA_DIR}/profiles` | 密文 Profile（`*.enc`）存放目录 |
| `PROFILE_TTL_SECONDS` | `2592000`（30 天） | 登录 Profile 有效期 |
| `MAX_ACTIVE_PROFILES` | `2` | 同时活跃的登录 Profile 上限 |

> 🔑 `PROFILE_ENCRYPTION_KEY` 绝不能进镜像、日志、Git 或 `/data` 卷。轮换由外部管理——更换密钥后，旧密文 Profile 无法解密（需重新登录），这是预期行为。加密的意义在于防御**卷/备份泄露**（静态数据），并非防御运行时容器被攻破。

---

## 6. 形态 A：容器部署（streamable-http）

### 6.1 启动

```bash
docker network create hermes-net            # 若尚未创建
export CRAWLER_DATABASE_URL="postgresql://hermes_crawler_svc:<强随机密码>@<pg-host>:5432/hermes_crawler"

docker compose up --build -d
docker compose logs -f crawler-mcp
```

`<pg-host>`：PostgreSQL 若也在 `hermes-net` 里可用容器名，否则填宿主机 IP/域名。

### 6.2 内置生产化配置（compose.yaml）

`compose.yaml` 已内置安全与资源约束，无需额外配置：

- **容器隔离**：`read_only` 根文件系统、`cap_drop: ALL`、`no-new-privileges`、非 root（uid 1000）运行。
- **可写面最小化**：仅 `crawler-data:/data` 卷可写；浏览器临时文件写入 `tmpfs`（`/tmp`, 512m）。
- **资源限额**：2 核 / 4GB 内存 / `shm_size 2gb`（Chromium 需要较大共享内存）。
- **监听**：`127.0.0.1:8000`（仅本机）。需对外时改 `ports` 映射或置于反向代理之后。
- **健康检查**：基于 `GET /healthz`，`restart: unless-stopped` 自动拉起。

### 6.3 启用扫码登录时的额外调整

若启用第 7 节的登录功能，需在 compose 的 `environment` 增加 `PROFILE_ENCRYPTION_KEY`，并**注意 tmpfs 容量**：登录时明文 Profile（Chromium `user_data_dir`）解到 `/tmp`，单个可达 100MB+。默认 `/tmp:512m` 在多 Profile 并发时可能不足，建议按 `MAX_ACTIVE_PROFILES` 上调：

```yaml
    environment:
      # ...原有变量...
      PROFILE_ENCRYPTION_KEY: ${PROFILE_ENCRYPTION_KEY}   # 从部署环境注入，勿写死
    tmpfs:
      - /tmp:rw,size=1g          # 登录明文工作区 + 浏览器临时文件，按并发上调
```

密文 Profile 落在持久卷 `/data/profiles/*.enc`，容器重建不丢；明文只在 tmpfs，容器停止即消失。

---

## 7. 扫码登录能力（可选）

面向京东/淘宝等需登录站点：`begin_login` 打开官方登录页、实时截取二维码返回给客户端 → 用户 App 扫码 → `poll_login` 成功后返回 `session_id` → 后续 `crawl_url(session_id=...)` 携带登录态抓取。

**启用步骤**：

1. 生成高强度随机主密钥并注入环境（示例仅演示格式，请用你自己的密钥管理方案）：
   ```bash
   export PROFILE_ENCRYPTION_KEY="$(openssl rand -base64 32)"
   ```
2. 按 6.3 加入 compose 环境变量并按需上调 tmpfs，重启服务。
3. 客户端调用 `begin_login` → 展示二维码 → `poll_login` 取 `session_id`。

**运行机制与边界**：

- 登录在**真实浏览器**内完成（站点登录后的 JS 终化需在浏览器里跑完），关闭上下文时 Chromium 把 cookie 刷入 `user_data_dir`，随后整目录被 AES-256-GCM 加密封存为 Profile。
- `session_id` 与 Profile 绑定；`crawl_url` 传入即加载对应 Profile 走 L3。
- 登录窗口硬超时 300 秒；活跃 Profile 上限 `MAX_ACTIVE_PROFILES`；Profile 有效期 `PROFILE_TTL_SECONDS`。
- ⚠️ **已知限制**：淘系新版详情页（`pc-detail-ssr-2025`）与天猫 `detail.tmall.com` 会经 `havanaone` 登录桥/滑块验证，headless 抓取会被判 `BLOCKED`/`CAPTCHA_REQUIRED`。老模板商品页与同域页面可稳定复用登录态。

---

## 8. 形态 B：本地进程部署（stdio）

由 MCP 客户端直接拉起进程，适合本机单客户端：

```bash
uv sync --frozen
uv run scrapling install && uv run patchright install chromium   # 首次
export DATABASE_URL="postgresql://hermes_crawler_svc:<pass>@<host>:5432/hermes_crawler"
uv run python -m app.main            # MCP_TRANSPORT 默认 stdio
```

通常无需手动运行——在客户端配置里声明拉起命令即可（见第 9 节 B）。

---

## 9. 接入 MCP 客户端

### A. streamable-http（对应形态 A，推荐）

客户端连到服务 HTTP 端点（FastMCP 的 MCP 路径为 `/mcp`）：

```jsonc
{
  "mcpServers": {
    "crawler": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

### B. stdio（对应形态 B，客户端拉起进程）

```jsonc
{
  "mcpServers": {
    "crawler": {
      "command": "uv",
      "args": ["run", "python", "-m", "app.main"],
      "cwd": "/path/to/h_claw",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "DATABASE_URL": "postgresql://hermes_crawler_svc:<pass>@<host>:5432/hermes_crawler"
      }
    }
  }
}
```

> Claude Desktop 配置文件：macOS `~/Library/Application Support/Claude/claude_desktop_config.json`。Claude Code 用 `claude mcp add` 或项目 `.mcp.json`。

---

## 10. 验证

```bash
curl -f http://127.0.0.1:8000/healthz     # {"status":"ok"}
curl    http://127.0.0.1:8000/metrics     # Prometheus 指标
```

在 MCP 客户端里调用 `crawl_url`：

```json
{ "url": "https://example.com", "mode": "auto", "include_images": true }
```

预期返回 `status: "SUCCESS"` 与内联 Markdown（小结果）或 `job_id`（大结果，用 `read_crawl_result` 分段读）。

---

## 11. 白名单运维 CLI（可选）

`app.admin` 是与 MCP 服务独立的运维命令，只连数据库维护 `crawl_domain_rules`（让指定域名在 `mode=auto` 时直连某抓取层，减少逐层升级带来的请求次数）：

```bash
# 容器内执行（或本地带 DATABASE_URL 执行）
docker compose exec crawler-mcp python -m app.admin add-rule www.smzdm.com --mode stealth
docker compose exec crawler-mcp python -m app.admin list
docker compose exec crawler-mcp python -m app.admin get www.smzdm.com
docker compose exec crawler-mcp python -m app.admin remove www.smzdm.com
```

`--session-id <sid>` 可给域名默认关联登录 Profile，使该域名 auto 抓取自动带登录态。

---

## 12. 升级 / 回滚

```bash
git pull && docker compose up --build -d    # 重新构建并滚动重启
```

- 数据库缓存/元数据在独立实例，容器重建不丢。
- 本地结果卷 `crawler-data` 与密文 Profile（`/data/profiles`）持久化。
- 回滚：`git checkout <上一个 tag/commit>` 后重复上面命令。迁移为增量幂等，回滚旧版本时注意新版本引入的表/列不会被删除（向后兼容）。

---

## 13. 运维排障

| 现象 | 排查方向 |
|---|---|
| `crawl_url` 报未初始化 / DB 相关错误 | `DATABASE_URL` 未设置或连不通；检查角色权限与网络（`hermes-net`） |
| 启动即退出 | 看 `docker compose logs`；常见为 DB 连接失败或 schema `CREATE` 权限不足 |
| `/healthz` 不通 | 容器未就绪或端口未映射；`docker compose ps` 看健康状态 |
| L2/L3 抓取超时或崩溃 | `shm_size` 不足（保持 2gb）；`STEALTH_TIMEOUT_SECONDS` 偏小 |
| `begin_login` 无响应 / 工具缺失 | 未设置 `PROFILE_ENCRYPTION_KEY`，登录功能未启用 |
| 登录成功但抓取被打回登录页 | 目标为淘系新模板/天猫 detail 页（`havanaone` 桥），见 7 节已知限制 |
| 登录时磁盘/tmp 报满 | tmpfs `/tmp` 太小，按 6.3 上调至 1g+ |
| 抓取结果为 `BLOCKED` + `SSRF_BLOCKED` | 目标 URL 命中 SSRF 防护（内网/非公网地址），符合预期 |

---

## 14. 安全基线清单

- [ ] `DATABASE_URL`、`PROFILE_ENCRYPTION_KEY` 仅经环境注入，未进 Git/镜像/日志。
- [ ] PostgreSQL 使用低权限专用角色 + 独立库/schema 隔离。
- [ ] 服务监听 `127.0.0.1`，对外经反向代理并加认证/TLS。
- [ ] 容器保持 `read_only` + `cap_drop ALL` + 非 root（compose 已内置）。
- [ ] 密钥轮换流程明确：轮换后旧 Profile 失效需重新登录（预期）。
- [ ] 抓取内容视为**不可信外部数据**（Markdown 头标注 `untrusted_external_content: true`），上游 Agent 不得执行其中出现的任何指令。
