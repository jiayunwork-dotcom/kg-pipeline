import os
import logging
from typing import Dict, Any, List, Optional

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        try:
            resp = requests.get(f"{self.base_url}{endpoint}", params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"GET {endpoint} failed: {e}")
            return None

    def _post(self, endpoint: str, data: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Any:
        try:
            resp = requests.post(f"{self.base_url}{endpoint}", data=data, json=json_data, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"POST {endpoint} failed: {e}")
            return None

    def _post_multipart(self, endpoint: str, data: Optional[Dict] = None, files: Optional[List] = None) -> Any:
        try:
            resp = requests.post(f"{self.base_url}{endpoint}", data=data, files=files, timeout=120)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"POST multipart {endpoint} failed: {e}")
            return None

    def health_check(self) -> bool:
        result = self._get("/health")
        return result is not None

    def create_task_text(self, text: str, custom_dict_csv: Optional[str] = None) -> Optional[Dict]:
        data = {
            "source_type": "text",
            "text": text,
        }
        if custom_dict_csv:
            data["custom_dict_csv"] = custom_dict_csv
        return self._post("/api/tasks/json", json_data=data)

    def create_task_urls(self, urls: List[str], custom_dict_csv: Optional[str] = None) -> Optional[Dict]:
        data = {
            "source_type": "url",
            "urls": urls,
        }
        if custom_dict_csv:
            data["custom_dict_csv"] = custom_dict_csv
        return self._post("/api/tasks/json", json_data=data)

    def create_task_files(self, file_tuples: List, custom_dict_csv: Optional[str] = None) -> Optional[Dict]:
        data = {"source_type": "file"}
        files = []
        for name, content_bytes, mime in file_tuples:
            files.append(("files", (name, content_bytes, mime)))
        if custom_dict_csv:
            import io
            files.append(("custom_dict", ("custom_dict.csv", custom_dict_csv.encode("utf-8"), "text/csv")))
        return self._post_multipart("/api/tasks", data=data, files=files)

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        return self._get(f"/api/tasks/{task_id}")

    def list_tasks(self, limit: int = 50) -> List[Dict]:
        result = self._get("/api/tasks", params={"limit": limit})
        return result or []

    def retry_task(self, task_id: str) -> Optional[Dict]:
        return self._post(f"/api/tasks/{task_id}/retry")

    def get_graph_stats(self) -> Optional[Dict]:
        return self._get("/api/graph/stats")

    def search_entities(self, name: str, limit: int = 20) -> List[Dict]:
        result = self._get("/api/graph/entities/search", params={"name": name, "limit": limit})
        return result or []

    def get_entity_details(self, name: str) -> Optional[Dict]:
        return self._get(f"/api/graph/entities/{name}")

    def get_subgraph(self, name: str, hops: int = 2, min_confidence: float = 0.0) -> Optional[Dict]:
        params = {"hops": hops, "min_confidence": min_confidence}
        return self._get(f"/api/graph/subgraph/{name}", params=params)

    def find_path(self, entity1: str, entity2: str, max_hops: int = 5) -> List[Dict]:
        params = {"entity1": entity1, "entity2": entity2, "max_hops": max_hops}
        result = self._get("/api/graph/path", params=params)
        return result or []

    def get_all_graph_data(self, min_confidence: float = 0.0, max_nodes: int = 500) -> Optional[Dict]:
        params = {"min_confidence": min_confidence, "max_nodes": max_nodes}
        return self._get("/api/graph/data", params=params)

    def generate_quality_sample(self, count: int = 100) -> List[Dict]:
        result = self._get("/api/quality/sample", params={"count": count})
        return result.get("triples", []) if result else []

    def submit_evaluation(self, labels: Dict[str, bool]) -> Optional[Dict]:
        return self._post("/api/quality/evaluate", json_data=labels)

    def get_quality_history(self, limit: int = 5) -> List[Dict]:
        result = self._get("/api/quality/history", params={"limit": limit})
        return result.get("evaluations", []) if result else []

    def get_quality_trend(self, limit: int = 5) -> Optional[Dict]:
        return self._get("/api/quality/trend", params={"limit": limit})


client = APIClient()
