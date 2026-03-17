# 🔧 更新 CloudBase 环境ID指南

## 🎯 问题概述
错误信息: `Env invalid`  
原因: 配置文件中的环境ID `test-platform-env` 不存在或无效

## 🔍 第一步：查看你的环境列表

打开终端，执行以下命令：

```bash
# 1. 确保已安装 CloudBase CLI
npm install -g @cloudbase/cli

# 2. 登录 CloudBase
cloudbase login

# 3. 查看所有环境
cloudbase env:list
```

## 📋 第二步：选择你的环境

从 `cloudbase env:list` 的输出中，选择一个环境ID。常见选项：

1. **默认环境**: `default`
2. **开发环境**: `dev` 或 `development`
3. **生产环境**: `prod` 或 `production`
4. **你的用户名**: 如 `zhangyongcheng`
5. **自动生成的ID**: 如 `env-xxxxxx`

## 🔧 第三步：更新配置文件

### 方法A：使用sed命令（推荐）

```bash
# 替换为你的实际环境ID（例如：default）
sed -i '' 's/"envId": ".*"/"envId": "default"/' cloudbaserc.json

# 验证更改
cat cloudbaserc.json | grep "envId"
```

### 方法B：手动编辑

1. 打开 `cloudbaserc.json`
2. 找到第2行: `"envId": "test-platform-env",`
3. 修改为你的环境ID，例如: `"envId": "default",`
4. 保存文件

### 方法C：使用预设配置

```bash
# 如果使用默认环境
cp cloudbaserc.default.json cloudbaserc.json

# 或者创建新配置
echo '{
  "envId": "YOUR-ENV-ID",
  "region": "ap-shanghai",
  "functionRoot": "./backend",
  "functions": [...],
  "hosting": {...}
}' > cloudbaserc.json
```

## 🧪 第四步：验证环境

```bash
# 检查环境状态
cloudbase env:info YOUR-ENV-ID

# 应该看到类似输出：
# 环境名称: YOUR-ENV-ID
# 环境状态: 正常
# 地域: ap-shanghai
```

## 🚀 第五步：测试部署

```bash
# 测试静态托管部署
cloudbase hosting:deploy frontend/dist -e YOUR-ENV-ID

# 测试云函数部署
cloudbase functions:deploy test-platform-api
```

## ❌ 如果环境不存在

如果没有任何环境，需要创建新环境：

```bash
# 创建新环境
cloudbase env:create test-platform-env

# 或者使用其他名称
cloudbase env:create my-test-platform
```

## 📊 环境配置示例

### 示例1：使用默认环境
```json
{
  "envId": "default",
  "region": "ap-shanghai"
}
```

### 示例2：使用开发环境
```json
{
  "envId": "dev",
  "region": "ap-shanghai"
}
```

### 示例3：使用自定义环境
```json
{
  "envId": "zhangyongcheng-test",
  "region": "ap-shanghai"
}
```

## 🔗 CloudBase 控制台

你也可以在网页控制台查看和管理环境：

1. 访问: https://console.cloud.tencent.com/tcb
2. 登录腾讯云账号
3. 查看"环境管理"
4. 找到你的环境ID

## 📞 需要帮助？

请提供以下信息：
1. `cloudbase env:list` 的完整输出
2. 你想使用的环境ID
3. 任何错误信息的截图

## 🎉 成功标志

当你能成功执行以下命令时，表示环境配置正确：

```bash
# 无错误信息，正常部署
cloudbase hosting:deploy frontend/dist -e YOUR-ENV-ID

# 访问地址应该能正常工作
# 前端: https://YOUR-ENV-ID.tcloudbaseapp.com
# API: https://YOUR-ENV-ID.service.tcloudbase.com/api
```