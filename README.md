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

## 一键部署

### 1. 启动服务

```bash
docker-compose up --build -d

### 如果你连数据库数据也想一起清掉，用：
docker-compose down -v

### 如果只是临时停掉、不删除容器，可以用：
docker-compose stop

### 以后再启动就执行：
docker-compose start

### 或者需要重建时再用：
docker-compose up --build -d







```

### 2. 访问地址

- 前端：[http://localhost:3000](http://localhost:3000)
- 后端 OpenAPI：[http://localhost:8000/docs](http://localhost:8000/docs)
- 后端健康检查：[http://localhost:8000/api/v1/system/health](http://localhost:8000/api/v1/system/health)

### 3. 运行健康检查

```bash
bash scripts/health_check.sh
```

### 4. 运行后端 pytest

```bash
docker-compose exec -T backend pytest
```

### 5. 运行前端 Playwright 自测

```bash
docker-compose --profile test run --rm e2e
```

### 6. 一键启动并执行全部验证

```bash
bash scripts/run_stack_tests.sh
```

## 后端核心接口

- `GET /api/v1/system/health`：系统健康检查
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

## 说明

- 前端全部中文呈现。
- 前端通过 Nginx 反向代理 `/api` 到后端，浏览器访问无需额外配置跨域。
- UI 用例由 Celery Worker 调用 Playwright 浏览器执行。
- `backend/tests` 直接对已启动系统执行接口与异步任务验证。
- `e2e/tests` 对平台前端页面执行 Playwright 自测。
