import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()  # .env 파일 로드

class Settings(BaseSettings):
    APP_NAME: str = "키움 트레이딩 API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    
    # 키움 API 설정 
    KIWOOM_APP_KEY: str = os.getenv("KIWOOM_APP_KEY", "")
    KIWOOM_SECRET_KEY: str = os.getenv("KIWOOM_SECRET_KEY", "")
    KIWOOM_REAL_SERVER: bool = os.getenv("KIWOOM_REAL_SERVER", "false").lower() == "true"
    
    # 웹소켓 설정
    WS_HEARTBEAT_INTERVAL: int = 30  # 초
    
    # CORS 설정
    CORS_ORIGINS: list = ["http://localhost:3000"]
    
    # PostgreSQL 설정 추가 (.env에서 오버라이드)
    PG_USER: str = "kim"
    PG_PASSWORD: str = "0510"
    PG_HOST: str = "localhost"
    PG_PORT: str = "5432"
    PG_DATABASE: str = "kiwoomdb"
    
    # Redis 설정 추가(.env에서 오버라이드)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    
    class Config:
        env_file = ".env"

settings = Settings()

