#!/usr/bin/env python3
"""
简单的模块导入验证脚本
验证所有核心模块可以正确导入
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

modules = [
    ("src.config", "配置模块"),
    ("src.models.schemas", "数据模型模块"),
    ("src.pipeline.text_processor", "文本处理模块"),
    ("src.pipeline.web_crawler", "网页抓取模块"),
    ("src.pipeline.ner", "NER实体识别模块"),
    ("src.pipeline.re", "RE关系抽取模块"),
    ("src.pipeline.entity_fusion", "实体融合模块"),
    ("src.pipeline.manager", "任务管理模块"),
    ("src.pipeline.quality", "质量评估模块"),
    ("src.pipeline.qa_service", "问答服务模块"),
    ("src.graph.store", "图谱存储模块"),
    ("src.api.qa", "问答API模块"),
]

print("=" * 60)
print("知识图谱Pipeline - 模块导入验证")
print("=" * 60)

success = 0
failed = []

for module_path, module_desc in modules:
    try:
        __import__(module_path)
        print(f"✅ {module_desc} - {module_path}")
        success += 1
    except Exception as e:
        print(f"❌ {module_desc} - {module_path}")
        print(f"   错误: {e}")
        failed.append((module_path, module_desc, str(e)))

print()
print("=" * 60)
print(f"结果: {success}/{len(modules)} 模块导入成功")

if failed:
    print()
    print("失败模块详情:")
    for path, desc, err in failed:
        print(f"  - {desc} ({path}): {err}")
    sys.exit(1)
else:
    print("所有核心模块验证通过！")
    sys.exit(0)
