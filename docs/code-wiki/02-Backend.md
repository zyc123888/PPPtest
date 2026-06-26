# 02 后端（FastAPI）

## 目录结构

```text
backend/
└── app/
    ├── main.py              # FastAPI app 创建与路由挂载
    ├── api.py               # API 路由与鉴权/权限守卫
    ├── models.py            # SQLAlchemy ORM（核心数据模型）
    ├── schemas.py           # Pydantic 请求/响应模型
    ├── services.py          # 业务服务层（初始化、鉴权、执行落库、工具能力等）
    ├── core/
    │   ├── config.py        # Settings（环境变量 -> 配置）
    │   ├── database.py      # engine/SessionLocal/init_db/ensure_schema
    │   └── celery_app.py    # Celery 配置与任务注册
    └── tasks/
        ├── executions.py    # 用例执行引擎（API/UI/性能/计划）
        └── case_generation.py # 用例生成（抓取/解析/AI/产物落地）
```

## 应用入口与生命周期

- FastAPI 应用： [main.py](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/main.py)
  - `lifespan()` 启动阶段会调用 `bootstrap_application()`，进而触发 `services.bootstrap_runtime()` 初始化表结构与默认数据（可配置关闭）（见 [main.py:L12-L33](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/main.py#L12-L33)、[services.py:L376-L396](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/services.py#L376-L396)）
  - 路由统一挂载到 `settings.api_v1_prefix`（默认 `/api/v1`）（见 [main.py:L33-L45](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/main.py#L33-L45)、[config.py:L7-L16](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/core/config.py#L7-L16)）

## 配置（Settings 与环境变量）

- 配置定义： [config.py](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/core/config.py)
  - `SettingsConfigDict(env_file=".env")`：默认从 `backend/.env` 或容器注入环境变量读取（见 [config.py:L35-L40](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/core/config.py#L35-L40)）
  - 核心参数：`DATABASE_URL/REDIS_URL/CELERY_BROKER_URL/CELERY_RESULT_BACKEND/CORS_ORIGINS/...`（见 [config.py:L7-L34](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/core/config.py#L7-L34)）
- Compose 中的生产式配置示例： [docker-compose.yml:L45-L55](file:///Users/zhangyongcheng/Desktop/PPPtest/docker-compose.yml#L45-L55)

## 路由组织（public vs protected）

- 路由聚合： [api.py](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py)
  - `public_router = APIRouter()`：免登录接口（典型：健康检查、登录）
  - `protected_router = APIRouter(dependencies=[Depends(get_current_user)])`：默认需要 Bearer Token（见 [api.py:L692-L694](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L692-L694)）

### 鉴权与角色

- Bearer token 解析：`auth_scheme = HTTPBearer(auto_error=False)`（见 [api.py:L55-L68](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L55-L68)）
- 当前用户：`get_current_user()` 通过 `services.get_user_by_token()` 查表校验 token（见 [api.py:L59-L68](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L59-L68)、[services.py:L571-L576](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/services.py#L571-L576)）
- 角色守卫：
  - `require_admin()`：仅 admin（见 [api.py:L71-L74](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L71-L74)）
  - `require_tester()`：admin 或 tester（见 [api.py:L77-L80](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L77-L80)）
- 工作空间权限：基于 `WorkspaceMember` 控制 workspace/project 可见性（见 [api.py:L83-L123](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L83-L123)）

### 关键接口示例（按域）

- 系统
  - `GET /system/health`（public）：数据库/Redis 连通性（见 [api.py:L712-L715](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L712-L715)、[services.py:L398-L418](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/services.py#L398-L418)）
  - `GET /system/info`（protected）：运行配置概览（敏感信息会被 mask）（见 [api.py:L717-L720](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L717-L720)、[services.py:L421-L438](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/services.py#L421-L438)）
  - `POST /system/bootstrap`（admin）：手动初始化/补齐 schema（见 [api.py:L722-L731](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L722-L731)）
- 认证
  - `POST /auth/login`（public）：签发 token（见 [api.py:L734-L741](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L734-L741)、[services.py:L543-L562](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/services.py#L543-L562)）
  - `POST /auth/logout`（protected）：撤销 token（见 [api.py:L743-L750](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L743-L750)）
  - `GET /auth/me`（protected）：用户信息 + 可访问工作空间（见 [api.py:L752-L755](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L752-L755)）
- 仪表盘
  - `GET /dashboard/summary`：聚合工作空间/项目/用例/执行统计（见 [api.py:L757-L764](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L757-L764)、[services.py:L440-L496](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/services.py#L440-L496)）
- 工作空间
  - `GET /workspaces`：按角色过滤（admin=全量，否则仅成员空间）（见 [api.py:L766-L774](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L766-L774)）

## 数据库访问与初始化策略

- SQLAlchemy engine / Session： [database.py](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/core/database.py)
  - `engine = create_engine(settings.database_url, ...)`
  - `SessionLocal = sessionmaker(...)`
  - `init_db()`：`Base.metadata.create_all` + `ensure_schema()`（在非迁移体系下用“补列/补索引”方式演进）（见 [database.py:L22-L39](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/core/database.py#L22-L39)）
- 启动时 bootstrap：`services.bootstrap_runtime()` 会调用 `init_db()` 并创建默认空间/管理员等（见 [services.py:L376-L396](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/services.py#L376-L396)、[services.py:L124-L185](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/services.py#L124-L185)）

## Schema（Pydantic）与 API 校验

- Pydantic 定义集中于： [schemas.py](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/schemas.py)
  - 以 `*Create/*Update/*Read` 命名，`Read` 继承 `ORMBaseModel(from_attributes=True)` 直接从 ORM 转换（见 [schemas.py:L6-L8](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/schemas.py#L6-L8)）
  - 对字段长度/数值范围做约束，例如 `ProjectCreate.name`、`APICaseCreate.expected_status`（见 [schemas.py:L10-L45](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/schemas.py#L10-L45)）

## “同步执行 vs 异步执行”的分发策略

API 层在触发执行任务时，会走 `_dispatch_task_or_run_inline()`：

- 条件满足时直接同步执行（便于本地调试/pytest）：`settings.app_env == "local"` 或 `PYTEST_CURRENT_TEST` 等（见 [api.py:L696-L709](file:///Users/zhangyongcheng/Desktop/PPPtest/backend/app/api.py#L696-L709)）
- 否则调用 Celery 的 `task_func.delay(record_id)` 投递到 Redis，由 worker 异步执行

