#!/bin/bash

# 最终修复和部署脚本

set -e

echo "🚀 自动化测试平台 - 最终修复和部署"
echo "==================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 函数：打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 步骤1：检查当前配置
print_info "步骤1: 检查当前配置..."
CURRENT_ENV=$(grep -o '"envId": *"[^"]*"' cloudbaserc.json 2>/dev/null | head -1 | cut -d'"' -f4 || echo "未找到")
print_info "当前环境ID: '$CURRENT_ENV'"

# 步骤2：检查CloudBase CLI
print_info "步骤2: 检查CloudBase CLI..."
if command -v cloudbase &> /dev/null; then
    print_success "CloudBase CLI 已安装"
else
    print_warning "CloudBase CLI 未安装"
    read -p "是否安装CloudBase CLI？ (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "正在安装 CloudBase CLI..."
        npm install -g @cloudbase/cli
        print_success "CloudBase CLI 安装完成"
    else
        print_error "需要安装CloudBase CLI才能继续"
        exit 1
    fi
fi

# 步骤3：检查登录状态
print_info "步骤3: 检查CloudBase登录状态..."
if cloudbase login list 2>/dev/null | grep -q "已登录"; then
    print_success "已登录 CloudBase"
else
    print_warning "未登录 CloudBase"
    print_info "请打开浏览器完成登录..."
    cloudbase login
fi

# 步骤4：获取环境列表
print_info "步骤4: 获取可用的环境..."
echo ""
echo "你的CloudBase环境列表:"
echo "----------------------"
cloudbase env:list
echo "----------------------"

# 步骤5：选择或创建环境
print_info "步骤5: 配置环境..."
echo ""
echo "请选择操作:"
echo "1) 使用现有环境（从上面列表中选择）"
echo "2) 创建新环境"
echo "3) 使用默认环境名 'default'"
read -p "请输入选项 (1/2/3): " ENV_OPTION

case $ENV_OPTION in
    1)
        read -p "请输入环境ID: " ENV_ID
        ;;
    2)
        read -p "请输入新环境名 (建议: test-platform): " NEW_ENV
        print_info "正在创建环境 '$NEW_ENV'..."
        cloudbase env:create "$NEW_ENV"
        ENV_ID="$NEW_ENV"
        ;;
    3)
        ENV_ID="default"
        print_info "使用默认环境: 'default'"
        ;;
    *)
        print_error "无效选项"
        exit 1
        ;;
esac

# 步骤6：更新配置文件
print_info "步骤6: 更新配置文件..."
if [[ "$CURRENT_ENV" != "$ENV_ID" ]]; then
    print_info "将环境ID从 '$CURRENT_ENV' 更新为 '$ENV_ID'"
    
    # 备份原文件
    cp cloudbaserc.json "cloudbaserc.json.backup.$(date +%Y%m%d_%H%M%S)"
    
    # 更新环境ID
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS
        sed -i '' "s/\"envId\": \".*\"/\"envId\": \"$ENV_ID\"/" cloudbaserc.json
    else
        # Linux
        sed -i "s/\"envId\": \".*\"/\"envId\": \"$ENV_ID\"/" cloudbaserc.json
    fi
    
    print_success "配置文件已更新"
else
    print_info "环境ID未改变，跳过更新"
fi

# 步骤7：验证环境
print_info "步骤7: 验证环境 '$ENV_ID'..."
if cloudbase env:info "$ENV_ID" &>/dev/null; then
    print_success "环境 '$ENV_ID' 验证成功"
else
    print_error "环境 '$ENV_ID' 验证失败"
    print_info "请检查环境是否存在或拼写是否正确"
    exit 1
fi

# 步骤8：构建前端
print_info "步骤8: 构建前端..."
cd frontend
print_info "安装依赖..."
npm install
print_info "构建应用..."
npm run build
cd ..
print_success "前端构建完成"

# 步骤9：部署
print_info "步骤9: 开始部署..."
echo ""
echo "部署配置:"
echo "  环境: $ENV_ID"
echo "  区域: ap-shanghai"
echo "  前端: frontend/dist"
echo "  后端: backend (云函数)"
echo ""

# 部署前端
print_info "部署前端静态托管..."
cloudbase hosting:deploy frontend/dist -e "$ENV_ID"

# 部署后端
print_info "部署后端云函数..."
cloudbase functions:deploy test-platform-api

print_success "部署完成！"

# 步骤10：显示访问信息
print_info "步骤10: 部署结果"
echo ""
echo "🎉 部署成功！"
echo ""
echo "🌐 访问地址:"
echo "   前端: https://$ENV_ID.tcloudbaseapp.com"
echo "   测试页面: https://$ENV_ID.tcloudbaseapp.com/test.html"
echo "   API服务: https://$ENV_ID.service.tcloudbase.com/api"
echo "   健康检查: https://$ENV_ID.service.tcloudbase.com/api/v1/system/health"
echo "   API文档: https://$ENV_ID.service.tcloudbase.com/api/docs"
echo ""
echo "🔧 管理控制台:"
echo "   https://console.cloud.tencent.com/tcb/env/$ENV_ID"
echo ""
echo "📋 验证步骤:"
echo "   1. 打开浏览器访问测试页面"
echo "   2. 检查是否能看到测试页面"
echo "   3. 访问主应用页面"
echo "   4. 验证API服务"
echo ""
echo "📝 注意事项:"
echo "   - 首次访问可能需要几分钟生效"
echo "   - 如果遇到问题，查看 CloudBase 控制台日志"
echo "   - 数据库配置需要单独设置"

print_success "脚本执行完成！"