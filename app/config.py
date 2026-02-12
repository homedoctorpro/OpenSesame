from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    linkedin_rate_limit_delay: float = 3.0
    max_urls_per_batch: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
