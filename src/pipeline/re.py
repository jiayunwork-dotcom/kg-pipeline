import re
import logging
from typing import List, Optional, Tuple
from itertools import combinations

import numpy as np

from src.models.schemas import Entity, Relation, RELATION_TYPES
from src.config import settings

logger = logging.getLogger(__name__)

RELATION_KEYWORDS = {
    "隶属于": [
        "隶属于", "属于", "归属于", "是...的一部分", "为...下属", "旗下",
        "是...的子公司", "是...的分公司", "是...的成员", "归属",
    ],
    "位于": [
        "位于", "坐落于", "地处", "在...", "坐落在", "处在",
        "位于...境内", "地处...地区",
    ],
    "创建了": [
        "创建了", "创立了", "成立了", "建立了", "创办了", "发起了",
        "由...创建", "由...创立", "由...创办", "由...成立",
    ],
    "参与了": [
        "参与了", "参加了", "出席了", "加入了", "投身于",
        "在...中担任", "任职于",
    ],
    "发生在": [
        "发生在", "举行于", "举办于", "召开于", "进行于",
        "于...发生", "在...举行",
    ],
    "合作关系": [
        "与...合作", "和...合作", "同...合作", "战略合作",
        "合作伙伴", "合作开发", "联合",
    ],
    "竞争关系": [
        "与...竞争", "和...竞争", "竞争对手", "竞争关系",
        "争夺", "抗衡",
    ],
    "子类关系": [
        "是一种", "是一类", "属于...类型", "为...的一种",
        "是...的子类", "继承自",
    ],
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
            logger.warning(f"Failed to load RE model, using keyword-based fallback: {e}")
            self._model_loaded = False

    def _keyword_based_predict(
        self,
        sentence: str,
        head: Entity,
        tail: Entity,
    ) -> Tuple[str, float]:
        best_relation = "无关系"
        best_score = 0.0

        for relation, keywords in RELATION_KEYWORDS.items():
            for kw in keywords:
                if "..." in kw:
                    parts = kw.split("...")
                    if len(parts) == 2:
                        pattern = re.escape(parts[0]) + r".{0,30}" + re.escape(parts[1])
                        if re.search(pattern, sentence):
                            score = 0.7
                            if score > best_score:
                                best_score = score
                                best_relation = relation
                else:
                    if kw in sentence:
                        score = 0.65
                        if score > best_score:
                            best_score = score
                            best_relation = relation

        head_idx = sentence.find(head.text)
        tail_idx = sentence.find(tail.text)
        if head_idx != -1 and tail_idx != -1:
            distance = abs(tail_idx - head_idx)
            if distance < 30 and best_relation != "无关系":
                best_score = min(1.0, best_score + 0.1)

        return best_relation, best_score

    def _model_based_predict(
        self,
        sentence: str,
        head: Entity,
        tail: Entity,
    ) -> Tuple[str, float]:
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

        relation, confidence = self._model_based_predict(
            sentence, ordered_head, ordered_tail
        )

        if relation == "无关系":
            return Relation(
                head_text=ordered_head.text,
                head_type=ordered_head.type,
                tail_text=ordered_tail.text,
                tail_type=ordered_tail.type,
                relation=relation,
                confidence=confidence,
                sentence=sentence,
                need_manual_confirm=False,
            )

        need_confirm = confidence < settings.CONFIDENCE_THRESHOLD

        return Relation(
            head_text=ordered_head.text,
            head_type=ordered_head.type,
            tail_text=ordered_tail.text,
            tail_type=ordered_tail.type,
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
