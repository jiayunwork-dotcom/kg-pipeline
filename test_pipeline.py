#!/usr/bin/env python3
"""快速测试核心Pipeline逻辑"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_re():
    from src.pipeline.re import REPredictor
    from src.models.schemas import Entity
    re_pred = REPredictor()
    sentence = '阿里巴巴集团由马云于1999年在杭州创立。'
    entities = [
        Entity(text='阿里巴巴集团', type='ORG', start=0, end=6, confidence=0.95),
        Entity(text='马云', type='PER', start=7, end=9, confidence=1.0),
        Entity(text='杭州', type='LOC', start=16, end=18, confidence=1.0),
    ]
    relations = re_pred.predict_sentence(sentence, entities)
    print("=== 关系抽取测试 ===")
    count = 0
    for rel in relations:
        if rel.relation != '无关系':
            print(f"  {rel.head_text} --[{rel.relation}]--> {rel.tail_text} (conf={rel.confidence:.2f})")
            count += 1
    print(f"共抽取 {count} 条有效关系")
    return True

def test_fusion():
    from src.pipeline.entity_fusion import EntityFusion
    fusion = EntityFusion()
    print("\n=== 实体融合测试 ===")
    
    test_names = ['阿里巴巴', '阿里巴巴集团', '阿里', 'Alibaba', '阿里巴巴有限公司']
    print("名称规范化:")
    for name in test_names:
        norm = fusion.normalize_name(name)
        print(f"  {name:20s} -> {norm}")
    
    print("\n编辑距离计算:")
    pairs = [('阿里巴巴', '阿里'), ('阿里巴巴', '腾讯'), ('马云', '马化腾')]
    for n1, n2 in pairs:
        dist = fusion.normalized_edit_distance(n1, n2)
        print(f"  {n1} <-> {n2}: {dist:.4f} {'(可合并)' if dist < 0.3 else '(不同实体)'}")
    return True

def test_ner():
    from src.pipeline.ner import NERPredictor, CustomDictionary
    ner = NERPredictor()
    
    csv_content = """阿里巴巴,ORG
马云,PER
杭州,LOC
通义千问,WORK"""
    custom_dict = CustomDictionary.from_csv(csv_content)
    
    test_sentence = '阿里巴巴集团由马云于1999年在杭州创立'
    entities = ner.predict(test_sentence, custom_dict)
    
    print("\n=== NER实体识别测试 ===")
    print(f"句子: {test_sentence}")
    for e in entities:
        print(f"  [{e.type}] {e.text:15s} 位置:{e.start}-{e.end} 置信度:{e.confidence:.2f} 来源:{e.source}")
    return True

if __name__ == "__main__":
    print("知识图谱Pipeline核心逻辑测试")
    print("=" * 50)
    try:
        test_ner()
        test_re()
        test_fusion()
        print("\n" + "=" * 50)
        print("✅ 所有测试通过!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
