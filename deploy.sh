#!/bin/bash

# 自动化测试平台 - CloudBase 部署脚本

set -e

echo "🚀 开始部署自动化测试平台到 CloudBase..."

# 检查 CloudBase CLI 是否已安装
if ! command -v cloudbase &> /dev/null; then
    echo "❌ CloudBase CLI 未安装，请先安装: npm install -g @cloudbase/cli"
    exit 1
fi

# 检查是否已登录
if ! cloudbase login list | grep -q "已登录"; then
    echo "🔑 请先登录 CloudBase: cloudbase login"
    exit 1
fi

echo "📦 构建前端..."
cd frontend
npm install
npm run build
cd ..

echo "🐍 准备后端云函数..."
cd backend

# 安装依赖（如果需要）
if [ ! -d "venv" ]; then
    echo "📦 创建Python虚拟环境并安装依赖..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

cd ..

echo "🌐 部署到 CloudBase..."
echo "注意: 部署前请确保 cloudbaserc.json 中的数据库配置已正确设置"

# 显示部署命令提示
echo ""
echo "📋 部署步骤:"
echo "1. 确保数据库已准备就绪:"
echo "   - MySQL 数据库: test_platform"
echo "   - Redis 实例"
echo ""
echo "2. 更新 cloudbaserc.json 中的数据库连接信息:"
echo "   - DATABASE_URL"
echo "   - REDIS_URL"
echo ""
echo "3. 检查 CloudBase CLI 是否已安装和登录:"
echo "   cloudbase --version"
echo "   cloudbase login list"
echo ""
echo "4. 执行部署命令:"
echo "   cloudbase functions:deploy test-platform-api"
echo "   cloudbase hosting:deploy frontend/dist -e test-platform-env"
echo ""
echo "5. 部署完成后，可以通过以下地址访问:"
echo "   - 前端测试页面: https://test-platform-env-xxx.tcloudbaseapp.com/test.html"
echo "   - 主应用: https://test-platform-env-xxx.tcloudbaseapp.com"
echo "   - 后端API: https://test-platform-env.service.tcloudbase.com/api"
echo "   - 健康检查: https://test-platform-env.service.tcloudbase.com/api/v1/system/health"
echo "   - API文档: https://test-platform-env.service.tcloudbase.com/api/docs"
echo ""
echo "📝 详细部署指南请查看 README-cloudbase.md"
echo ""
echo "⚠️  如果遇到 HTTP 418 错误，可能是以下原因:"
echo "   - CloudBase CLI 未正确安装或登录"
echo "   - 静态托管服务未启用"
echo "   - 域名配置有问题"
echo "   - 前端未正确构建或部署"

# 创建快捷部署命令
cat > quick_deploy.sh << 'EOF'
#!/bin/bash
# 快速部署脚本
set -e
echo "🚀 快速部署..."
cloudbase functions:deploy test-platform-api
cloudbase hosting:deploy frontend/dist -e test-platform-env
echo "✅ 部署完成！"
EOF

chmod +x quick_deploy.sh

echo "✅ 部署脚本准备完成！"
echo "📁 生成的文件:"
echo "   - deploy.sh: 主部署脚本"
echo "   - quick_deploy.sh: 快速部署脚本"
echo "   - cloudbaserc.json: CloudBase 配置文件"
echo ""
echo "🚀 开始部署请运行: ./quick_deploy.sh"