# OmniTest · AI 测试用例生成与执行平台

一个面向测试团队的 **AI 驱动测试用例生成与执行平台**：用大模型把需求/文档自动拆解成结构化用例，并管理 API/UI 用例、测试计划、执行与报告。后端 FastAPI，前端 Vue 3，异步任务 Celery + Redis，端到端用 Playwright 自测。

> Docker Compose 项目名 `omnitest`，GHCR 镜像前缀 `ghcr.io/zyc123888/omnitest`。

## 平台能力

- **AI 用例生成管线**（`backend/app/tasks/case_generation_v2_pipeline/`）
  - 需求 → 功能点 → 测试用例 的确定性拆解与回填
  - JSON 截断检测 + 模型自愈修复、重试审计、并发控制
  - 多模型接入（OpenAI / 阿里云百炼 DashScope / Qwen 兼容端点，走 `httpx` 直连）
  - 模型密钥经 Fernet 加密存储（`app/core/secrets.py`），不在库内落明文
- **项目管理**：工作区（Workspace）、成员与 RBAC、项目（Project）
- **用例管理**：API 用例、UI 用例（含 Tiptap 富文本步骤与图片上传）
- **测试计划与执行**：测试计划（Plan）、异步执行（Execution，Celery Worker 调 pytest / Playwright）
- **报告**：执行摘要、请求/响应快照、产物下载
- **常用工具**：JSON 格式化、Base64 编解码、时间戳转换

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | FastAPI、SQLAlchemy 2.0、Celery、Redis、Pydantic v2、`cryptography`(Fernet) |
| AI 生成 | `httpx` 直连多模型供应商（无 OpenAI SDK 依赖） |
| 前端 | Vue 3、Vite、Pinia、Vue Router 4、Element Plus、Tiptap、设计 Token(`tokens.css`) |
| 数据库 | MariaDB / MySQL（本地 compose 用 `mariadb`；SQLite 可用于单测） |
| 异步 | Celery + Redis（按队列拆分：execution / case_generation / beat） |
| 测试 | pytest（后端）、vitest（前端）、Playwright（e2e） |
| 部署 | Docker Compose（本地）/ GitHub Actions + GHCR + SSH（生产） |

## 目录结构（关键部分）

```text
OmniTest/
├── backend/
│   ├── app/
│   │   ├── api.py                # 路由聚合（当前为单体文件，计划按领域拆分，见 docs）
│   │   ├── main.py               # FastAPI 入口、生命周期、静态上传目录
│   │   ├── models.py             # ORM 模型（SQLAlchemy 2.0 Mapped 风格）
│   │   ├── schemas.py            # Pydantic 请求/响应契约
│   │   ├── services.py           # 业务逻辑层
│   │   ├── core/                 # config / secrets / database / celery_app
│   │   └── tasks/                # executions.py, case_generation_v2.py,
│   │                              # case_generation_v2_pipeline/（AI 生成管线）
│   ├── tests/                    # pytest 集成测试（conftest 拉起 TestClient）
│   ├── Dockerfile                # 多阶段、非 root
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── lib/api.js            # 后端 API 封装（Bearer 鉴权）
│   │   ├── stores/               # Pinia（auth 等）
│   │   ├── router/               # Vue Router 4
│   │   ├── views/                # 用例生成器、API/UI 用例、执行、报告等
│   │   ├── components/           # 公共组件
│   │   └── styles/tokens.css     # 设计 Token
│   ├── Dockerfile / nginx.conf / vite.config.js
│   └── package.json
├── e2e/                          # Playwright 端到端用例（admin_layout / full_flow /
│                                  # workspace_membership_flow / workspace_owner_guard /
│                                  # execution_artifact_download 等）
├── deploy/                       # 生产部署权威配置（compose.production.yml / deploy.sh /
│                                  # bootstrap-server.sh / .env.production.example）
├── docs/                         # 架构与部署文档
├── scripts/                      # health_check.sh / run_stack_tests.sh
├── .github/workflows/            # stack-tests.yml（测试门禁）、publish-deploy.yml（发版部署）
├── docker-compose.yml            # 本地一键起栈
└── README.md
```

## 安全与必填环境变量（重要）

以下变量**无代码内默认值**，缺失会在启动时直接报错（fail-fast），部署前必须提供：

| 变量 | 说明 |
|------|------|
| `INITIAL_ADMIN_PASSWORD` | 初始管理员口令，**禁止使用弱口令**（如 `admin123`） |
| `APP_ENCRYPTION_KEY` | 模型密钥 Fernet 加密密钥。生成：`python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |
| `DATABASE_URL` / `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | 数据库与 Redis 连接 |
| `CORS_ORIGINS` | 前端来源白名单 |

Docker Compose 使用项目根目录的 `.env`；直接运行后端时可参考
`backend/.env.example`。生产环境参考 `deploy/.env.production.example`。

## 本地 Docker 启动

### 1. 准备环境

复制并填写环境变量（至少包含上面的必填项）：

```bash
cp .env.example .env
# 编辑根目录 .env，至少替换数据库口令、INITIAL_ADMIN_PASSWORD 与 APP_ENCRYPTION_KEY
```

### 2. 启动并验证 Docker（macOS Colima）

```bash
colima status || colima start
docker info
```

### 3. 启动项目

```bash
cd PPPtest
docker-compose up -d --build
docker-compose ps
```

`backend` `frontend` `mariadb` `redis` `worker` 应处于运行/`healthy` 状态。

### 4. 访问地址

- 前端：http://localhost:3000
- 后端 OpenAPI：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/v1/system/health

### 5. 运行测试

```bash
# 后端 pytest（容器内）
docker-compose exec -T backend pytest

# 前端 Playwright 端到端（e2e profile）
docker-compose --profile test run --rm e2e

# 一键启动并执行全部验证
bash scripts/run_stack_tests.sh
```

### 6. 停止 / 清理

```bash
docker-compose stop            # 暂停，保留数据
docker-compose start           # 恢复
docker-compose down            # 停止并删容器，保留数据
docker-compose down -v         # 停止并删除容器与数据库数据（不可恢复）
```

## 生产部署

生产采用 GitHub Actions + GitHub Container Registry + 远程 Docker Compose（`deploy/` 为权威配置，`publish-deploy.yml` 在测试通过后构建镜像并 SSH 部署，含 `known_hosts` 与密钥校验、concurrency 保护）。初始化、Secrets、回滚与备份详见 `docs/production_deployment.md` 与 `deploy/.env.production.example`。

## 说明

- 前端全部中文呈现，经 Nginx 反向代理 `/api` 到后端，浏览器无需额外跨域配置。
- UI 用例由 Celery Worker 调用 Playwright 执行；AI 生成管线调用大模型服务。
- 上传图片经 `/api/v1/uploads/{filename}` 提供，读取与上传均要求登录。
- 本 README 取代早期「迷你演示平台」描述，当前内容以真实代码为准。
