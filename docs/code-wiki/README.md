# PPPtest Code Wiki

本 Wiki 面向代码阅读与二次开发，聚焦：

- 项目整体架构与端到端流程
- 主要模块职责与依赖关系
- 关键类与关键函数（含源码跳转）
- 项目运行 / 测试 / 部署方式与环境变量

## 快速导航

- [01-Architecture.md](file:///Users/zhangyongcheng/Desktop/PPPtest/docs/code-wiki/01-Architecture.md)
- [02-Backend.md](file:///Users/zhangyongcheng/Desktop/PPPtest/docs/code-wiki/02-Backend.md)
- [03-Frontend.md](file:///Users/zhangyongcheng/Desktop/PPPtest/docs/code-wiki/03-Frontend.md)
- [04-DataModel.md](file:///Users/zhangyongcheng/Desktop/PPPtest/docs/code-wiki/04-DataModel.md)
- [05-Tasks-Workers.md](file:///Users/zhangyongcheng/Desktop/PPPtest/docs/code-wiki/05-Tasks-Workers.md)
- [06-Run-Test-Deploy.md](file:///Users/zhangyongcheng/Desktop/PPPtest/docs/code-wiki/06-Run-Test-Deploy.md)

## 仓库一览

```text
PPPtest/
├── backend/              # FastAPI + SQLAlchemy + Celery（含 Worker 运行镜像）
├── frontend/             # Vue3 + Vite（开发）+ Nginx（生产镜像）
├── e2e/                  # Playwright 端到端自测
├── scripts/              # 健康检查与全栈验证脚本
├── docs/                 # 项目说明文档（本 Wiki 在 docs/code-wiki 下）
├── docker-compose.yml    # 本地一键启动（mysql/redis/backend/worker/frontend）
└── cloudbaserc.json      # CloudBase 部署（云函数 + 静态托管 + /api 重写）
```

## 术语

- 用例类型：API / UI / Performance（性能）
- 执行记录：TestRun（单用例执行），TestPlanRun（计划执行）
- 产物：执行期间生成的 request/response、日志、截图、报告等，落地到 `backend/reports/`

