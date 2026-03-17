# 自动化测试平台 - CloudBase 部署指南

## 📋 部署概述

本项目将部署到腾讯云 CloudBase，包含以下组件：

1. **前端**: Vue 3 应用，通过静态托管部署
2. **后端**: FastAPI 应用，通过云函数部署
3. **数据库**: CloudBase 云数据库 (MySQL)
4. **缓存**: CloudBase 云缓存 (Redis)

## 🚀 部署前提

### 1. 安装 CloudBase CLI

```bash
npm install -g @cloudbase/cli
```

### 2. 登录 CloudBase

```bash
cloudbase login
```

### 3. 创建 CloudBase 环境

如果没有环境，请先创建：

```bash
cloudbase env:create test-platform-env
```

## ⚙️ 配置数据库

### 1. 创建云数据库实例

1. 登录 [CloudBase 控制台](https://console.cloud.tencent.com/tcb)
2. 进入环境管理
3. 创建 MySQL 数据库实例
4. 创建数据库 `test_platform`
5. 创建用户并授予权限

### 2. 创建云缓存实例

1. 在 CloudBase 控制台创建 Redis 实例
2. 获取连接信息

### 3. 更新配置文件

编辑 `cloudbaserc.json`，更新以下环境变量：

```json
{
  "envVariables": {
    "DATABASE_URL": "mysql+pymysql://用户名:密码@数据库地址:3306/test_platform",
    "REDIS_URL": "redis://redis地址:6379/0",
    "CELERY_BROKER_URL": "redis://redis地址:6379/0",
    "CELERY_RESULT_BACKEND": "redis://redis地址:6379/0"
  }
}
```

## 🚀 部署步骤

### 1. 构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

### 2. 部署后端云函数

```bash
cloudbase functions:deploy test-platform-api
```

### 3. 部署前端静态托管

```bash
cloudbase hosting:deploy frontend/dist -e test-platform-env
```

### 4. 一键部署（推荐）

```bash
chmod +x deploy.sh
./deploy.sh
```

或使用快速部署脚本：

```bash
chmod +x quick_deploy.sh
./quick_deploy.sh
```

## 🌐 访问地址

部署完成后，可以通过以下地址访问：

### 前端地址
```
https://test-platform-env-xxx.tcloudbaseapp.com
```

### 后端 API 地址
```
https://test-platform-env.service.tcloudbase.com/api
```

### API 文档
```
https://test-platform-env.service.tcloudbase.com/api/docs
```

## 🔧 环境变量配置

### 后端云函数环境变量

在 CloudBase 控制台设置以下环境变量：

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| DATABASE_URL | MySQL 数据库连接 | mysql+pymysql://user:pass@host:3306/test_platform |
| REDIS_URL | Redis 连接 | redis://host:6379/0 |
| CELERY_BROKER_URL | Celery 消息队列 | redis://host:6379/0 |
| CELERY_RESULT_BACKEND | Celery 结果后端 | redis://host:6379/0 |

## 📊 数据库初始化

系统启动时会自动：
1. 创建必要的数据库表
2. 插入演示数据
3. 初始化测试项目

## 🔍 健康检查

部署完成后，可以通过以下接口检查服务状态：

```
GET https://test-platform-env.service.tcloudbase.com/api/v1/system/health
```

## 🛠️ 故障排除

### 1. 云函数部署失败
- 检查 Python 依赖是否正确安装
- 查看云函数日志：`cloudbase functions:log test-platform-api`

### 2. 数据库连接失败
- 检查数据库连接字符串
- 确认数据库权限设置
- 检查网络连接

### 3. 前端无法访问 API
- 检查 API 路径配置
- 查看浏览器控制台错误
- 确认云函数已正确部署

### 4. Redis 连接失败
- 检查 Redis 实例状态
- 确认连接字符串格式
- 检查网络防火墙设置

## 📞 支持

如有问题，请查看：
1. CloudBase 官方文档：https://docs.cloudbase.net/
2. 项目 Issues：提交问题报告
3. 腾讯云技术支持

## 🔄 更新部署

更新代码后，重新执行部署步骤：

```bash
# 1. 更新代码
git pull

# 2. 重新构建前端
cd frontend && npm run build && cd ..

# 3. 重新部署
./quick_deploy.sh
```

## 📝 注意事项

1. **数据库备份**: 定期备份云数据库数据
2. **监控告警**: 设置 CloudBase 监控告警
3. **安全配置**: 配置 HTTPS 和访问控制
4. **成本优化**: 根据使用情况调整资源配置