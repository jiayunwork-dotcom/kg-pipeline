import re
import logging
import csv
import io
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from src.models.schemas import Entity, ENTITY_TYPES

logger = logging.getLogger(__name__)

ENTITY_TYPE_CN_MAP = {
    "PER": ["人名", "姓名", "人物", "个人"],
    "ORG": ["组织机构", "组织", "机构", "公司", "企业", "集团", "政府", "部门"],
    "LOC": ["地点", "地名", "地方", "城市", "国家", "地区", "地址"],
    "TIME": ["时间", "日期", "年份", "年代", "时期"],
    "EVENT": ["事件", "活动", "会议", "运动", "事故"],
    "WORK": ["作品", "著作", "书籍", "电影", "音乐", "文章", "报告"],
    "TECH": ["技术", "术语", "方法", "算法", "系统", "框架", "模型"],
}

CHINESE_NAME_PATTERN = re.compile(r"[\u4e00-\u9fa5]{2,4}(?:·[\u4e00-\u9fa5]{2,4})*")
ORG_PATTERN = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9]+?(?:公司|集团|有限|股份|科技|大学|学院|研究院|研究所|中心|协会|委员会|部|局|厅|处|队|银行|医院|学校|工厂)"
)
TIME_PATTERN = re.compile(
    r"(?:(?:19|20)\d{2}[-/.年](?:0?[1-9]|1[0-2])[-/.月](?:0?[1-9]|[12]\d|3[01])日?)|"
    r"(?:19|20)\d{2}年?|"
    r"(?:20\d{2}|19\d{2})[-/.年](?:0?[1-9]|1[0-2])月?|"
    r"(?:\d{1,2})[点时](?:\d{1,2})?分?|"
    r"(?:去年|今年|明年|昨天|今天|明天|后天|前天|上周|本周|下周|上月|本月|下月)"
)
URL_PATTERN = re.compile(r"https?://[^\s]+")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class CustomDictionary:
    entities: Dict[str, str]

    @classmethod
    def from_csv(cls, csv_content: str) -> "CustomDictionary":
        entities: Dict[str, str] = {}
        try:
            reader = csv.reader(io.StringIO(csv_content))
            for row in reader:
                if len(row) >= 2:
                    name = row[0].strip()
                    etype = row[1].strip().upper()
                    if name and etype in ENTITY_TYPES:
                        entities[name] = etype
        except Exception as e:
            logger.warning(f"Failed to parse custom dictionary CSV: {e}")
        return cls(entities=entities)

    def match(self, text: str) -> List[Entity]:
        results: List[Entity] = []
        for name, etype in self.entities.items():
            start = 0
            while True:
                pos = text.find(name, start)
                if pos == -1:
                    break
                results.append(
                    Entity(
                        text=name,
                        type=etype,
                        start=pos,
                        end=pos + len(name),
                        confidence=1.0,
                        source="dictionary",
                    )
                )
                start = pos + len(name)
        return results


class NERPredictor:
    _instance: Optional["NERPredictor"] = None

    def __init__(self):
        self._model_loaded = False
        self._tokenizer = None
        self._model = None
        self._try_load_model()

    @classmethod
    def get_instance(cls) -> "NERPredictor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _try_load_model(self):
        try:
            from transformers import AutoTokenizer, AutoModelForTokenClassification
            from src.config import settings

            self._tokenizer = AutoTokenizer.from_pretrained(
                settings.NER_MODEL_NAME,
                cache_dir=settings.MODEL_CACHE_DIR,
            )
            self._model = AutoModelForTokenClassification.from_pretrained(
                settings.NER_MODEL_NAME,
                cache_dir=settings.MODEL_CACHE_DIR,
            )
            self._model_loaded = True
            logger.info("NER model loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load NER model, using rule-based fallback: {e}")
            self._model_loaded = False

    def _rule_based_predict(self, text: str) -> List[Entity]:
        entities: List[Entity] = []

        for match in TIME_PATTERN.finditer(text):
            entities.append(
                Entity(
                    text=match.group(),
                    type="TIME",
                    start=match.start(),
                    end=match.end(),
                    confidence=0.85,
                    source="rule",
                )
            )

        for match in ORG_PATTERN.finditer(text):
            entities.append(
                Entity(
                    text=match.group(),
                    type="ORG",
                    start=match.start(),
                    end=match.end(),
                    confidence=0.7,
                    source="rule",
                )
            )

        entities = self._deduplicate_entities(entities)
        return entities

    def _model_based_predict(self, text: str) -> List[Entity]:
        if not self._model_loaded:
            return self._rule_based_predict(text)

        try:
            import torch

            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                return_offsets_mapping=True,
            )
            offset_mapping = inputs.pop("offset_mapping")[0]

            with torch.no_grad():
                outputs = self._model(**inputs)

            predictions = torch.argmax(outputs.logits, dim=-1)[0].tolist()
            id2label = getattr(self._model.config, "id2label", {})

            entities: List[Entity] = []
            current_entity = None
            current_start = None

            for idx, (pred_id, (start, end)) in enumerate(zip(predictions, offset_mapping)):
                if start == end:
                    continue
                label = id2label.get(pred_id, "O")
                bio_tag = label[0] if len(label) > 1 else "O"
                etype = label[2:] if len(label) > 2 else label

                if bio_tag == "B" and etype in ENTITY_TYPES:
                    if current_entity is not None and current_start is not None:
                        entities.append(current_entity)
                    current_start = start
                    current_entity = Entity(
                        text=text[start:end],
                        type=etype,
                        start=start,
                        end=end,
                        confidence=0.9,
                        source="model",
                    )
                elif bio_tag == "I" and current_entity is not None and etype == current_entity.type:
                    current_entity.end = end
                    current_entity.text = text[current_start:end]
                else:
                    if current_entity is not None and current_start is not None:
                        entities.append(current_entity)
                    current_entity = None
                    current_start = None

            if current_entity is not None and current_start is not None:
                entities.append(current_entity)

            return entities

        except Exception as e:
            logger.error(f"Model-based NER prediction failed, falling back to rules: {e}")
            return self._rule_based_predict(text)

    def _deduplicate_entities(self, entities: List[Entity]) -> List[Entity]:
        entities.sort(key=lambda e: (e.start, -(e.end - e.start)))
        merged: List[Entity] = []
        for ent in entities:
            if not merged:
                merged.append(ent)
                continue
            last = merged[-1]
            if ent.start < last.end:
                if (ent.end - ent.start) > (last.end - last.start):
                    merged[-1] = ent
                continue
            merged.append(ent)
        return merged

    def predict(
        self,
        text: str,
        custom_dict: Optional[CustomDictionary] = None,
    ) -> List[Entity]:
        if not text or not text.strip():
            return []

        dict_entities: List[Entity] = []
        if custom_dict is not None:
            dict_entities = custom_dict.match(text)

        model_entities = self._model_based_predict(text)

        all_entities = dict_entities + model_entities
        all_entities = self._deduplicate_entities(all_entities)

        all_entities = [
            e for e in all_entities
            if e.text.strip() and len(e.text.strip()) >= 1
        ]

        return all_entities

    def predict_sentences(
        self,
        sentences: List[str],
        custom_dict: Optional[CustomDictionary] = None,
    ) -> List[Tuple[str, List[Entity]]]:
        results = []
        offset = 0
        for sent in sentences:
            entities = self.predict(sent, custom_dict)
            for e in entities:
                e.start += offset
                e.end += offset
            results.append((sent, entities))
            offset += len(sent) + 1
        return results
