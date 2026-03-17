# 自动化测试平台 - 最终部署指南

## 🎯 部署概览

您的自动化测试平台已准备好部署到腾讯云 CloudBase。部署完成后，您将获得公网可访问的地址。

## 📋 部署前提检查

请确保已完成以下准备工作：

### 1. ✅ CloudBase CLI 已安装
```bash
npm install -g @cloudbase/cli
```

### 2. ✅ CloudBase 账号已登录
```bash
cloudbase login
```

### 3. ✅ 数据库实例已创建
- MySQL 数据库实例
- Redis 缓存实例
- 数据库名: `test_platform`

### 4. ✅ 配置文件已更新
更新 `cloudbaserc.json` 中的数据库连接信息

## 🚀 一键式部署命令

### 方法一：使用部署脚本（推荐）

```bash
# 1. 进入项目目录
cd /Users/zhangyongcheng/Desktop/PPPtest

# 2. 给予执行权限
chmod +x deploy.sh quick_deploy.sh

# 3. 执行部署
./deploy.sh
```

### 方法二：手动部署

```bash
# 1. 构建前端
cd frontend
npm install
npm run build
cd ..

# 2. 部署后端云函数
cloudbase functions:deploy test-platform-api

# 3. 部署前端静态托管
cloudbase hosting:deploy frontend/dist -e test-platform-env
```

## 🌐 获取公网访问地址

### 部署完成后，您将获得：

#### 1. 前端访问地址
```
https://test-platform-env-{随机ID}.tcloudbaseapp.com
```
- **默认首页**: 自动化测试平台控制台
- **功能**: 项目管理、测试用例管理、执行中心、工具集

#### 2. 后端 API 地址
```
https://test-platform-env.service.tcloudbase.com/api
```
- **API 文档**: `/api/docs` (Swagger UI)
- **健康检查**: `/api/v1/system/health`
- **OpenAPI**: `/api/openapi.json`

#### 3. 数据库管理地址
- **MySQL**: CloudBase 控制台 > 数据库 > MySQL
- **Redis**: CloudBase 控制台 > 数据库 > Redis

## 🔧 环境变量配置

在 CloudBase 控制台中设置以下环境变量：

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `DATABASE_URL` | MySQL 连接字符串 | `mysql+pymysql://user:pass@host:3306/test_platform` |
| `REDIS_URL` | Redis 连接字符串 | `redis://host:6379/0` |
| `CELERY_BROKER_URL` | Celery 消息队列 | `redis://host:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery 结果后端 | `redis://host:6379/0` |
| `CORS_ORIGINS` | 跨域白名单 | `https://test-platform-env-*.tcloudbaseapp.com` |

## 📊 系统功能验证

部署完成后，请验证以下功能：

### 1. 健康检查
```bash
curl https://test-platform-env.service.tcloudbase.com/api/v1/system/health
```
预期响应: `{"status":"healthy","database":"connected","redis":"connected"}`

### 2. 前端访问
1. 打开浏览器访问前端地址
2. 检查控制台是否正常加载
3. 验证中文界面显示

### 3. 数据库初始化
系统首次启动会自动：
- 创建所有数据库表
- 插入演示数据
- 初始化测试项目

## 🛡️ 安全配置建议

### 1. 访问控制
- 设置 IP 访问白名单
- 启用 HTTPS 强制跳转
- 配置访问频率限制

### 2. 数据安全
- 定期备份数据库
- 启用数据库审计日志
- 使用强密码策略

### 3. 监控告警
- 设置云函数调用监控
- 配置数据库性能告警
- 监控 Redis 内存使用

## 🔄 更新与维护

### 1. 代码更新
```bash
# 拉取最新代码
git pull

# 重新构建并部署
./quick_deploy.sh
```

### 2. 数据库迁移
```bash
# 备份数据库
cloudbase database:backup test_platform

# 恢复数据库
cloudbase database:restore backup_file.sql
```

### 3. 日志查看
```bash
# 查看云函数日志
cloudbase functions:log test-platform-api

# 查看部署日志
cloudbase hosting:log
```

## 📞 技术支持

### 1. 部署问题
- 检查 `cloudbaserc.json` 配置
- 查看 CloudBase CLI 错误信息
- 验证数据库连接

### 2. 应用问题
- 查看云函数日志
- 检查浏览器控制台错误
- 验证环境变量设置

### 3. 腾讯云支持
- CloudBase 文档: https://docs.cloudbase.net/
- 技术支持: CloudBase 控制台 > 技术支持
- 社区论坛: https://cloud.tencent.com/developer/ask

## 🎉 部署成功提示

当您看到以下信息时，表示部署已完成：

```
✅ 部署完成！

🌐 访问地址:
- 前端: https://test-platform-env-xxx.tcloudbaseapp.com
- 后端API: https://test-platform-env.service.tcloudbase.com/api
- API文档: https://test-platform-env.service.tcloudbase.com/api/docs

📊 系统状态:
- 数据库: 已连接
- Redis: 已连接
- 云函数: 运行中
- 静态托管: 已部署

🚀 开始使用自动化测试平台吧！
```

## 📝 注意事项

1. **首次启动**: 系统需要几分钟初始化数据库
2. **公网访问**: 地址是公开的，请确保安全配置
3. **成本控制**: 监控资源使用，避免意外费用
4. **备份策略**: 定期备份重要数据
5. **版本管理**: 记录每次部署的版本信息