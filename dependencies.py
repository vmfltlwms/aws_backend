from fastapi import Depends
from db.postgres import get_db_connection
from db.redis_client import get_redis_connection
from core.kiwoom_client import KiwoomClient
from core.socket_client import SocketClient
from core.websocket import ConnectionManager
from services.realtime_services import RealtimeStateManager
from services.realtime_handler import RealtimeHandler


# 싱글톤 인스턴스
_kiwoom_client = None
_connection_manager = None
_realtime_state_manager = None
_socket_client = None
_realtime_handler = None


def get_realtime_handler() -> RealtimeHandler:
    """실시간 데이터 핸들러 인스턴스 제공"""
    global _realtime_handler
    if _realtime_handler is None:
        _realtime_handler = RealtimeHandler()
        
    return _realtime_handler
def get_kiwoom_client() -> KiwoomClient:
    """키움 API 클라이언트 인스턴스 제공"""
    global _kiwoom_client
    if _kiwoom_client is None:
        _kiwoom_client = KiwoomClient()
    return _kiwoom_client

def get_socket_client() -> SocketClient:
    """소켓 클라이언트 인스턴스 제공"""
    global _socket_client
    if _socket_client is None:
        _socket_client = SocketClient()
    return _socket_client

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