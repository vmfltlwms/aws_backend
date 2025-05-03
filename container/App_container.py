# containers.py
from dependency_injector import containers, providers
from core.token_client import TokenGenerator
from core.kiwoom_client import KiwoomClient
from core.socket_client import SocketClient
from core.websocket import ConnectionManager
from services.realtime_services import RealtimeStateManager
from db.postgres import get_db_connection
from db.redis_client import get_redis_connection

class AppContainer(containers.DeclarativeContainer):
    # 와이어링 설정
    wiring_config = containers.WiringConfiguration(
        modules=[
            "api.endpoints.market", 
            "api.endpoints.orders",
            "api.endpoints.account",
            "api.endpoints.realtime",
            "core.kiwoom_client",
            "core.socket_client"
        ]
    )
    
    # 설정 관리
    config = providers.Configuration()
    
    # 토큰 생성기
    token_generator = providers.Singleton(TokenGenerator)
    
    # 키움 클라이언트
    kiwoom_client = providers.Singleton(
        KiwoomClient,
        token_generator=token_generator
    )
    
    # 소켓 클라이언트
    socket_client = providers.Singleton(
        SocketClient,
        token_generator=token_generator
    )
    
    # 웹소켓 연결 관리자
    connection_manager = providers.Singleton(ConnectionManager)
    
    # 실시간 상태 관리자
    realtime_state_manager = providers.Singleton(RealtimeStateManager)
    
    # 데이터베이스 연결
    db = providers.Factory(get_db_connection)
    
    # Redis 연결
    redis = providers.Factory(get_redis_connection)

# 컨테이너 인스턴스 생성
container = AppContainer()