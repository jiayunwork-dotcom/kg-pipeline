import re
import logging
from typing import List, Optional, Tuple
from itertools import combinations

from src.models.schemas import Entity, Relation, RELATION_TYPES
from src.config import settings

logger = logging.getLogger(__name__)


class VerbPattern:
    def __init__(
        self,
        relation: str,
        verbs: List[str],
        prepositions: List[str] = None,
        passive: bool = True,
        head_first: bool = True,
        base_score: float = 0.85,
        head_types: Optional[List[str]] = None,
        tail_types: Optional[List[str]] = None,
    ):
        self.relation = relation
        self.verbs = verbs
        self.prepositions = prepositions or [""]
        self.passive = passive
        self.head_first = head_first
        self.base_score = base_score
        self.head_types = head_types
        self.tail_types = tail_types

    def is_type_allowed(self, head_type: str, tail_type: str) -> bool:
        if self.head_types and head_type not in self.head_types:
            return False
        if self.tail_types and tail_type not in self.tail_types:
            return False
        return True


VERB_PATTERNS: List[VerbPattern] = [
    VerbPattern(
        relation="创建了",
        verbs=[
            "创立", "创建", "建立", "成立", "创办", "发起", "组建", "缔造",
            "开设", "设立", "推出", "发布", "开发", "发明", "设计",
            "made", "founded", "created", "established", "launched",
        ],
        prepositions=["", "了", "出", "过"],
        head_first=True,
        base_score=0.92,
        head_types=["PER", "ORG"],
        tail_types=["ORG", "WORK", "EVENT", "PRODUCT", "TECH"],
    ),
    VerbPattern(
        relation="创建了",
        verbs=[
            "由...创立", "由...创建", "由...建立", "由...成立", "由...创办",
            "由...发起", "由...组建", "由...缔造", "由...推出", "由...发布",
        ],
        head_first=False,
        base_score=0.90,
        head_types=["PER", "ORG"],
        tail_types=["ORG", "WORK", "EVENT", "PRODUCT", "TECH"],
    ),
    VerbPattern(
        relation="隶属于",
        verbs=[
            "隶属于", "属于", "归属于", "归属", "从属", "附属于",
            "是...的子公司", "是...的分公司", "是...的分支机构", "是...的一部分",
            "是...的成员", "是...旗下", "为...下属",
        ],
        head_first=True,
        base_score=0.88,
        head_types=["ORG", "WORK", "PER", "TECH", "PRODUCT"],
        tail_types=["ORG", "TECH", "WORK"],
    ),
    VerbPattern(
        relation="位于",
        verbs=[
            "位于", "坐落于", "地处", "处在", "坐落在", "地处",
            "在...举办", "在...设立", "在...成立",
            "总部位于", "总部设在", "总部在",
            "座落于", "位于...境内", "位于...地区",
        ],
        head_first=True,
        base_score=0.90,
        head_types=["ORG", "PER", "EVENT", "WORK", "PRODUCT"],
        tail_types=["LOC", "GPE"],
    ),
    VerbPattern(
        relation="发生在",
        verbs=[
            "发生在", "发生于", "举行于", "举行在", "举办于", "举办在",
            "召开于", "召开在", "进行于", "进行在",
            "于...举行", "于...举办", "于...召开", "在...举行",
            "爆发于", "爆发在",
        ],
        head_first=True,
        base_score=0.86,
        head_types=["EVENT", "TIME"],
        tail_types=["LOC", "GPE", "TIME"],
    ),
    VerbPattern(
        relation="参与了",
        verbs=[
            "参与了", "参加了", "出席了", "加入了", "投身于",
            "任职于", "就任于", "担任", "出任",
            "在...担任", "在...任职", "在...工作",
            "参与", "参加", "出席", "加入",
        ],
        head_first=True,
        base_score=0.85,
        head_types=["PER", "ORG"],
        tail_types=["ORG", "EVENT", "WORK"],
    ),
    VerbPattern(
        relation="合作关系",
        verbs=[
            "与...合作", "和...合作", "同...合作", "与...战略合作",
            "与...签署", "与...达成合作", "与...建立合作",
            "合作开发", "联合开发", "联合打造", "共同开发",
            "合作伙伴", "达成战略合作",
        ],
        head_first=True,
        base_score=0.82,
        head_types=["ORG", "PER"],
        tail_types=["ORG", "PER"],
    ),
    VerbPattern(
        relation="竞争关系",
        verbs=[
            "与...竞争", "和...竞争", "同...竞争", "与...抗衡",
            "与...争夺", "竞争对手", "竞品", "竞争关系",
            "角逐", "较量", "争夺市场",
        ],
        head_first=True,
        base_score=0.82,
        head_types=["ORG", "PER"],
        tail_types=["ORG", "PER"],
    ),
    VerbPattern(
        relation="子类关系",
        verbs=[
            "是一种", "是一类", "是...的一种", "是...的一类",
            "属于...类型", "归为...类", "归类为",
            "是...的子类", "继承自", "继承了",
            "本质上是", "实质上是",
        ],
        head_first=True,
        base_score=0.84,
        head_types=["TECH", "WORK", "PRODUCT", "ORG"],
        tail_types=["TECH", "WORK", "ORG"],
    ),
]

