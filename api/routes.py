from fastapi import APIRouter
from .endpoints import market, orders, account,realtime,server_sockets

# API 라우터 생성
api_router = APIRouter()

# 각 엔드포인트 라우터 등록
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(account.router, prefix="/account", tags=["account"])
api_router.include_router(realtime.router, prefix="/realtime", tags=["realtime"])
api_router.include_router(server_sockets.router, prefix="/socket", tags=["socket"])
