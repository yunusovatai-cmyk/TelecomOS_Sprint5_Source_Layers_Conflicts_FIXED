from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TelecomOS API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://telecomos:telecomos@localhost:5432/telecomos"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "telecomos"
    minio_secret_key: str = "telecomos123"
    minio_secure: bool = False
    pdf_extraction_timeout_seconds: int = 180
    pdf_max_pages: int = 500
    pdf_max_words: int = 1_000_000
    pdf_max_evidence: int = 50_000
    pdf_max_render_pixels: int = 25_000_000
    pdf_low_confidence_threshold: float = 0.8
    pdf_span_length_min_difference_ft: float = 25.0
    pdf_span_length_difference_ratio: float = 0.15

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
