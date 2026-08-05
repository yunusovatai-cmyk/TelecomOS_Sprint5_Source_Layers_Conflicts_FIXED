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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
