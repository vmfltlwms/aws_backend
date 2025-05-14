import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from core.socket_client import SocketClient
from services.realtime_services import RealtimeStateManager
from models.stock import ConditionalSearch, ConditionalSearchRequest, \
                        RealtimePriceRequest, RealtimePriceUnsubscribeRequest
from dependencies import get_socket_client, get_realtime_state_manager

router = APIRouter()
logger = logging.getLogger(__name__)

# 실시간 데이터 통계
class RealtimeStats:
    def __init__(self):
        self.received_count = 0
        self.last_received = None
        self.error_count = 0
        self.by_type = {}
        self.connection_events = []
    
    def update(self, data_type: str):
        self.received_count += 1
        self.last_received = datetime.now()
        self.by_type[data_type] = self.by_type.get(data_type, 0) + 1
    
    def add_error(self):
        self.error_count += 1
    
    def add_connection_event(self, event: str):
        self.connection_events.append({
            "event": event,
            "timestamp": datetime.now().isoformat()
        })
        # 최근 100개만 유지
        if len(self.connection_events) > 100:
            self.connection_events = self.connection_events[-100:]
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "received_count": self.received_count,
            "last_received": self.last_received.isoformat() if self.last_received else None,
            "error_count": self.error_count,
            "by_type": self.by_type,
            "recent_events": self.connection_events[-10:]  # 최근 10개 이벤트
        }

# 글로벌 통계 인스턴스
stats = RealtimeStats()

# 헬스체크 엔드포인트
@router.get("/health",
            summary="실시간 연결 상태 확인",
            description="WebSocket 연결 상태 및 실시간 데이터 수신 상태를 확인합니다.")
