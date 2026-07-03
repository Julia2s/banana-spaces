from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ScientificTangle Gateway"
    app_version: str = "0.2.0"
    environment: str = "local"
    api_prefix: str = "/api"
    raw_upload_dir: Path = Path("data/raw_uploads")
    normalized_dir: Path = Path("data/normalized")
    source_corpus_dir: Path = Path("demo/seed_data")
    db_dsn: str = "postgresql://scientific_tangle:scientific_tangle@localhost:5432/scientific_tangle"
    worker_poll_interval_seconds: float = 1.0
    worker_batch_size: int = 10
    retrieval_source_char_limit: int = 8000
    retrieval_top_k_default: int = 10

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "scientific_tangle"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "st_chunks"
    qdrant_vector_dim: int = 768

    yandex_folder_id: str = ""
    yandex_iam_token: str = ""
    yandexgpt_model: str = "yandexgpt-4-pro"
    yandex_embeddings_model: str = "emb/text-search-doc"
    yandex_api_url: str = "https://llm.api.cloud.yandex.net/llm/v1"

    embeddings_backend: str = "sentence-transformers"
    embeddings_model_name: str = "sentence-transformers/LaBSE"

    audit_enabled: bool = True
    audit_log_body: bool = False

    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")


settings = Settings()
