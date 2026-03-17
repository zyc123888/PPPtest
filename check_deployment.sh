#!/bin/bash

# 检查部署状态脚本

set -e

echo "🔍 检查自动化测试平台部署状态..."

# 检查 CloudBase CLI
echo "1. 检查 CloudBase CLI..."
if command -v cloudbase &> /dev/null; then
    echo "   ✅ CloudBase CLI 已安装"
    cloudbase --version
else
    echo "   ❌ CloudBase CLI 未安装"
    echo "   请执行: npm install -g @cloudbase/cli"
fi

echo ""
echo "2. 检查登录状态..."
if cloudbase login list 2>/dev/null | grep -q "已登录"; then
    echo "   ✅ 已登录 CloudBase"
else
    echo "   ❌ 未登录 CloudBase"
    echo "   请执行: cloudbase login"
fi

echo ""
echo "3. 检查前端构建..."
if [ -d "frontend/dist" ] && [ -f "frontend/dist/index.html" ]; then
    echo "   ✅ 前端已构建"
    echo "   文件数量: $(find frontend/dist -type f | wc -l)"
else
    echo "   ❌ 前端未构建或构建不完整"
    echo "   请执行: cd frontend && npm run build && cd .."
fi

echo ""
echo "4. 检查配置文件..."
if [ -f "cloudbaserc.json" ]; then
    echo "   ✅ cloudbaserc.json 存在"
    # 检查重写规则
    if grep -q "rewrites" cloudbaserc.json; then
        echo "   ✅ 重写规则已配置"
    else
        echo "   ⚠️  缺少重写规则（SPA支持）"
    fi
else
    echo "   ❌ cloudbaserc.json 不存在"
fi

echo ""
echo "5. 检查后端云函数配置..."
if [ -f "backend/scf_handler.py" ]; then
    echo "   ✅ 云函数入口文件存在"
else
    echo "   ❌ 云函数入口文件不存在"
fi

echo ""
echo "6. 检查数据库配置..."
if [ -f "backend/.env.example" ]; then
    echo "   ✅ 数据库配置模板存在"
else
    echo "   ❌ 数据库配置模板不存在"
fi

echo ""
echo "📊 部署状态总结:"
echo ""
echo "如果所有检查都通过 ✅，请执行以下命令部署:"
echo "  ./quick_deploy.sh"
echo ""
echo "如果遇到 HTTP 418 错误，请检查:"
echo "  1. CloudBase 静态托管是否已启用"
echo "  2. 域名是否正确配置"
echo "  3. 前端是否已正确部署"
echo ""
echo "🔧 故障排除步骤:"
echo "  1. 重新构建前端: cd frontend && npm run build && cd .."
echo "  2. 重新部署: cloudbase hosting:deploy frontend/dist -e test-platform-env"
echo "  3. 访问测试页面: https://test-platform-env-xxx.tcloudbaseapp.com/test.html"
echo "  4. 检查 CloudBase 控制台日志"
echo ""
echo "📞 如果问题仍然存在，请提供:"
echo "  - 具体的错误信息"
echo "  - CloudBase 环境ID"
echo "  - 访问的完整URL"