async def check_realtime_health(
    socket_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """실시간 연결 상태 확인"""
    try:
        health_status = {
            "connected": socket_client.connected,
            "websocket_active": socket_client.websocket is not None,
            "receive_task_active": bool(
                socket_client.receive_task and not socket_client.receive_task.done()
            ),
            "monitor_task_active": bool(
                hasattr(socket_client, 'monitor_task') and 
                socket_client.monitor_task and 
                not socket_client.monitor_task.done()
            ),
            "registered_groups": len(socket_client.registered_items),
            "active_subscriptions": state_manager.get_active_subscriptions(),
            "last_connected": datetime.fromtimestamp(
                socket_client.last_connected_time
            ).isoformat() if socket_client.last_connected_time else None,
            "reconnect_attempts": socket_client.reconnect_attempts,
            "statistics": stats.get_stats()
        }
        
        # 전반적인 상태 판단
        if socket_client.connected and health_status["websocket_active"]:
            health_status["status"] = "healthy"
        elif socket_client.reconnect_attempts > 0:
            health_status["status"] = "reconnecting"
        else:
            health_status["status"] = "unhealthy"
        
        return health_status
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

# 연결 재시작 엔드포인트
@router.post("/restart",
             summary="실시간 연결 재시작",
             description="WebSocket 연결을 재시작합니다.")
async def restart_connection(
    socket_client: SocketClient = Depends(get_socket_client)
):
    """연결 재시작"""
    try:
        logger.info("실시간 연결 재시작 요청")
        stats.add_connection_event("restart_requested")
        
        # 기존 연결 종료
        await socket_client.disconnect()
        
        # 잠시 대기
        import asyncio
        await asyncio.sleep(1)
        
        # 재연결
        success = await socket_client.connect()
        
        if success:
            stats.add_connection_event("restart_success")
            return {
                "status": "success",
                "message": "연결 재시작 완료",
                "connected": socket_client.connected
            }
        else:
            stats.add_connection_event("restart_failed")
            return {
                "status": "failed",
                "message": "연결 재시작 실패",
                "connected": socket_client.connected
            }
            
    except Exception as e:
        logger.error(f"Restart error: {e}")
        stats.add_error()
        raise HTTPException(status_code=500, detail=str(e))

# 구독 현황 조회 엔드포인트
@router.get("/subscriptions",
            summary="실시간 구독 현황 조회",
            description="현재 활성화된 실시간 구독 목록을 조회합니다.")
async def get_subscriptions(
    socket_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """현재 구독 현황 조회"""
    try:
        return {
            "socket_client_items": socket_client.registered_items,
            "state_manager_subs": state_manager.get_active_subscriptions(),
            "total_groups": len(socket_client.registered_items),
            "total_items": sum(
                len(items) for items in socket_client.registered_items.values()
            )
        }
    except Exception as e:
        logger.error(f"Get subscriptions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/price/subscribe",
            summary="실시간 구독 등록",
            description="실시간 구독 등록",
            responses={
                200: {"description": "구독 성공"},
                400: {"description": "잘못된 요청"},
                503: {"description": "서비스 이용 불가"}
            })
async def subscribe_realtime_price(
    request: RealtimePriceRequest,
    socket_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """
    실시간 시세 정보 구독 API
    
    - **group_no**: 그룹 번호
    - **items**: 종목 코드 리스트 (예: ["005930", "000660"])
    - **data_types**: 데이터 타입 리스트 (예: ["0D"])
    - **refresh**: 새로고침 여부 (True: 기존 등록 초기화, False: 기존에 추가)
    """
    try:
        # 연결 상태 확인
        if not socket_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # 입력값 검증
        if not request.items:
            raise HTTPException(status_code=400, detail="종목 코드가 비어있습니다.")
        
        if not request.data_types:
            request.data_types = ["0D"]  # 기본값 설정
        
        # 구독 요청
        result = await socket_client.subscribe_realtime_price(
            group_no=request.group_no,
            items=request.items,
            data_types=request.data_types,
            refresh=request.refresh
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # 상태 관리자 업데이트
        state_manager.add_subscription(
            group_no=request.group_no,
            items=request.items,
            data_types=request.data_types,
            refresh=request.refresh
        )
        
        # 통계 업데이트
        stats.add_connection_event(f"subscribe_group_{request.group_no}")
        
        logger.info(f"구독 성공: 그룹={request.group_no}, 종목={request.items}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Subscribe error: {e}", exc_info=True)
        stats.add_error()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/price/unsubscribe",
            summary="실시간 구독 등록해제",
            description="실시간 구독 등록해제")
async def unsubscribe_realtime_price(
    request: RealtimePriceUnsubscribeRequest,
    socket_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """
    실시간 시세 정보 구독 해제 API
    
    - **group_no**: 그룹 번호
    - **items**: 종목 코드 리스트 (예: ["005930", "000660"]). None이면 그룹 전체 해제
    - **data_types**: 데이터 타입 리스트 (예: ["0D"]). None이면 지정된 종목의 모든 타입 해제
    """
    try:
        if not socket_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        result = await socket_client.unsubscribe_realtime_price(
            group_no=request.group_no,
            items=request.items,
            data_types=request.data_types
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # 상태 관리자 업데이트
        state_manager.remove_subscription(
            group_no=request.group_no,
            items=request.items,
            data_types=request.data_types
        )
        
        # 통계 업데이트
        stats.add_connection_event(f"unsubscribe_group_{request.group_no}")
        
        logger.info(f"구독 해제 성공: 그룹={request.group_no}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unsubscribe error: {e}", exc_info=True)
        stats.add_error()
        raise HTTPException(status_code=500, detail=str(e))

# 그룹 전체 해제를 위한 간단한 엔드포인트
@router.delete("/price/group/{group_no}")
async def unsubscribe_group(
    group_no: str,
    socket_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """
    실시간 시세 그룹 전체 구독 해제 API
    
    - **group_no**: 해제할 그룹 번호
    """
    try:
        if not socket_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        result = await socket_client.unsubscribe_realtime_price(group_no=group_no)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # 상태 관리자 업데이트
        state_manager.remove_subscription(group_no=group_no)
        
        # 통계 업데이트
        stats.add_connection_event(f"unsubscribe_entire_group_{group_no}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unsubscribe group error: {e}", exc_info=True)
        stats.add_error()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/condition/list")
async def get_condition_list(socket_client: SocketClient = Depends(get_socket_client)):
    """조건검색 목록 조회 (ka10171)"""
    try:
        if not socket_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await socket_client.get_condition_list()
        logger.debug(f"조건검색 목록: {json.dumps(response, indent=2)}")
        
        return response
    except Exception as e:
        logger.error(f"조건검색 목록 조회 오류: {str(e)}")
        stats.add_error()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/condition/search")
async def request_condition_search(
    condition_search: ConditionalSearchRequest,
    socket_client: SocketClient = Depends(get_socket_client)
):
    """조건검색 요청 일반 (ka10172)"""
    try:
        if not socket_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        result = await socket_client.request_condition_search(
            seq=condition_search.seq,
            search_type=condition_search.search_type,
            market_type=condition_search.market_type,
            cont_yn=condition_search.cont_yn,
            next_key=condition_search.next_key
        )
        
        return result
    except Exception as e:
        logger.error(f"조건검색 요청 오류: {str(e)}")
        stats.add_error()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/condition/realtime")
async def request_realtime_condition(
    condition_search: ConditionalSearch,
    socket_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """조건검색 요청 실시간 (ka10173)"""
    try:
        if not socket_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        result = await socket_client.request_realtime_condition(
            condition_search.seq,
            condition_search.search_type,
            condition_search.market_type
        )
        
        # 상태 관리자 업데이트
        state_manager.add_condition_subscription(condition_search.seq)
        
        return {"status": "success", "message": "실시간 조건검색 요청 완료", "data": result}
    except Exception as e:
        logger.error(f"실시간 조건검색 요청 오류: {str(e)}")
        stats.add_error()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/condition/cancel")
async def cancel_realtime_condition(
    seq: str = Query(..., description="조건검색식 일련번호"),
    socket_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """조건검색 실시간 해제 (ka10174)"""
    try:
        if not socket_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        result = await socket_client.cancel_realtime_condition(seq)
        
        # 상태 관리자 업데이트
        state_manager.remove_condition_subscription(seq)
        
        return {"status": "success", "message": f"실시간 조건검색 해제 완료 (조건번호: {seq})"}
    except Exception as e:
        logger.error(f"실시간 조건검색 해제 오류: {str(e)}")
        stats.add_error()
        raise HTTPException(status_code=500, detail=str(e))

# WebSocket 엔드포인트 (실시간 데이터 스트리밍)
@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    socket_client: SocketClient = Depends(get_socket_client)
):
    """WebSocket을 통한 실시간 데이터 스트리밍"""
    await websocket.accept()
    socket_client.websocket_clients.append(websocket)
    
    try:
        while True:
            # 클라이언트로부터 메시지 수신 대기
            data = await websocket.receive_text()
            # 필요한 경우 메시지 처리
            logger.debug(f"WebSocket 메시지 수신: {data}")
    except WebSocketDisconnect:
        socket_client.websocket_clients.remove(websocket)
        logger.info("WebSocket 클라이언트 연결 해제")
    except Exception as e:
        logger.error(f"WebSocket 오류: {e}")
        if websocket in socket_client.websocket_clients:
            socket_client.websocket_clients.remove(websocket)

# 통계 조회 엔드포인트
@router.get("/stats",
            summary="실시간 데이터 통계",
            description="실시간 데이터 수신 통계를 조회합니다.")
async def get_realtime_stats():
    """실시간 데이터 통계 조회"""
    return stats.get_stats()

# 통계 재설정 엔드포인트
@router.post("/stats/reset",
             summary="통계 재설정",
             description="실시간 데이터 통계를 재설정합니다.")
async def reset_stats():
    """통계 재설정"""
    global stats
    stats = RealtimeStats()
    return {"status": "success", "message": "통계가 재설정되었습니다."}