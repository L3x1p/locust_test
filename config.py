from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="")

    database_url: str = "postgresql+psycopg2://postgres:Qqwerty1%21@localhost:5433/chat"
    api_base_url: str = "http://localhost:8080"  
    vllm_base_url: str = "http://localhost:8000"
    vllm_api_key: str = "local-token"
    vllm_model: str = "Qwen/Qwen2.5-3B-Instruct"
    vllm_max_tokens: int = 256


settings = Settings()
