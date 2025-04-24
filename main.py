import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.routes import api_router
from config import settings
from core.kiwoom_client import KiwoomClient
from dependencies import get_kiwoom_client

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 라이프사이클 핸들러 정의
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 시작 시 실행
    kiwoom_client = get_kiwoom_client()
    await kiwoom_client.initialize()
    logging.info("Kiwoom client initialized.")
    yield
    # 앱 종료 시 실행
    await kiwoom_client.disconnect()
    logging.info("Kiwoom client disconnected.")

# FastAPI 앱 인스턴스 생성 (lifespan 적용)
app = FastAPI(
    title=settings.APP_NAME,
    description="키움 API를 활용한 트레이딩 서비스",
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan  # 👈 여기 lifespan 등록
)

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(api_router, prefix="/api")

# 상태 확인 엔드포인트
@app.get("/")
async def root():
    """API 상태 확인"""
    kiwoom_client = get_kiwoom_client()
    return {
        "status": "online",
        "connected_to_kiwoom": kiwoom_client.connected,
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION
    }

# 서버 실행 코드
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=settings.DEBUG)
