import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from container.token_di import TokenContainer 
from api.routes import api_router
from config import settings
from core.kiwoom_client import KiwoomClient
from dependencies import get_kiwoom_client, get_socket_client,get_realtime_handler
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
    
    # 1. 먼저 realtime_handler 인스턴스 가져오기
    realtime_handler = get_realtime_handler()
    logging.info(f"RealtimeHandler 인스턴스 생성됨")
    
    # 2. realtime_handler 초기화
    await realtime_handler.initialize()
    logging.info("Realtime handler initialized.")
    
    # 3. SocketClient 인스턴스 가져오기
    socket_client = get_socket_client()
    logging.info("SocketClient 인스턴스 생성됨")
    
    # 4. SocketClient에 realtime_handler 전달하며 초기화
    await socket_client.initialize(realtime_handler=realtime_handler)
    logging.info("Socket client initialized with realtime_handler.")

    # 데이터베이스 연결 초기화
    await init_db()
    logging.info("PostgreSQL connection initialized.")
    
    # Redis 연결 초기화
    await init_redis()
    logging.info("Redis connection initialized.")
    
    yield
    
    # 앱 종료 시 실행
    await socket_client.disconnect()
    logging.info("socket client disconnected.")
    
    # 데이터베이스 연결 종료
    await close_db()
    logging.info("PostgreSQL connection closed.")
    
    # Redis 연결 종료
    await close_redis()
    logging.info("Redis connection closed.")

# 토큰 의존성 주입을 위한 컨테이너 설정
app_container = TokenContainer()
app_container.wire(
    modules=["core.kiwoom_client", "core.socket_client"]  # 의존성 주입할 모듈
)

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
    allow_origins=["*"],
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
        "connected_to_kiwoom": True,
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database_connected": True
    }

# 서버 실행 코드
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)

