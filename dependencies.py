from fastapi import Depends
from db.postgres import get_db_connection
from db.redis_client import get_redis_connection
from core.kiwoom_client import KiwoomClient
from core.websocket import ConnectionManager
# from core.realtime_state import RealtimeStateManagerk
from services.realtime_services import RealtimeStateManager

# 싱글톤 인스턴스
_kiwoom_client = None
_connection_manager = None
_realtime_state_manager = None

def get_kiwoom_client() -> KiwoomClient:
    """키움 API 클라이언트 인스턴스 제공"""
    global _kiwoom_client
    if _kiwoom_client is None:
        _kiwoom_client = KiwoomClient()
    return _kiwoom_client

def get_connection_manager() -> ConnectionManager:
    """웹소켓 연결 관리자 인스턴스 제공"""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager

def get_realtime_state_manager() -> RealtimeStateManager:
    """실시간 상태 관리자 인스턴스 제공"""
    global _realtime_state_manager
    if _realtime_state_manager is None:
        _realtime_state_manager = RealtimeStateManager()
    return _realtime_state_manager

def get_db():
    """PostgreSQL 데이터베이스 연결을 반환합니다."""
    return get_db_connection()

def get_redis():
    """Redis 연결을 반환합니다."""
    return get_redis_connection()