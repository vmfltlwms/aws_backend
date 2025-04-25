import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.routes import api_router
from config import settings
from core.kiwoom_client import KiwoomClient
from dependencies import get_kiwoom_client
from db.postgres import init_db, close_db
from db.redis_client import init_redis, close_redis

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
    
    # 데이터베이스 연결 초기화
    await init_db()
    logging.info("PostgreSQL connection initialized.")
    
    # Redis 연결 초기화
    await init_redis()
    logging.info("Redis connection initialized.")
    
    yield
    
    # 앱 종료 시 실행
    await kiwoom_client.disconnect()
    logging.info("Kiwoom client disconnected.")
    
    # 데이터베이스 연결 종료
    await close_db()
    logging.info("PostgreSQL connection closed.")
    
    # Redis 연결 종료
    await close_redis()
    logging.info("Redis connection closed.")

# FastAPI 앱 인스턴스 생성 (lifespan 적용)
app = FastAPI(
    title=settings.APP_NAME,
    description="키움 API를 활용한 트레이딩 서비스",
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan
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
        "version": settings.APP_VERSION,
        "database_connected": True
    }

# 서버 실행 코드
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=settings.DEBUG)

# import logging
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from contextlib import asynccontextmanager
# from api.routes import api_router
# from config import settings
# from core.kiwoom_client import KiwoomClient
# from dependencies import get_kiwoom_client
# from db.postgres import init_db, close_db  # 추가: PostgreSQL 연결 함수
# from db.redis_client import init_redis, close_redis  # 추가: Redis 연결 함수

# # 로깅 설정
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )

# # 라이프사이클 핸들러 정의
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # 앱 시작 시 실행
#     # Kiwoom 클라이언트 초기화
#     kiwoom_client = get_kiwoom_client()
#     await kiwoom_client.initialize()
#     logging.info("Kiwoom client initialized.")
    
#     # 데이터베이스 연결 초기화
#     await init_db()
#     logging.info("PostgreSQL connection initialized.")
    
#     # Redis 연결 초기화
#     await init_redis()
#     logging.info("Redis connection initialized.")
    
#     yield
    
#     # 앱 종료 시 실행
#     await kiwoom_client.disconnect()
#     logging.info("Kiwoom client disconnected.")
    
#     # 데이터베이스 연결 종료
#     await close_db()
#     logging.info("PostgreSQL connection closed.")
    
#     # Redis 연결 종료
#     await close_redis()
#     logging.info("Redis connection closed.")

# # FastAPI 앱 인스턴스 생성 (lifespan 적용)
# app = FastAPI(
#     title=settings.APP_NAME,
#     description="키움 API를 활용한 트레이딩 서비스",
#     version=settings.APP_VERSION,
#     debug=settings.DEBUG,
#     lifespan=lifespan
# )

# # CORS 미들웨어 설정
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=settings.CORS_ORIGINS,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # API 라우터 등록
# app.include_router(api_router, prefix="/api")

# # 상태 확인 엔드포인트
# @app.get("/")
# async def root():
#     """API 상태 확인"""
#     kiwoom_client = get_kiwoom_client()
#     return {
#         "status": "online",
#         "connected_to_kiwoom": kiwoom_client.connected,
#         "app_name": settings.APP_NAME,
#         "version": settings.APP_VERSION,
#         "database_connected": True  # 추가: 데이터베이스 연결 상태
#     }

# # 서버 실행 코드
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=settings.DEBUG)