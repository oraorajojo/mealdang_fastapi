from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]  # mealdang_fastapi

# 환경 설정 관리 클래스 : BaseSettings 상속받아 정의, 타입 힌트 필수
class Settings(BaseSettings):
    APP_NAME: str = "MealDang-FastAPI"
    APP_ENV: str
    APP_HOST: str
    APP_PORT: int
    APP_DEBUG: bool = False
    CORS_ORIGINS: str

    # DB 설정은 저장소 준비되면 여기에 추가 예정 (DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME)

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
