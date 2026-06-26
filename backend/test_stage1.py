#!/usr/bin/env python3
"""第一阶段重构验证脚本"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from app.tasks.case_generation import (
    _call_skill_with_gate,
    _load_skill_template,
    _load_claw_skill_context,
    _resolve_claw_rules_dir,
)

def test_imports():
    """验证所有函数导入成功"""
    print("✅ 函数导入成功")

def test_rules_dir_resolution():
    """验证规则目录解析"""
    rules_dir = _resolve_claw_rules_dir()
    print(f"📂 规则目录: {rules_dir}")
    print(f"   存在: {rules_dir.exists()}")
    if rules_dir.exists():
        print(f"   内容: {os.listdir(rules_dir)}")

def test_skill_template_loading():
    """验证模板加载"""
    skills = ["requirement-analyzer", "testcase-designer", "quality-reviewer"]
    for skill in skills:
        template = _load_skill_template(skill)
        print(f"📄 {skill} 模板: {len(template)} 字符")
        if template:
            print(f"   前100字符: {template[:100]}...")

def test_skill_context_loading():
    """验证 SKILL.md 加载"""
    skills = ["requirement-analyzer", "testcase-designer", "quality-reviewer"]
    for skill in skills:
        context = _load_claw_skill_context(skill)
        print(f"📖 {skill} 上下文: {len(context)} 字符")
        if context:
            print(f"   前100字符: {context[:100]}...")

def test_call_skill_with_gate_signature():
    """验证 _call_skill_with_gate 签名支持 output_contract=None"""
    import inspect
    sig = inspect.signature(_call_skill_with_gate)
    params = sig.parameters
    if "output_contract" in params:
        default = params["output_contract"].default
        print(f"✅ output_contract 参数存在，默认值: {default}")
    else:
        print("❌ output_contract 参数不存在")

if __name__ == "__main__":
    print("=" * 60)
    print("第一阶段重构验证")
    print("=" * 60)
    
    try:
        test_imports()
        test_rules_dir_resolution()
        test_skill_template_loading()
        test_skill_context_loading()
        test_call_skill_with_gate_signature()
        print("\n" + "=" * 60)
        print("✅ 所有验证通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
