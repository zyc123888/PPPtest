# 数据库配置指南

## 📊 CloudBase 数据库设置

### 1. 创建 MySQL 数据库实例

1. **登录 CloudBase 控制台**
   - 访问: https://console.cloud.tencent.com/tcb
   - 选择您的环境或创建新环境

2. **创建数据库实例**
   - 进入 "数据库" > "MySQL"
   - 点击 "新建 MySQL 实例"
   - 选择合适的配置:
     - 规格: 至少 1GB 内存
     - 存储: 至少 10GB
     - 版本: MySQL 8.0

3. **创建数据库和用户**
   ```sql
   -- 创建数据库
   CREATE DATABASE test_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   
   -- 创建用户
   CREATE USER 'tester'@'%' IDENTIFIED BY 'your_secure_password';
   
   -- 授予权限
   GRANT ALL PRIVILEGES ON test_platform.* TO 'tester'@'%';
   FLUSH PRIVILEGES;
   ```

### 2. 获取数据库连接信息

在 CloudBase 控制台获取：
- **主机地址**: 数据库实例的访问地址
- **端口**: 通常为 3306
- **用户名**: 您创建的用户名
- **密码**: 您设置的密码
- **数据库名**: `test_platform`

### 3. 创建 Redis 缓存实例

1. **进入 CloudBase 控制台**
   - 进入 "数据库" > "Redis"

2. **创建 Redis 实例**
   - 点击 "新建 Redis 实例"
   - 配置建议:
     - 规格: 至少 256MB 内存
     - 版本: Redis 5.0+

3. **获取连接信息**
   - 获取 Redis 实例的连接地址和端口

## 🔧 配置文件更新

### 1. 更新 `cloudbaserc.json`

将以下配置替换为您的实际连接信息：

```json
{
  "envVariables": {
    "DATABASE_URL": "mysql+pymysql://tester:your_password@your_db_host:3306/test_platform",
    "REDIS_URL": "redis://your_redis_host:6379/0",
    "CELERY_BROKER_URL": "redis://your_redis_host:6379/0",
    "CELERY_RESULT_BACKEND": "redis://your_redis_host:6379/0"
  }
}
```

### 2. 创建 `.env` 文件（本地开发）

在 `backend/` 目录下创建 `.env` 文件：

```bash
# 数据库配置
DATABASE_URL=mysql+pymysql://tester:your_password@your_db_host:3306/test_platform

# Redis 配置
REDIS_URL=redis://your_redis_host:6379/0
CELERY_BROKER_URL=redis://your_redis_host:6379/0
CELERY_RESULT_BACKEND=redis://your_redis_host:6379/0

# CORS 配置（生产环境）
CORS_ORIGINS=https://your-domain.tcloudbaseapp.com
```

## 🚀 数据库初始化

### 自动初始化

当云函数首次启动时，会自动：
1. 创建所有数据库表
2. 设置 UTF8MB4 字符集
3. 插入演示数据

### 手动初始化（如果需要）

您可以使用以下命令手动初始化数据库：

```bash
# 进入后端目录
cd backend

# 激活虚拟环境
source venv/bin/activate

# 运行初始化脚本
python -c "
from app.core.database import init_db
from app.services import seed_demo_data
from app.core.database import SessionLocal

print('初始化数据库...')
init_db()

print('插入演示数据...')
with SessionLocal() as db:
    seed_demo_data(db)

print('✅ 数据库初始化完成！')
"
```

## 🧪 验证数据库连接

### 1. 使用 MySQL 客户端测试

```bash
# 连接数据库
mysql -h your_db_host -u tester -p test_platform

# 查看表结构
SHOW TABLES;
DESCRIBE projects;
```

### 2. 通过健康检查接口

部署后访问：
```
GET https://your-env.service.tcloudbase.com/api/v1/system/health
```

响应应该包含数据库状态信息。

## 🔒 安全建议

### 1. 密码安全
- 使用强密码（至少12个字符，包含大小写字母、数字和特殊字符）
- 定期更换密码
- 不要在代码中硬编码密码

### 2. 访问控制
- 限制数据库访问IP范围
- 使用最小权限原则
- 定期审计数据库访问日志

### 3. 备份策略
- 定期自动备份数据库
- 测试备份恢复流程
- 保留多个历史备份版本

## 📈 性能优化

### 1. 数据库配置
```sql
-- 调整连接数
SET GLOBAL max_connections = 200;

-- 优化查询缓存
SET GLOBAL query_cache_size = 64M;

-- 调整 InnoDB 缓冲池
SET GLOBAL innodb_buffer_pool_size = 512M;
```

### 2. 索引优化
确保以下表有适当的索引：
- `projects`: `id`, `workspace_id`
- `test_runs`: `project_id`, `status`, `started_at`
- `api_cases`: `project_id`, `method`
- `ui_cases`: `project_id`, `target_url`

## 🐛 故障排除

### 1. 连接失败
- **错误**: `Can't connect to MySQL server`
  - 检查防火墙设置
  - 确认数据库实例状态
  - 验证连接信息

### 2. 权限错误
- **错误**: `Access denied for user`
  - 检查用户名和密码
  - 验证用户权限
  - 确认数据库名称

### 3. 字符集问题
- **错误**: `Incorrect string value`
  - 确保使用 UTF8MB4 字符集
  - 重新创建数据库表
  - 更新连接字符串

## 📞 支持

如果遇到数据库相关问题，请：
1. 查看 CloudBase 数据库文档
2. 检查 CloudBase 控制台日志
3. 联系腾讯云技术支持