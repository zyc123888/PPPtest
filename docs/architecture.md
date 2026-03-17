# 自动化测试平台架构设计

## 目标

构建一套面向测试工程师的自动化测试平台，支持：

- API 接口测试管理与异步执行
- Web UI 测试管理与异步执行
- 平台自身的接口自测与 Playwright 自测
- 常用测试工具集
- Docker 一键部署

## 技术栈

- 后端：FastAPI + SQLAlchemy + Celery + Redis + MySQL
- 前端：Vue 3 + Vite + Nginx
- 异步任务：Celery Worker
- 自动化测试：pytest + Playwright
- 编排：Docker Compose

## 组件划分

### 1. 后端服务 `backend`

负责：

- 项目管理
- API 用例管理
- UI 用例管理
- 执行记录管理
- 系统健康检查
- 常用工具接口

### 2. 任务执行服务 `worker`

负责：

- 异步执行 API 测试用例
- 使用 Playwright 异步执行 UI 测试用例
- 将执行结果写回 MySQL

### 3. 前端服务 `frontend`

提供中文控制台：

- 首页总览
- 健康状态面板
- 项目与用例管理
- 执行中心
- 常用工具

### 4. 基础设施

- MySQL：持久化项目、用例和执行记录
- Redis：Celery broker / backend

### 5. 自测套件

- `backend/tests`：使用 pytest 对已启动系统做接口与异步执行验证
- `e2e/tests`：使用 Playwright 验证平台前端可访问并可执行基本交互

## 核心流程

1. 用户通过前端查看项目、用例、系统状态。
2. 用户点击执行 API/UI 测试。
3. FastAPI 创建执行记录并投递 Celery 任务。
4. Worker 执行用例并更新执行状态。
5. 前端轮询执行记录并展示结果。

## 数据模型

### Project

- 项目名称
- 描述
- 基础地址

### APICase

- 所属项目
- 请求方法
- 请求路径
- 请求头
- 请求体
- 预期状态码

### UICase

- 所属项目
- 目标地址
- Playwright 步骤
- 期望文本

### TestRun

- 用例类型
- 用例名称
- 状态
- 任务 ID
- 摘要
- 请求/响应快照
- 耗时

## 开发策略

1. 先定义后端模型、接口和任务执行框架。
2. 再实现中文前端控制台。
3. 补齐 pytest 与 Playwright 自测。
4. 最后通过 Docker Compose 实际启动并迭代修复。

