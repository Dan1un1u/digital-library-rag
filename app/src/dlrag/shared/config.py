"""统一配置。只读环境与 .env；不在导入时联网。"""
from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from .models import ChunkingConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_mode: Literal["real", "mock"]
    data_dir: Path | None = None
    db_path: Path | None = None
    files_dir: Path | None = None
    index_dir: Path | None = None
    chunking_config: ChunkingConfig = Field(default_factory=ChunkingConfig)
    max_upload_mb: int = Field(default=25, gt=0, le=500)
    metadata_api_enabled: bool = True
    metadata_api_provider: Literal["siliconflow", "cliproxyapi"] = "siliconflow"
    metadata_api_model: str = "Qwen/Qwen3-VL-8B-Instruct"
    metadata_api_timeout_seconds: float = Field(default=45, gt=0, le=180, allow_inf_nan=False)
    metadata_lookup_enabled: bool = True
    metadata_lookup_timeout_seconds: float = Field(default=10, gt=0, le=30, allow_inf_nan=False)
    api_base_url: str = "http://127.0.0.1:8000"
    embedding_model: str = "BAAI/bge-m3"
    embedding_provider: Literal["siliconflow", "local_bge"] = "siliconflow"
    embedding_base_url: str = "http://127.0.0.1:18080/v1"
    embedding_revision: str | None = None
    embedding_dimension: int = Field(default=1024, gt=0)
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_api_key: SecretStr = SecretStr("")
    sd_embedding_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_provider: Literal["siliconflow", "cliproxyapi"] = "siliconflow"
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] = "none"
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    llm_max_output_tokens: int = Field(default=1000, gt=0)
    llm_context_window_tokens: int = Field(default=32768, gt=0)
    llm_client_factory: str = ""
    llm_enable_thinking: bool | None = None
    planning_enabled: bool = True
    retrieval_mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    qa_context_budget_tokens: int = Field(default=18000, gt=0)
    qa_max_evidence_chunks: int = Field(default=8, ge=1, le=12)
    qa_bilingual_retrieval_enabled: bool = True
    qa_evidence_rerank_enabled: bool = True
    qa_semantic_rerank_enabled: bool = True
    qa_rerank_model: str = 'BAAI/bge-reranker-v2-m3'
    qa_rerank_provider: Literal["siliconflow", "llm"] = "siliconflow"
    qa_rerank_timeout_seconds: float = Field(default=20, gt=0, allow_inf_nan=False)
    qa_reference_penalty_enabled: bool = True
    qa_neighbor_expansion_enabled: bool = True
    qa_neighbor_radius: int = Field(default=1, ge=1, le=2)
    qa_neighbor_seed_k: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def paths(self):
        if self.llm_max_output_tokens >= self.llm_context_window_tokens:
            raise ValueError("LLM 输出预算必须小于上下文上限")
        self.data_dir = (self.data_dir or Path("data") / self.app_mode).resolve()
        self.db_path = (self.db_path or self.data_dir / "library.sqlite").resolve()
        self.files_dir = (self.files_dir or self.data_dir / "raw").resolve()
        self.index_dir = (self.index_dir or self.data_dir / "indexes").resolve()
        return self

    def public(self):
        return {"app_mode": self.app_mode, "embedding_model": self.embedding_model,
                "embedding_provider": self.embedding_provider,
                "llm_provider": self.llm_provider,
                "metadata_api_provider": self.metadata_api_provider,
                "qa_rerank_provider": self.qa_rerank_provider,
                "metadata_api_enabled": self.metadata_api_enabled,
                "metadata_api_model": self.metadata_api_model,
                "metadata_api_timeout_seconds": self.metadata_api_timeout_seconds,
                "metadata_lookup_enabled": self.metadata_lookup_enabled,
                "metadata_lookup_timeout_seconds": self.metadata_lookup_timeout_seconds,
                "embedding_revision": self.embedding_revision or None,
                "embedding_dimension": self.embedding_dimension, "llm_model": self.llm_model,
                "llm_timeout_seconds": self.llm_timeout_seconds,
                "llm_max_output_tokens": self.llm_max_output_tokens,
                "llm_context_window_tokens": self.llm_context_window_tokens,
                "llm_enable_thinking": self.llm_enable_thinking,
                "chunking_config": self.chunking_config.model_dump(),
                "planning_enabled": self.planning_enabled, "retrieval_mode": self.retrieval_mode,
                "qa_context_budget_tokens": self.qa_context_budget_tokens,
                "qa_max_evidence_chunks": self.qa_max_evidence_chunks,
                "qa_bilingual_retrieval_enabled": self.qa_bilingual_retrieval_enabled,
                "qa_evidence_rerank_enabled": self.qa_evidence_rerank_enabled,
                "qa_semantic_rerank_enabled": self.qa_semantic_rerank_enabled,
                "qa_rerank_model": self.qa_rerank_model,
                "qa_reference_penalty_enabled": self.qa_reference_penalty_enabled,
                "qa_neighbor_expansion_enabled": self.qa_neighbor_expansion_enabled,
                "qa_neighbor_radius": self.qa_neighbor_radius,
                "qa_neighbor_seed_k": self.qa_neighbor_seed_k,
                "max_upload_mb": self.max_upload_mb}
