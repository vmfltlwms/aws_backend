from fastapi import Depends

from core.kiwoom_client import KiwoomClient
from core.websocket import ConnectionManager

# 싱글톤 인스턴스
_kiwoom_client = None
_connection_manager = None

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