"""YandexGPT AI Studio client.

Обёртка над REST API YandexGPT для трёх задач:
1. Chat completion — answer synthesis, extraction
2. Embeddings — векторизация чанков и запросов (если включён backend=yandex)
3. Embeddings text-search — пары query/doc для retrieval

API-ключи НЕ запрашиваются у пользователя. Они читаются из .env:
- GATEWAY_YANDEX_FOLDER_ID
- GATEWAY_YANDEX_IAM_TOKEN

Если токен пустой — клиент кидает YandexClientNotConfigured.
Все публичные методы имеют fallback на заглушку, чтобы тесты и dev-режим работали без Yandex.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from scientific_tangle_gateway.config import settings

logger = logging.getLogger(__name__)


class YandexClientError(RuntimeError):
    pass


class YandexClientNotConfigured(YandexClientError):
    pass


class YandexClient:
    """Тонкий клиент YandexGPT REST API.

    Документация: https://yandex.cloud/ru/docs/yandexgpt/api-ref/grpc/
    """

    def __init__(
        self,
        folder_id: str | None = None,
        iam_token: str | None = None,
        api_url: str | None = None,
        model: str | None = None,
        embeddings_model: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.folder_id = folder_id if folder_id is not None else settings.yandex_folder_id
        self.iam_token = iam_token if iam_token is not None else settings.yandex_iam_token
        self.api_url = api_url or settings.yandex_api_url
        self.model = model or settings.yandexgpt_model
        self.embeddings_model = embeddings_model or settings.yandex_embeddings_model
        self.timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.folder_id and self.iam_token)

    def _require_config(self) -> None:
        if not self.is_configured:
            raise YandexClientNotConfigured(
                "YandexGPT не настроен: укажите GATEWAY_YANDEX_FOLDER_ID и GATEWAY_YANDEX_IAM_TOKEN в .env"
            )

    def _headers(self) -> dict[str, str]:
        self._require_config()
        return {
            "Authorization": f"Bearer {self.iam_token}",
            "x-folder-id": self.folder_id,
            "Content-Type": "application/json",
        }

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        """Синхронный chat completion. Возвращает текст ответа.

        Fallback: если клиент не настроен — возвращает пустую строку с предупреждением.
        Это позволяет dev-режиму работать без API-ключа.
        """
        if not self.is_configured:
            logger.warning("YandexGPT не настроен, chat() вернёт пустую строку")
            return ""

        payload = {
            "modelUri": f"ml://gpt://{self.folder_id}/{self.model}",
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": str(max_tokens),
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_prompt},
            ],
        }

        try:
            response = httpx.post(
                f"{self.api_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            alternatives = data.get("result", {}).get("alternatives", [])
            if not alternatives:
                return ""
            return alternatives[0].get("message", {}).get("text", "")
        except httpx.HTTPError as error:
            logger.error("YandexGPT chat error: %s", error)
            raise YandexClientError(f"Chat request failed: {error}") from error

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        """Chat с ожидаемым JSON-ответом.

        Достаёт JSON из ответа модели, отбрасывая markdown-обёртки ```json ... ```.
        При ошибке парсинга возвращает {"_raw": "<текст>"}.
        """
        text = self.chat(system_prompt, user_prompt, temperature, max_tokens)
        if not text:
            return {}
        return self._parse_json_lenient(text)

    @staticmethod
    def _parse_json_lenient(text: str) -> dict[str, Any]:
        """Достаёт JSON из текста LLM, отбрасывая markdown-обёртки."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    pass
            return {"_raw": text}

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Векторизация списка текстов через Yandex embeddings API.

        Fallback: если не настроен — пустой список.
        """
        if not self.is_configured:
            logger.warning("YandexGPT embeddings не настроен, возвращён пустой список")
            return []

        if not texts:
            return []

        payload = {
            "modelUri": f"emb://{self.folder_id}/{self.embeddings_model}",
            "text": texts,
        }
        try:
            response = httpx.post(
                f"{self.api_url}/embedding",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            return [item["vectors"] for item in data.get("embeddings", [])]
        except httpx.HTTPError as error:
            logger.error("YandexGPT embeddings error: %s", error)
            raise YandexClientError(f"Embeddings request failed: {error}") from error


_default_client: YandexClient | None = None


def get_default_client() -> YandexClient:
    global _default_client
    if _default_client is None:
        _default_client = YandexClient()
    return _default_client
