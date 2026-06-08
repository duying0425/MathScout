# 本地配置（Local Configuration）

MathScout 从 `.env` 读取运行时配置。

## 默认本地设置

用 `.env.example` 创建本地 `.env`：

```powershell
Copy-Item .env.example .env
```

默认本地 `.env` 应刻意保持简单：

```text
DATABASE_URL=sqlite+pysqlite:///./.data/mathscout_dev.db
AI_PROVIDER=rule
DEEPSEEK_API_KEY=
```

`.env` 被 Git 忽略，本地密钥不会被提交。

这种 SQLite 模式**不需要 Docker、不需要 PostgreSQL**，足以支持：

- 导入教材模板
- 创建爬取作业
- 单进程爬取
- 存储已抓文档、候选、方法、变体与决策
- 打开基于数据库的后台 UI

SQLite 数据库文件位于 `.data/` 下，仅本地存在。在新环境克隆后，需重新运行初始化命令：

```powershell
mathscout init-db
mathscout import-template
mathscout seed-sources
```

后台控制台与列表页使用与 CLI 相同的 `DATABASE_URL`，因此从 SQLite 切到 PostgreSQL
会同时改变两侧。

## 爬虫 User-Agent

`DEFAULT_USER_AGENT` 用作爬虫请求的 HTTP `User-Agent` 头，以及 `robots.txt` 权限检查。
它不是 API Key。

修改该值可能影响爬取行为，因为有些站点会按 user agent 过滤、限速或返回不同内容。
做真实公开爬取时，保持其具有描述性。

## DeepSeek

通过 OpenAI 兼容接口使用 DeepSeek，设置：

```text
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_deepseek_key
OPENAI_COMPATIBLE_BASE_URL=https://api.deepseek.com
OPENAI_COMPATIBLE_MODEL=deepseek-chat
```

若 `AI_PROVIDER=rule`，爬虫使用本地规则抽取器，不调用外部 AI 接口。

## 之后再上 PostgreSQL

PostgreSQL 在首个版本中是可选的。当你需要以下能力时再用它：

- 更大的数据集
- 并发 worker
- 更强的查询性能
- pgvector 语义检索

启动 Docker Desktop 后：

```powershell
docker compose up -d postgres
```

然后以 `.env.postgres.example` 作为配置参考。

> 说明：早期版本曾在 docker-compose 中包含 redis 容器，用于规划中的 Celery 队列。
> 该队列已从代码中移除，redis 容器也已从 `docker-compose.yml` 删除；如果将来重新
> 引入独立 worker，再按需添加。

Windows 上的 Docker Desktop 可通过 WSL 后端运行这些 Linux 容器。只要 Docker Desktop
本身工作正常，你无需为本项目单独安装 Ubuntu/Debian WSL 发行版。
