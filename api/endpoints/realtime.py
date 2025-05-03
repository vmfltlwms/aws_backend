import logging
import json
from fastapi import APIRouter, Depends, HTTPException,Query
from core.socket_client import SocketClient
from services.realtime_services import RealtimeStateManager
from models.stock import ConditionalSearch, ConditionalSearchRequest, \
                        RealtimePriceRequest, RealtimePriceUnsubscribeRequest
from dependencies import get_socket_client, get_realtime_state_manager

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/price/subscribe",
            summary="실시간 구독 등록",
            description="실시간 구독 등록")
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
    if not socket_client.connected:
        raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
    
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
    
    return result


@router.post("/price/unsubscribe",
            summary="실시간 구독 등록해제",
            description="실시간 구독 등록해제")
async def unsubscribe_realtime_price(
    request: RealtimePriceUnsubscribeRequest,
    kiwoom_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """
    실시간 시세 정보 구독 해제 API
    
    - **group_no**: 그룹 번호
    - **items**: 종목 코드 리스트 (예: ["005930", "000660"]). None이면 그룹 전체 해제
    - **data_types**: 데이터 타입 리스트 (예: ["0D"]). None이면 지정된 종목의 모든 타입 해제
    """
    if not kiwoom_client.connected:
        raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
    
    result = await kiwoom_client.unsubscribe_realtime_price(
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
    
    return result


# 그룹 전체 해제를 위한 간단한 엔드포인트
@router.delete("/price/group/{group_no}")
async def unsubscribe_group(
    group_no: str,
    kiwoom_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """
    실시간 시세 그룹 전체 구독 해제 API
    
    - **group_no**: 해제할 그룹 번호
    """
    if not kiwoom_client.connected:
        raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
    
    result = await kiwoom_client.unsubscribe_realtime_price(group_no=group_no)
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    # 상태 관리자 업데이트
    state_manager.remove_subscription(group_no=group_no)
    
    return result


@router.get("/condition/list")
async def get_condition_list(kiwoom_client: SocketClient = Depends(get_socket_client)):
    """조건검색 목록 조회 (ka10171)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_condition_list()
        logger.debug(f"조건검색 목록: {json.dumps(response, indent=2)}")
        
        return response
    except Exception as e:
        logger.error(f"조건검색 목록 조회 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/condition/search")
async def request_condition_search(
    condition_search: ConditionalSearchRequest,
    kiwoom_client: SocketClient = Depends(get_socket_client)
):
    """조건검색 요청 일반 (ka10172)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        result = await kiwoom_client.request_condition_search(
            seq=condition_search.seq,
            search_type=condition_search.search_type,
            market_type=condition_search.market_type,
            cont_yn=condition_search.cont_yn,
            next_key=condition_search.next_key
        )
        
        return result
    except Exception as e:
        logger.error(f"조건검색 요청 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/condition/realtime")
async def request_realtime_condition(
    condition_search: ConditionalSearch,
    kiwoom_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """조건검색 요청 실시간 (ka10173)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        result = await kiwoom_client.request_realtime_condition(
            condition_search.seq,
            condition_search.search_type,
            condition_search.market_type
        )
        
        # 상태 관리자 업데이트
        state_manager.add_condition_subscription(condition_search.seq)
        
        return {"status": "success", "message": "실시간 조건검색 요청 완료", "data": result}
    except Exception as e:
        logger.error(f"실시간 조건검색 요청 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/condition/cancel")
async def cancel_realtime_condition(
    seq: str = Query(..., description="조건검색식 일련번호"),
    kiwoom_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """조건검색 실시간 해제 (ka10174)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        result = await kiwoom_client.cancel_realtime_condition(seq)
        
        # 상태 관리자 업데이트
        state_manager.remove_condition_subscription(seq)
        
        return {"status": "success", "message": f"실시간 조건검색 해제 완료 (조건번호: {seq})"}
    except Exception as e:
        logger.error(f"실시간 조건검색 해제 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    