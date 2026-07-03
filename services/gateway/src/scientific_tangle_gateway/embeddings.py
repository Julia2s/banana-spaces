"""Embeddings provider.

Два бэкенда:
1. sentence-transformers (по умолчанию, локально, бесплатно).
   Модель LaBSE — мультиязычная, хорошо работает для рус+англ.
2. Yandex embeddings (если GATEWAY_EMBEDDINGS_BACKEND=yandex).

Все модели кэшируются в памяти процесса. Для больших корпусов используйте Qdrant.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from scientific_tangle_gateway.config import settings
from scientific_tangle_gateway.yandex_client import YandexClient

logger = logging.getLogger(__name__)


class EmbeddingsProvider:
    def __init__(self, backend: str | None = None) -> None:
        self.backend = backend or settings.embeddings_backend
        self._st_model: Any = None
        self._yandex: YandexClient | None = None
        self._vector_dim: int | None = None

    @property
    def vector_dim(self) -> int:
        if self._vector_dim is None:
            self._ensure_loaded()
        return self._vector_dim or 768

    def _ensure_loaded(self) -> None:
        if self.backend == "yandex":
            self._yandex = YandexClient()
            if self._yandex.is_configured:
                self._vector_dim = 768
            else:
                logger.warning("Yandex embeddings не настроены, fallback на sentence-transformers")
                self.backend = "sentence-transformers"

        if self.backend == "sentence-transformers":
            try:
                from sentence_transformers import SentenceTransformer
                self._st_model = SentenceTransformer(settings.embeddings_model_name)
                self._vector_dim = self._st_model.get_sentence_embedding_dimension()
            except ImportError:
                logger.warning("sentence-transformers не установлен, fallback на hashing")
                self.backend = "hashing"
                self._vector_dim = 256
            except Exception as error:
                logger.warning("Ошибка загрузки sentence-transformers: %s, fallback на hashing", error)
                self.backend = "hashing"
                self._vector_dim = 256

        if self.backend == "hashing":
            self._vector_dim = 256

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_loaded()

        if self.backend == "sentence-transformers" and self._st_model is not None:
            try:
                vectors = self._st_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                return [list(map(float, v)) for v in vectors]
            except Exception as error:
                logger.warning("ST encode failed: %s, fallback на hashing", error)
                return self._hash_embed(texts)

        if self.backend == "yandex" and self._yandex is not None and self._yandex.is_configured:
            try:
                return self._yandex.embed_texts(texts)
            except Exception as error:
                logger.warning("Yandex embeddings failed: %s, fallback на hashing", error)
                return self._hash_embed(texts)

        return self._hash_embed(texts)

    def embed_one(self, text: str) -> list[float]:
        result = self.embed([text])
        return result[0] if result else [0.0] * self.vector_dim

    def _hash_embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib
        dim = 256
        result = []
        for text in texts:
            vec = [0.0] * dim
            for token in text.lower().split():
                h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
                vec[h % dim] += 1.0
            norm = float(np.linalg.norm(vec)) or 1.0
            result.append([v / norm for v in vec])
        return result
