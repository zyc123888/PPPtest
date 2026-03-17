#!/bin/bash

# 简单部署检查脚本

echo "🔍 简单部署检查"
echo "================"

# 检查配置文件
echo "1. 检查配置文件..."
if [ -f "cloudbaserc.json" ]; then
    ENV_ID=$(grep -o '"envId": *"[^"]*"' cloudbaserc.json | head -1 | cut -d'"' -f4)
    echo "   环境ID: ${ENV_ID:-未找到}"
else
    echo "   ❌ cloudbaserc.json 不存在"
    exit 1
fi

# 构建URL
FRONTEND_URL="https://${ENV_ID}.tcloudbaseapp.com"
API_URL="https://${ENV_ID}.service.tcloudbase.com"

echo ""
echo "2. 测试URL:"
echo "   前端: $FRONTEND_URL"
echo "   API: $API_URL"

echo ""
echo "3. 快速测试 (使用curl)..."
echo "   a) 测试前端:"
if command -v curl &> /dev/null; then
    curl -s -I "$FRONTEND_URL/test.html" | head -1
    echo ""
    echo "   b) 测试健康检查:"
    curl -s -I "$API_URL/api/v1/system/health" | head -1
else
    echo "   ⚠️  curl 未安装，无法进行网络测试"
fi

echo ""
echo "4. 手动验证步骤:"
echo "   a) 打开浏览器访问: $FRONTEND_URL/test.html"
echo "   b) 如果看到测试页面，说明静态托管正常"
echo "   c) 访问: $FRONTEND_URL/"
echo "   d) 如果看到主应用，部署成功"
echo "   e) 如果看到 HTTP 418 错误:"
echo "      - 检查 CloudBase 控制台"
echo "      - 验证静态托管是否启用"
echo "      - 检查域名配置"

echo ""
echo "5. CloudBase 控制台链接:"
echo "   https://console.cloud.tencent.com/tcb/env/$ENV_ID"

echo ""
echo "📌 如果问题仍然存在，请提供:"
echo "   - 具体的错误截图"
echo "   - 浏览器控制台错误"
echo "   - CloudBase 环境ID"