FALLBACK_KEYWORDS = {
    "隶属于": ["隶属", "旗下", "子公司", "分公司", "下属", "分支"],
    "位于": ["总部", "地址", "座落", "坐落", "地处", "境内", "位于"],
    "创建了": ["创立", "创建", "成立", "创办", "发起", "推出", "发布"],
    "参与了": ["出席", "参加", "参与", "加入", "任职", "担任", "就任"],
    "发生在": ["举行", "举办", "召开", "发生", "爆发", "进行"],
    "合作关系": ["合作", "联合", "共同", "伙伴", "战略", "签署"],
    "竞争关系": ["竞争", "对手", "抗衡", "争夺", "角逐", "竞品"],
    "子类关系": ["一种", "一类", "类型", "本质", "归类", "属于"],
}


class REPredictor:
    _instance: Optional["REPredictor"] = None

    def __init__(self):
        self._model_loaded = False
        self._tokenizer = None
        self._model = None
        self._try_load_model()

    @classmethod
    def get_instance(cls) -> "REPredictor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _try_load_model(self):
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            from src.config import settings

            self._tokenizer = AutoTokenizer.from_pretrained(
                settings.RE_MODEL_NAME,
                cache_dir=settings.MODEL_CACHE_DIR,
            )
            self._model_loaded = True
            logger.info("RE model components loaded")
        except Exception as e:
            logger.warning(f"Failed to load RE model, using rule-based engine: {e}")
            self._model_loaded = False

    @staticmethod
    def _escape(text: str) -> str:
        return re.escape(text)

    def _match_verb_pattern(
        self,
        sentence: str,
        ordered_head: Entity,
        ordered_tail: Entity,
    ) -> Tuple[Optional[str], float, Optional[Entity], Optional[Entity]]:
        head_idx = sentence.find(ordered_head.text)
        tail_idx = sentence.find(ordered_tail.text)

        if head_idx == -1 or tail_idx == -1:
            return None, 0.0, None, None

        if head_idx < tail_idx:
            e1_start, e1_end = head_idx, head_idx + len(ordered_head.text)
            e2_start, e2_end = tail_idx, tail_idx + len(ordered_tail.text)
            e1_entity = ordered_head
            e2_entity = ordered_tail
        else:
            e1_start, e1_end = tail_idx, tail_idx + len(ordered_tail.text)
            e2_start, e2_end = head_idx, head_idx + len(ordered_head.text)
            e1_entity = ordered_tail
            e2_entity = ordered_head

        middle_text = sentence[e1_end:e2_start]
        total_text = sentence


        if len(middle_text) > 120:
            return None, 0.0, None, None

        best_relation = None
        best_score = 0.0
        best_head: Optional[Entity] = None
        best_tail: Optional[Entity] = None

        for pattern in VERB_PATTERNS:
            matched = False
            matched_score = 0.0

            for verb in pattern.verbs:
                if "..." in verb:
                    parts = verb.split("...")
                    if len(parts) == 2:
                        before_pat = self._escape(parts[0])
                        after_pat = self._escape(parts[1])

                        regex = before_pat + r".{0,30}" + after_pat
                        if re.search(regex, total_text):
                            matched = True
                            matched_score = pattern.base_score

                            if len(middle_text) < 20:
                                matched_score += 0.05
                            elif len(middle_text) < 50:
                                matched_score += 0.02

                            break
                else:
                    for prep in pattern.prepositions:
                        target_verb = verb + prep
                        if target_verb in middle_text or target_verb in total_text:
                            matched = True
                            matched_score = pattern.base_score

                            if len(middle_text) < 20:
                                matched_score += 0.05
                            elif len(middle_text) < 50:
                                matched_score += 0.02

                            if len(target_verb) <= 4 and len(middle_text) < 15:
                                matched_score += 0.02

                            break
                    if matched:
                        break

            if matched and matched_score > best_score:
                if pattern.head_first:
                    candidate_head_type = e1_entity.type
                    candidate_tail_type = e2_entity.type
                else:
                    candidate_head_type = e2_entity.type
                    candidate_tail_type = e1_entity.type

                if not pattern.is_type_allowed(candidate_head_type, candidate_tail_type):
                    continue

                if pattern.head_first:
                    result_head = e1_entity
                    result_tail = e2_entity
                else:
                    result_head = e2_entity
                    result_tail = e1_entity

                best_relation = pattern.relation
                best_score = matched_score
                best_head = result_head
                best_tail = result_tail

        if best_score == 0.0:
            for relation, keywords in FALLBACK_KEYWORDS.items():
                for kw in keywords:
                    if kw in middle_text:
                        score = 0.68
                        if len(middle_text) < 25:
                            score += 0.05
                        if len(kw) >= 3:
                            score += 0.02
                        if score > best_score:
                            directional_rels = {"创建了", "参与了", "发生在", "位于", "隶属于"}
                            if relation in directional_rels:
                                result_head = e1_entity
                                result_tail = e2_entity
                            else:
                                result_head = e1_entity
                                result_tail = e2_entity

                            best_relation = relation
                            best_score = score
                            best_head = result_head
                            best_tail = result_tail
                        break

        return best_relation, min(0.98, best_score), best_head, best_tail

    def _keyword_based_predict(
        self,
        sentence: str,
        head: Entity,
        tail: Entity,
    ) -> Tuple[str, float, Optional[Entity], Optional[Entity]]:
        relation, score, res_head, res_tail = self._match_verb_pattern(sentence, head, tail)
        if relation is not None and score > 0:
            return relation, score, res_head, res_tail

        head_idx = sentence.find(head.text)
        tail_idx = sentence.find(tail.text)
        if head_idx != -1 and tail_idx != -1:
            distance = abs(tail_idx - head_idx)

            type_combo_rules = {
                ("PER", "ORG"): ("创建了", 0.55),
                ("ORG", "LOC"): ("位于", 0.58),
                ("PER", "LOC"): ("位于", 0.52),
                ("EVENT", "LOC"): ("发生在", 0.60),
                ("EVENT", "TIME"): ("发生在", 0.60),
                ("PER", "EVENT"): ("参与了", 0.55),
                ("PER", "WORK"): ("创建了", 0.58),
                ("ORG", "ORG"): ("合作关系", 0.50),
                ("WORK", "TECH"): ("子类关系", 0.55),
            }
            key = (head.type, tail.type)
            reverse_key = (tail.type, head.type)
            if key in type_combo_rules and distance < 50:
                rel, base = type_combo_rules[key]
                adjusted = base + max(0, 0.08 - distance / 800)
                return rel, adjusted, head, tail
            elif reverse_key in type_combo_rules and distance < 50:
                rel, base = type_combo_rules[reverse_key]
                adjusted = base + max(0, 0.08 - distance / 800)
                return rel, adjusted, tail, head

        return "无关系", 0.0, None, None

    def _model_based_predict(
        self,
        sentence: str,
        head: Entity,
        tail: Entity,
    ) -> Tuple[str, float, Optional[Entity], Optional[Entity]]:
        if not self._model_loaded:
            return self._keyword_based_predict(sentence, head, tail)

        try:
            return self._keyword_based_predict(sentence, head, tail)
        except Exception as e:
            logger.error(f"Model-based RE prediction failed: {e}")
            return self._keyword_based_predict(sentence, head, tail)

    def _order_entities(self, head: Entity, tail: Entity) -> Tuple[Entity, Entity]:
        if head.start <= tail.start:
            return head, tail
        return tail, head

    def predict_pair(
        self,
        sentence: str,
        head: Entity,
        tail: Entity,
    ) -> Optional[Relation]:
        if head.text == tail.text:
            return None

        ordered_head, ordered_tail = self._order_entities(head, tail)

        relation, confidence, res_head, res_tail = self._model_based_predict(
            sentence, ordered_head, ordered_tail
        )

        if res_head is not None and res_tail is not None:
            final_head = res_head
            final_tail = res_tail
        else:
            final_head = ordered_head
            final_tail = ordered_tail

        if relation == "无关系":
            return Relation(
                head_text=final_head.text,
                head_type=final_head.type,
                tail_text=final_tail.text,
                tail_type=final_tail.type,
                relation=relation,
                confidence=confidence,
                sentence=sentence,
                need_manual_confirm=False,
            )

        need_confirm = confidence < settings.CONFIDENCE_THRESHOLD

        return Relation(
            head_text=final_head.text,
            head_type=final_head.type,
            tail_text=final_tail.text,
            tail_type=final_tail.type,
            relation=relation,
            confidence=round(float(confidence), 4),
            sentence=sentence,
            need_manual_confirm=need_confirm,
        )

    def predict_sentence(
        self,
        sentence: str,
        entities: List[Entity],
    ) -> List[Relation]:
        if not entities or len(entities) < 2:
            return []

        relations: List[Relation] = []

        for head, tail in combinations(entities, 2):
            rel = self.predict_pair(sentence, head, tail)
            if rel is not None:
                relations.append(rel)

        return relations

    def predict_all(
        self,
        sentence_entity_pairs: List[Tuple[str, List[Entity]]],
    ) -> List[Relation]:
        all_relations: List[Relation] = []

        for sentence, entities in sentence_entity_pairs:
            if not sentence or not entities:
                continue
            rels = self.predict_sentence(sentence, entities)
            all_relations.extend(rels)

        return all_relations
