import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    APP_NAME: str = "Agent 34 - Fraud Investigation Agent"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    
    # MySQL Database Connection
    DATABASE_URL: str = Field(
        default="mysql+pymysql://root:Sqlwork%402026@localhost:3306/Agent_34?charset=utf8mb4"
    )
    
    # JWT Security & RBAC
    SECRET_KEY: str = "agent34-super-secret-jwt-key-for-fraud-investigation-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    
    # Ollama Local LLM
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    OLLAMA_FALLBACK_MODEL: str = "gemma2:9b"
    
    # Policy RAG Vector Store
    QDRANT_STORAGE_PATH: str = "./qdrant_data"
    POLICY_COLLECTION_NAME: str = "fraud_policies"
    EMBEDDING_DIMENSION: int = 384
    
    # Decision Gateway
    DEFAULT_DECISION_MODE: str = "ADVISOR"
    
    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
