#!/usr/bin/env python3
"""
验证 CloudBase 部署访问性
"""

import requests
import sys
import json
from urllib.parse import urljoin

def test_url(url, description):
    """测试URL访问性"""
    print(f"\n🔍 测试: {description}")
    print(f"   URL: {url}")
    
    try:
        response = requests.get(url, timeout=10, allow_redirects=True)
        print(f"   状态码: {response.status_code}")
        print(f"   响应大小: {len(response.content)} bytes")
        
        if response.status_code == 200:
            print("   ✅ 访问成功")
            return True
        elif response.status_code == 418:
            print("   ❌ HTTP 418 - I'm a teapot")
            print("      通常表示服务器配置错误或代理问题")
            return False
        else:
            print(f"   ⚠️  非200状态码: {response.status_code}")
            print(f"      响应头部: {dict(response.headers)}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"   ❌ 请求失败: {e}")
        return False

def main():
    print("🚀 CloudBase 部署验证脚本")
    print("=" * 50)
    
    # 从配置文件读取环境ID
    try:
        with open('cloudbaserc.json', 'r') as f:
            config = json.load(f)
        env_id = config.get('envId', 'test-platform-env')
        print(f"环境ID: {env_id}")
    except Exception as e:
        print(f"读取配置文件失败: {e}")
        env_id = 'test-platform-env'
    
    # 构建测试URL
    base_url = f"https://{env_id}.tcloudbaseapp.com"
    api_base = f"https://{env_id}.service.tcloudbase.com"
    
    tests = [
        (f"{base_url}/test.html", "前端测试页面"),
        (f"{base_url}/", "前端主应用"),
        (f"{base_url}/index.html", "前端index.html"),
        (f"{api_base}/api/v1/system/health", "API健康检查"),
        (f"{api_base}/api/docs", "API文档"),
    ]
    
    success_count = 0
    for url, desc in tests:
        if test_url(url, desc):
            success_count += 1
    
    print(f"\n{'='*50}")
    print(f"测试结果: {success_count}/{len(tests)} 通过")
    
    if success_count == 0:
        print("\n❌ 所有测试都失败，可能的原因:")
        print("   1. 应用未部署到 CloudBase")
        print("   2. 环境ID不正确")
        print("   3. CloudBase 服务有问题")
        print("   4. 网络连接问题")
    elif success_count < len(tests):
        print("\n⚠️  部分测试失败:")
        print("   检查 CloudBase 控制台配置")
        print("   验证重写规则是否正确")
    else:
        print("\n✅ 所有测试通过！部署成功！")
    
    print(f"\n📋 建议:")
    print(f"   1. 登录 CloudBase 控制台: https://console.cloud.tencent.com/tcb")
    print(f"   2. 检查环境 '{env_id}' 的状态")
    print(f"   3. 查看静态托管和云函数日志")
    print(f"   4. 验证重写规则配置")

if __name__ == "__main__":
    main()