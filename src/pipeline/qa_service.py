import logging
import re
from typing import List, Dict, Any, Optional, Tuple

from src.models.schemas import (
    QAIntent,
    ParsedQuestion,
    QAResult,
    QAEntity,
    QARelation,
    QAPath,
)
from src.graph.store import GraphStore
from src.pipeline.ner import NERPredictor

logger = logging.getLogger(__name__)


INTENT_PATTERNS = {
    QAIntent.ATTRIBUTE: [
        r"什么是|是什么|介绍一下|简介|定义|含义",
        r"什么类型|类型是|属于什么|属于哪类|类别",
        r"别名|又叫|又称|也叫|简称|全称",
        r"来源|出自|来自|首次出现在|出处",
        r"属性|特性|特征",
    ],
    QAIntent.RELATION: [
        r"和.*(的)?关系|与.*(的)?关系|之间.*(的)?关系",
        r"和.*有什么关系|与.*有什么关系",
        r"关联|联系",
    ],
    QAIntent.PATH: [
        r"怎么.*关联|怎么.*联系|如何.*关联|如何.*联系",
        r"路径|通路|链条|关系链",
        r"通过.*连接|经过.*关联",
        r"从.*到.*|.*到.*的路径",
    ],
    QAIntent.LIST: [
        r"有哪些|有什么|列出|列举",
        r"相关的.*有哪些|有关的.*有哪些",
        r"关联.*有哪些|联系.*有哪些",
        r"涉及.*哪些|参与.*哪些",
    ],
}

ATTRIBUTE_KEYWORDS = {
    "type": ["类型", "类别", "种类", "属于什么", "是什么类型"],
    "aliases": ["别名", "又叫", "又称", "也叫", "简称", "全称"],
    "first_source": ["来源", "出自", "来自", "首次出现", "出处"],
    "frequency": ["出现次数", "频次", "频率", "多少次"],
}


