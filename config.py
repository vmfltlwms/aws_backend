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
    
    class Config:
        env_file = ".env"

settings = Settings()