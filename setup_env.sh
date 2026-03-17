#!/bin/bash

# CloudBase 环境设置脚本

set -e

echo "🚀 CloudBase 环境设置"
echo "====================="

# 检查 CloudBase CLI
echo "1. 检查 CloudBase CLI..."
if command -v cloudbase &> /dev/null; then
    echo "   ✅ CloudBase CLI 已安装"
    CLOUDBASE_VERSION=$(cloudbase --version)
    echo "   版本: $CLOUDBASE_VERSION"
else
    echo "   ❌ CloudBase CLI 未安装"
    echo "   正在安装 CloudBase CLI..."
    npm install -g @cloudbase/cli
    echo "   ✅ CloudBase CLI 安装完成"
fi

echo ""
echo "2. 检查登录状态..."
if cloudbase login list 2>/dev/null | grep -q "已登录"; then
    echo "   ✅ 已登录 CloudBase"
else
    echo "   ❌ 未登录 CloudBase"
    echo "   请打开浏览器完成登录..."
    cloudbase login
fi

echo ""
echo "3. 查看现有环境..."
echo "   执行命令: cloudbase env:list"
echo ""
echo "   等待命令执行..."
cloudbase env:list

echo ""
echo "4. 环境配置选项:"
echo ""
echo "   A) 使用现有环境"
echo "      1. 从上面列表中选择一个环境ID"
echo "      2. 更新 cloudbaserc.json 中的 envId"
echo "      3. 例如: \"envId\": \"your-existing-env-id\""
echo ""
echo "   B) 创建新环境"
echo "      执行命令: cloudbase env:create test-platform-env"
echo ""
echo "   C) 检查环境详情"
echo "      执行命令: cloudbase env:info test-platform-env"
echo "      或: cloudbase env:info your-env-id"

echo ""
echo "5. 更新配置文件:"
echo "   编辑 cloudbaserc.json，将 \"envId\" 的值改为你的实际环境ID"
echo ""
echo "   🔧 快速更新命令:"
echo "   sed -i '' 's/\"envId\": \".*\"/\"envId\": \"YOUR-ENV-ID\"/' cloudbaserc.json"
echo ""
echo "6. 验证环境:"
echo "   执行命令: cloudbase env:info YOUR-ENV-ID"
echo "   应该看到环境状态为 \"正常\""

echo ""
echo "📌 重要提示:"
echo "   1. 环境ID是唯一的，区分大小写"
echo "   2. 确保环境在正确的区域（ap-shanghai）"
echo "   3. 环境创建后可能需要几分钟才能完全就绪"
echo ""
echo "🔗 CloudBase 控制台:"
echo "   https://console.cloud.tencent.com/tcb"