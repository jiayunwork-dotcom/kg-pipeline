import re
import logging
from typing import List, Dict, Optional, Set, Tuple
from collections import defaultdict

from src.models.schemas import Entity, EntityNode

logger = logging.getLogger(__name__)

NORMALIZE_RULES = [
    (r"[（(].*?[)）]", ""),
    (r"[\s\-_·•.・]", ""),
    (r"[《》<>「」『』\"'“”‘’]", ""),
    (r"有限公司|有限责任公司|股份有限公司|集团|公司", ""),
    (r"大学|学院|研究院|研究所|中心", ""),
]


class EntityFusion:
    _instance: Optional["EntityFusion"] = None

    def __init__(self):
        self._embedder = None
        self._try_load_embedder()
        self._node_index: Dict[str, EntityNode] = {}
        self._normalized_index: Dict[str, List[str]] = defaultdict(list)

    @classmethod
    def get_instance(cls) -> "EntityFusion":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _try_load_embedder(self):
        try:
            from sentence_transformers import SentenceTransformer
            from src.config import settings

            self._embedder = SentenceTransformer(
                settings.SENTENCE_MODEL_NAME,
                cache_folder=settings.MODEL_CACHE_DIR,
            )
            logger.info("Sentence embedder loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load sentence embedder: {e}")
            self._embedder = None

    @staticmethod
    def normalize_name(name: str) -> str:
        if not name:
            return ""
        normalized = name.lower().strip()
        for pattern, replacement in NORMALIZE_RULES:
            normalized = re.sub(pattern, replacement, normalized)
        return normalized.strip()

    @staticmethod
    def normalized_edit_distance(s1: str, s2: str) -> float:
        n1, n2 = EntityFusion.normalize_name(s1), EntityFusion.normalize_name(s2)
        if not n1 or not n2:
            return 1.0
        if n1 == n2:
            return 0.0
        len1, len2 = len(n1), len(n2)
        if len1 == 0 or len2 == 0:
            return 1.0
        dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
        for i in range(len1 + 1):
            dp[i][0] = i
        for j in range(len2 + 1):
            dp[0][j] = j
        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                if n1[i - 1] == n2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
        max_len = max(len1, len2)
        return dp[len1][len2] / max_len if max_len > 0 else 1.0

    def _semantic_similarity(self, text1: str, text2: str) -> float:
        if self._embedder is None:
            return 0.0
        try:
            import numpy as np

            embeddings = self._embedder.encode([text1, text2])
            e1, e2 = embeddings[0], embeddings[1]
            norm1, norm2 = np.linalg.norm(e1), np.linalg.norm(e2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(np.dot(e1, e2) / (norm1 * norm2))
        except Exception as e:
            logger.error(f"Semantic similarity computation failed: {e}")
            return 0.0

    def set_existing_nodes(self, nodes: List[EntityNode]):
        self._node_index = {}
        self._normalized_index = defaultdict(list)
        for node in nodes:
            self._node_index[node.canonical_name] = node
            norm = self.normalize_name(node.canonical_name)
            if norm:
                self._normalized_index[norm].append(node.canonical_name)
            for alias in node.aliases:
                alias_norm = self.normalize_name(alias)
                if alias_norm:
                    self._normalized_index[alias_norm].append(node.canonical_name)

    def find_match(
        self,
        entity: Entity,
        context: str = "",
    ) -> Optional[str]:
        if entity.text in self._node_index:
            return entity.text

        norm_text = self.normalize_name(entity.text)
        if not norm_text:
            return None

        if norm_text in self._normalized_index:
            candidates = self._normalized_index[norm_text]
            if candidates:
                return candidates[0]

        edit_candidates: List[Tuple[str, float]] = []
        for norm_name, canonicals in self._normalized_index.items():
            dist = self.normalized_edit_distance(norm_text, norm_name)
            if dist < 0.3:
                for c in canonicals:
                    edit_candidates.append((c, dist))

        if not edit_candidates:
            return None

        edit_candidates.sort(key=lambda x: x[1])

        if self._embedder and context:
            best_candidate = None
            best_sim = 0.0
            for candidate, _ in edit_candidates[:5]:
                node = self._node_index.get(candidate)
                if node is None:
                    continue
                node_context = " ".join([node.canonical_name] + node.aliases)
                sim = self._semantic_similarity(context, node_context)
                if sim > best_sim and sim >= 0.85:
                    best_sim = sim
                    best_candidate = candidate
            return best_candidate

        return edit_candidates[0][0]

    def add_or_merge(
        self,
        entity: Entity,
        source_doc: str,
        context: str = "",
    ) -> EntityNode:
        matched = self.find_match(entity, context)

        if matched is not None and matched in self._node_index:
            node = self._node_index[matched]
            node.frequency += 1
            if entity.text not in node.aliases and entity.text != node.canonical_name:
                node.aliases.append(entity.text)
                norm = self.normalize_name(entity.text)
                if norm:
                    self._normalized_index[norm].append(node.canonical_name)
            return node

        canonical_name = entity.text
        node = EntityNode(
            canonical_name=canonical_name,
            aliases=[],
            type=entity.type,
            first_source=source_doc,
            frequency=1,
        )
        self._node_index[canonical_name] = node
        norm = self.normalize_name(canonical_name)
        if norm:
            self._normalized_index[norm].append(canonical_name)
        return node

    def resolve_entities(
        self,
        entities: List[Entity],
        source_doc: str,
        sentence_context: str = "",
    ) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for entity in entities:
            resolved = self.add_or_merge(entity, source_doc, sentence_context)
            mapping[entity.text] = resolved.canonical_name
        return mapping
