# 自动化测试平台

一个完整的测试工程平台示例，覆盖：

- API 接口测试管理与执行
- Web UI 测试管理与执行
- Celery 异步任务调度
- MySQL / Redis 健康检查
- 中文前端控制台
- pytest 接口自测
- Playwright 前端自测
- Docker Compose 一键部署
- GitHub Actions 构建 GHCR 镜像并自动部署到生产服务器

## 技术栈

- 后端：FastAPI、SQLAlchemy、Celery、PyMySQL、Redis
- 前端：Vue 3、Vite、Nginx
- 基础设施：MySQL 8、Redis 7
- 测试：pytest、Playwright

## 项目结构

```text
PPPtest/
├── backend
│   ├── app
│   │   ├── api.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── services.py
│   │   ├── core
│   │   │   ├── celery_app.py
│   │   │   ├── config.py
│   │   │   └── database.py
│   │   └── tasks
│   │       └── executions.py
│   ├── tests
│   │   ├── conftest.py
│   │   └── test_platform_api.py
│   ├── Dockerfile
│   ├── pytest.ini
│   └── requirements.txt
├── docs
│   └── architecture.md
├── e2e
│   ├── tests
│   │   └── platform.spec.js
│   ├── Dockerfile
│   ├── package.json
│   └── playwright.config.js
├── frontend
│   ├── src
│   │   ├── lib
│   │   │   └── api.js
│   │   ├── styles
│   │   │   └── main.css
│   │   ├── App.vue
│   │   └── main.js
│   ├── Dockerfile
│   ├── index.html
│   ├── nginx.conf
│   ├── package.json
│   └── vite.config.js
├── scripts
│   ├── health_check.sh
│   └── run_stack_tests.sh
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

## 平台能力

### 1. 项目与用例管理

- 新增项目
- 新增 API 用例
- 新增 UI 用例
- 查看项目与用例列表

### 2. 执行中心

- 投递 API 异步测试任务
- 投递 UI 异步测试任务
- 查看运行状态与摘要
- 查看请求/响应快照

### 3. 常用工具

- JSON 格式化
- Base64 编解码
- 时间戳转换

## 默认演示数据

系统启动后会自动初始化：

- 项目：`平台自检项目`
- API 用例：`示例健康检查接口`
- UI 用例：`示例前端首页巡检`

## 本地 Docker 启动

### 1. 启动并验证 Docker（Colima）

macOS 使用 Colima 时，重启电脑后需要先启动 Colima。若 `docker info` 已能正常返回信息，可跳过 `colima start`。

```bash
colima status
colima start
docker info
```

若提示 `colima: command not found`，请使用 Docker Desktop 启动 Docker，或安装并配置 Colima。若提示 Docker socket 不存在，通常表示 Colima 尚未启动。

### 2. 启动项目

```bash
cd /Users/zhangyongcheng/Desktop/PPPtest
docker-compose up -d --build
docker-compose ps
```

`docker-compose ps` 中 backend、frontend、mysql、redis 和 worker 应处于运行状态；backend、frontend、mysql、redis 会显示 `healthy`。

### 3. 访问地址

- 前端：[http://localhost:3000](http://localhost:3000)
- 后端 OpenAPI：[http://localhost:8000/docs](http://localhost:8000/docs)
- 后端健康检查：[http://localhost:8000/api/v1/system/health](http://localhost:8000/api/v1/system/health)

### 4. 运行健康检查

```bash
bash scripts/health_check.sh
```

### 5. 运行后端 pytest

```bash
docker-compose exec -T backend pytest
```

### 6. 运行前端 Playwright 自测

```bash
docker-compose --profile test run --rm e2e
```

### 7. 一键启动并执行全部验证

```bash
bash scripts/run_stack_tests.sh
```

### 8. 停止、重启和清理

```bash
# 临时停止，不删除容器和数据
docker-compose stop

# 恢复已停止的容器
docker-compose start

# 停止并删除容器，保留数据库数据
docker-compose down

# 停止并删除容器和数据库数据（不可恢复）
docker-compose down -v
```

## 后端核心接口

- `GET /api/v1/system/health`：系统健康检查
- `GET /api/v1/system/info`：系统运行信息与配置概览
- `POST /api/v1/system/bootstrap`：手动初始化数据库与演示数据
- `GET /api/v1/dashboard/summary`：仪表盘汇总
- `GET /api/v1/projects`：项目列表
- `POST /api/v1/projects`：创建项目
- `GET /api/v1/api-cases`：接口用例列表
- `POST /api/v1/api-cases`：创建接口用例
- `GET /api/v1/ui-cases`：UI 用例列表
- `POST /api/v1/ui-cases`：创建 UI 用例
- `GET /api/v1/executions/runs`：执行记录
- `POST /api/v1/executions/api/{case_id}/run`：执行 API 用例
- `POST /api/v1/executions/ui/{case_id}/run`：执行 UI 用例
- `POST /api/v1/tools/json/format`：JSON 格式化
- `POST /api/v1/tools/base64/encode`：Base64 编码
- `POST /api/v1/tools/base64/decode`：Base64 解码
- `POST /api/v1/tools/timestamp/convert`：时间戳转换

## 生产部署

生产环境采用 GitHub Actions、GitHub Container Registry 和远程 Docker Compose。完整初始化、Secrets、自动回滚与备份说明见 [生产部署文档](docs/production_deployment.md)。

## 说明

- 前端全部中文呈现。
- 前端通过 Nginx 反向代理 `/api` 到后端，浏览器访问无需额外配置跨域。
- UI 用例由 Celery Worker 调用 Playwright 浏览器执行。
- `backend/tests` 直接对已启动系统执行接口与异步任务验证。
- `e2e/tests` 对平台前端页面执行 Playwright 自测。
