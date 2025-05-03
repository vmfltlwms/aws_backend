from dependency_injector import containers, providers
from core.token_client import TokenGenerator



class TokenContainer(containers.DeclarativeContainer):

    wiring_config =  containers.WiringConfiguration(
        modules=["core.kiwoom_client", "core.socket_client"]  # 의존성 주입할 모듈
    )
    token_generator = providers.Singleton(TokenGenerator)

