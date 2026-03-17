"""
CloudBase 云函数入口文件
"""
import json
from fastapi import FastAPI
from mangum import Mangum
import uvicorn
from app.main import app as fastapi_app

# 创建 Mangum handler 用于 CloudBase 云函数
handler = Mangum(fastapi_app)

# 本地调试使用
if __name__ == "__main__":
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8000)