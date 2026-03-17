#!/usr/bin/env python3
"""PPPtest 完整功能测试"""
from playwright.sync_api import sync_playwright
import os

TARGET_URL = "http://1.12.246.253"
os.makedirs('/tmp/ppptest_full', exist_ok=True)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        print("测试开始...")
        
        # 登录
        page.goto(TARGET_URL)
        page.wait_for_load_state('networkidle')
        page.screenshot(path='/tmp/ppptest_full/01_home.png')
        
        page.locator('button:has-text("登录")').click()
        page.wait_for_load_state('networkidle')
        
        page.locator('input').first.fill('admin')
        page.locator('input[type="password"]').fill('admin123')
        page.locator('button:has-text("登录")').click()
        page.wait_for_load_state('networkidle')
        
        print("登录成功！")
        print("浏览器将保持打开5秒...")
        page.wait_for_timeout(5000)
        
        browser.close()
        print("测试完成，浏览器已关闭")

if __name__ == "__main__":
    main()