class QAService:
    _instance: Optional["QAService"] = None

    def __init__(self):
        self.ner = NERPredictor.get_instance()
        self.graph_store = GraphStore.get_instance()

    @classmethod
    def get_instance(cls) -> "QAService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def extract_entities(self, question: str) -> List[str]:
        try:
            entities = self.ner.predict(question)
            entity_texts = [e.text for e in entities]
            unique_entities = []
            seen = set()
            for e in entity_texts:
                if e not in seen and len(e.strip()) > 0:
                    seen.add(e)
                    unique_entities.append(e.strip())
            return unique_entities
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return []

    def classify_intent(self, question: str) -> Tuple[QAIntent, List[str]]:
        scores: Dict[QAIntent, int] = {
            QAIntent.ATTRIBUTE: 0,
            QAIntent.RELATION: 0,
            QAIntent.PATH: 0,
            QAIntent.LIST: 0,
        }

        query_attributes = []

        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, question):
                    scores[intent] += 1

        for attr, keywords in ATTRIBUTE_KEYWORDS.items():
            for kw in keywords:
                if kw in question:
                    scores[QAIntent.ATTRIBUTE] += 1
                    if attr not in query_attributes:
                        query_attributes.append(attr)

        max_score = max(scores.values()) if scores else 0

        if max_score == 0:
            return QAIntent.ATTRIBUTE, []

        best_intent = max(scores, key=scores.get)

        if best_intent == QAIntent.ATTRIBUTE and not query_attributes:
            query_attributes = ["type", "aliases", "first_source"]

        return best_intent, query_attributes

    def parse_question(self, question: str) -> ParsedQuestion:
        entities = self.extract_entities(question)
        intent, query_attrs = self.classify_intent(question)

        if not entities:
            for word in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", question):
                matched = self.graph_store.search_entity(word, limit=1)
                if matched:
                    entities.append(word)
                    break

        return ParsedQuestion(
            original_question=question,
            entities=entities,
            intent=intent,
            query_attributes=query_attrs,
        )

    def fuzzy_match_entity(self, name: str) -> Optional[str]:
        matched = self.graph_store.search_entity(name, limit=5)
        if matched:
            exact_match = [e for e in matched if e.canonical_name == name]
            if exact_match:
                return exact_match[0].canonical_name
            alias_match = [
                e for e in matched if name in (e.aliases or [])
            ]
            if alias_match:
                return alias_match[0].canonical_name
            return matched[0].canonical_name
        return None

    def query_attribute(self, parsed: ParsedQuestion) -> QAResult:
        if not parsed.entities:
            return QAResult(
                answer_text="抱歉，我没有理解您问题中提到的实体，请重新描述。",
                raw_data={},
            )

        entity_name = parsed.entities[0]
        matched_name = self.fuzzy_match_entity(entity_name)

        if not matched_name:
            return QAResult(
                answer_text=f"抱歉，在知识图谱中未找到与「{entity_name}」相关的实体。",
                raw_data={"searched_entity": entity_name},
            )

        entities = self.graph_store.search_entity(matched_name, limit=1)
        if not entities:
            return QAResult(
                answer_text=f"抱歉，在知识图谱中未找到「{matched_name}」的详细信息。",
                raw_data={"searched_entity": matched_name},
            )

        entity = entities[0]
        qa_entity = QAEntity(
            name=entity.canonical_name,
            type=entity.type,
            aliases=entity.aliases,
            first_source=entity.first_source,
            frequency=entity.frequency,
        )

        attrs = parsed.query_attributes or ["type", "aliases", "first_source"]
        parts = []

        if "type" in attrs:
            parts.append(f"{matched_name}是一个{entity.type}类型的实体")
        if "aliases" in attrs and entity.aliases:
            alias_str = "、".join(entity.aliases)
            parts.append(f"别名有{alias_str}")
        if "first_source" in attrs and entity.first_source:
            parts.append(f"首次出现在文档{entity.first_source}中")
        if "frequency" in attrs:
            parts.append(f"共出现{entity.frequency}次")

        if not parts:
            parts = [
                f"{matched_name}是一个{entity.type}类型的实体",
                f"共出现{entity.frequency}次",
            ]

        if entity.aliases and "aliases" not in attrs:
            alias_str = "、".join(entity.aliases)
            parts.append(f"别名有{alias_str}")

        answer = "，".join(parts) + "。"

        return QAResult(
            answer_text=answer,
            entities=[qa_entity],
            raw_data={"entity": entity.model_dump()},
        )

    def query_relation(self, parsed: ParsedQuestion) -> QAResult:
        if len(parsed.entities) < 2:
            return QAResult(
                answer_text="抱歉，我需要两个实体名称来查询它们之间的关系，请您明确说明。",
                raw_data={},
            )

        entity1 = parsed.entities[0]
        entity2 = parsed.entities[1]

        matched1 = self.fuzzy_match_entity(entity1)
        matched2 = self.fuzzy_match_entity(entity2)

        if not matched1 and not matched2:
            return QAResult(
                answer_text=f"抱歉，在知识图谱中未找到「{entity1}」和「{entity2}」相关的实体。",
                raw_data={"searched_entities": [entity1, entity2]},
            )
        if not matched1:
            return QAResult(
                answer_text=f"抱歉，在知识图谱中未找到「{entity1}」相关的实体。",
                raw_data={"searched_entity": entity1},
            )
        if not matched2:
            return QAResult(
                answer_text=f"抱歉，在知识图谱中未找到「{entity2}」相关的实体。",
                raw_data={"searched_entity": entity2},
            )

        rels1 = self.graph_store.get_entity_relations(matched1)
        direct_rels = [
            r for r in rels1
            if r["other_name"] == matched2
        ]

        qa_rels = []
        rel_parts = []

        if direct_rels:
            for r in direct_rels:
                qa_rel = QARelation(
                    head=matched1 if r["direction"] == "out" else matched2,
                    tail=matched2 if r["direction"] == "out" else matched1,
                    relation=r["relation"],
                    confidence=r["confidence"],
                    head_type="",
                    tail_type="",
                )
                qa_rels.append(qa_rel)
                direction = "→" if r["direction"] == "out" else "←"
                rel_parts.append(
                    f"{matched1} {direction}[{r['relation']}（置信度{r['confidence']:.2f}）] {matched2}"
                )
        else:
            paths = self.graph_store.find_shortest_path(matched1, matched2, max_hops=3)
            if paths:
                return self._format_path_result(paths, matched1, matched2, direct=False)
            else:
                return QAResult(
                    answer_text=f"在知识图谱中，{matched1}和{matched2}之间没有直接或间接的关系。",
                    raw_data={"entity1": matched1, "entity2": matched2},
                )

        answer = f"{matched1}和{matched2}之间的关系是：\n" + "\n".join(rel_parts)

        return QAResult(
            answer_text=answer,
            relations=qa_rels,
            raw_data={"relations": direct_rels},
        )

    def _format_path_result(
        self,
        paths: List[Dict[str, Any]],
        entity1: str,
        entity2: str,
        direct: bool = False,
    ) -> QAResult:
        qa_paths = []
        path_parts = []

        for i, path in enumerate(paths, 1):
            qa_path = QAPath(
                node_names=path["node_names"],
                node_types=path["node_types"],
                relation_types=path["relation_types"],
                confidences=path["confidences"],
                path_length=path["path_length"],
            )
            qa_paths.append(qa_path)

            nodes = path["node_names"]
            rels = path["relation_types"]
            confs = path["confidences"]

            path_str = ""
            for j, node in enumerate(nodes):
                path_str += f"「{node}」"
                if j < len(rels):
                    path_str += f" --[{rels[j]}]--> "

            avg_conf = sum(confs) / len(confs) if confs else 0
            path_parts.append(
                f"路径{i}（{path['path_length']}跳，平均置信度{avg_conf:.2f}）：\n  {path_str}"
            )

        if direct:
            prefix = f"{entity1}和{entity2}之间的直接关系路径是：\n"
        else:
            prefix = f"{entity1}和{entity2}之间没有直接关系，但存在间接关联路径：\n"

        answer = prefix + "\n\n".join(path_parts)

        return QAResult(
            answer_text=answer,
            paths=qa_paths,
            raw_data={"paths": paths},
        )

    def query_path(self, parsed: ParsedQuestion) -> QAResult:
        if len(parsed.entities) < 2:
            return QAResult(
                answer_text="抱歉，我需要两个实体名称来查询路径，请您明确说明起始实体和目标实体。",
                raw_data={},
            )

        entity1 = parsed.entities[0]
        entity2 = parsed.entities[1]

        matched1 = self.fuzzy_match_entity(entity1)
        matched2 = self.fuzzy_match_entity(entity2)

        if not matched1 or not matched2:
            missing = []
            if not matched1:
                missing.append(entity1)
            if not matched2:
                missing.append(entity2)
            return QAResult(
                answer_text=f"抱歉，在知识图谱中未找到「{'、'.join(missing)}」相关的实体。",
                raw_data={"searched_entities": [entity1, entity2]},
            )

        paths = self.graph_store.find_shortest_path(matched1, matched2, max_hops=5)

        if not paths:
            return QAResult(
                answer_text=f"在知识图谱中，5跳内未找到从{matched1}到{matched2}的关联路径。",
                raw_data={"entity1": matched1, "entity2": matched2, "max_hops": 5},
            )

        return self._format_path_result(paths, matched1, matched2, direct=False)

    def query_list(self, parsed: ParsedQuestion) -> QAResult:
        if not parsed.entities:
            return QAResult(
                answer_text="抱歉，我没有理解您问题中提到的实体，请重新描述。",
                raw_data={},
            )

        entity_name = parsed.entities[0]
        matched_name = self.fuzzy_match_entity(entity_name)

        if not matched_name:
            return QAResult(
                answer_text=f"抱歉，在知识图谱中未找到与「{entity_name}」相关的实体。",
                raw_data={"searched_entity": entity_name},
            )

        subgraph = self.graph_store.get_subgraph(matched_name, hops=1)
        nodes = subgraph.get("nodes", [])
        edges = subgraph.get("edges", [])

        if len(nodes) <= 1:
            return QAResult(
                answer_text=f"{matched_name}目前没有关联的其他实体。",
                raw_data={"entity": matched_name},
            )

        qa_entities = []
        qa_rels = []
        related_entities = []

        for node in nodes:
            if node["name"] != matched_name:
                qa_entities.append(
                    QAEntity(
                        name=node["name"],
                        type=node.get("type", "UNKNOWN"),
                        aliases=node.get("aliases", []),
                        frequency=node.get("frequency", 1),
                    )
                )
                related_entities.append(node["name"])

        for edge in edges:
            if edge["source"] == matched_name or edge["target"] == matched_name:
                qa_rels.append(
                    QARelation(
                        head=edge["source"],
                        tail=edge["target"],
                        relation=edge["relation"],
                        confidence=edge.get("confidence", 1.0),
                    )
                )

        out_rels = {}
        in_rels = {}
        for rel in qa_rels:
            if rel.head == matched_name:
                out_rels.setdefault(rel.relation, []).append(rel.tail)
            elif rel.tail == matched_name:
                in_rels.setdefault(rel.relation, []).append(rel.head)

        parts = [f"与{matched_name}相关的实体有："]

        if out_rels:
            for rel_type, tails in out_rels.items():
                tail_str = "、".join([f"「{t}」" for t in tails])
                parts.append(f"  • {matched_name} --[{rel_type}]--> {tail_str}")

        if in_rels:
            for rel_type, heads in in_rels.items():
                head_str = "、".join([f"「{h}」" for h in heads])
                parts.append(f"  • {head_str} --[{rel_type}]--> {matched_name}")

        parts.append(f"\n共关联 {len(related_entities)} 个实体。")

        answer = "\n".join(parts)

        return QAResult(
            answer_text=answer,
            entities=qa_entities,
            relations=qa_rels,
            raw_data={"subgraph": subgraph},
        )

    def answer_question(
        self,
        question: str,
        parsed_question: Optional[ParsedQuestion] = None,
    ) -> QAResult:
        if not self.graph_store.is_connected():
            return QAResult(
                answer_text="抱歉，知识图谱服务当前不可用，请稍后再试。",
                raw_data={},
            )

        if parsed_question is not None:
            parsed = parsed_question
        else:
            parsed = self.parse_question(question)

        if not parsed.entities:
            return QAResult(
                answer_text="抱歉，我没有从您的问题中识别出任何实体，请尝试更明确地描述您想查询的内容。",
                raw_data={"parsed": parsed.model_dump()},
            )

        intent_handlers = {
            QAIntent.ATTRIBUTE: self.query_attribute,
            QAIntent.RELATION: self.query_relation,
            QAIntent.PATH: self.query_path,
            QAIntent.LIST: self.query_list,
        }

        handler = intent_handlers.get(parsed.intent, self.query_attribute)
        result = handler(parsed)

        return result
