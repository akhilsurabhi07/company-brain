import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "Company Brain Ingestion Engine"
    ENVIRONMENT: str = "development"

    # Database Settings
    POSTGRES_USER: str = "company_brain_app"
    POSTGRES_PASSWORD: str = "app_secure_password_2026"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "company_brain"

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # AWS S3 / MinIO Settings
    S3_ENDPOINT_URL: str = "http://localhost:9000"  # MinIO default, or None for real AWS S3
    S3_ACCESS_KEY_ID: str = "minioadmin"
    S3_SECRET_ACCESS_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "company-brain-raw-data"
    S3_REGION: str = "us-east-1"

    # Redis & Celery Settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # Security Settings
    MASTER_ENCRYPTION_KEY: str = "default_master_encryption_key_32bytes_len!"  # Replace in production

    # LLM Provider API Keys
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    OLLAMA_HOST: str = "http://localhost:11434"
    VLLM_ENDPOINT: str = "http://localhost:8000/v1"

    # Free LLM Providers
    GROQ_API_KEY: str = ""
    HUGGINGFACE_API_KEY: str = ""

    # Google OAuth (Drive connector) — real 3-legged OAuth 2.0, not domain-wide
    # delegation (Google itself recommends against DWD's org-wide impersonation
    # power). Create these in Google Cloud Console > APIs & Services > Credentials.
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/connectors/oauth/google_drive/callback"

    # Atlassian OAuth (Jira connector) — real OAuth 2.0 (3LO), not the API-token
    # basic-auth shortcut (Atlassian's own docs say collecting tokens from customers
    # doesn't meet their cloud-app security requirements). Create at developer.atlassian.com.
    JIRA_OAUTH_CLIENT_ID: str = ""
    JIRA_OAUTH_CLIENT_SECRET: str = ""
    JIRA_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/connectors/oauth/jira/callback"

    # Microsoft identity platform OAuth (SharePoint connector) — real delegated
    # permissions + refresh token (the safe equivalent of Drive/Jira's approach), NOT
    # application permissions / app-only access, which is Microsoft's parallel to
    # Google's domain-wide delegation. Create at entra.microsoft.com (App registrations).
    MICROSOFT_OAUTH_CLIENT_ID: str = ""
    MICROSOFT_OAUTH_CLIENT_SECRET: str = ""
    MICROSOFT_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/connectors/oauth/sharepoint/callback"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
