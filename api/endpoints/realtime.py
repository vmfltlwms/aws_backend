import logging
import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from core.kiwoom_client import KiwoomClient
from core.websocket import ConnectionManager
from services.realtime_services import RealtimeStateManager
from models.stock import ConditionalSearch, ConditionalSearchRequest, \
                        RealtimePriceRequest, RealtimePriceUnsubscribeRequest
from dependencies import get_kiwoom_client, get_connection_manager, get_realtime_state_manager

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/price/subscribe",
            summary="실시간 구독 등록",
            description="실시간 구독 등록")
async def subscribe_realtime_price(
    request: RealtimePriceRequest,
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """
    실시간 시세 정보 구독 API
    
    - **group_no**: 그룹 번호
    - **items**: 종목 코드 리스트 (예: ["005930", "000660"])
    - **data_types**: 데이터 타입 리스트 (예: ["0D"])
    - **refresh**: 새로고침 여부 (True: 기존 등록 초기화, False: 기존에 추가)
    """
    if not kiwoom_client.connected:
        raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
    
    result = await kiwoom_client.subscribe_realtime_price(
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
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client),
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
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client),
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
async def get_condition_list(kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)):
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
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
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
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client),
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
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client),
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
    

@router.websocket("/ws/market")
async def market_websocket(
    websocket: WebSocket,
    connection_manager: ConnectionManager = Depends(get_connection_manager),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager)
):
    """시장 데이터 웹소켓 연결"""
    connection_info = await connection_manager.connect(websocket)
    
    try:
        while True:
            # 클라이언트로부터 메시지 수신
            data = await websocket.receive_text()
            
            try:
                command = json.loads(data)
                
                # 클라이언트 명령 처리
                if command.get("action") == "register":
                    # 실시간 데이터 등록 명령 처리
                    group_no = command.get("group_no")
                    items = command.get("items", [])
                    types = command.get("types", [])
                    refresh = command.get("refresh", False)
                    
                    if group_no and items and types:
                        result = await kiwoom_client.register_real_data(group_no, items, types, refresh)
                        # 등록이 성공하면 클라이언트를 해당 그룹에 추가
                        if result:
                            if group_no not in connection_info["groups"]:
                                connection_info["groups"].append(group_no)
                            
                            # 상태 관리자 업데이트
                            state_manager.add_subscription(group_no, items, types, refresh)
                            
                            await websocket.send_json({"status": "success", "action": "register"})
                        else:
                            await websocket.send_json({"status": "error", "message": "등록 실패"})
                    else:
                        await websocket.send_json({"status": "error", "message": "유효하지 않은 파라미터"})
                
                # 조건검색 명령 처리
                elif command.get("action") == "condition_list":
                    # 조건검색 목록 요청
                    try:
                        result = await kiwoom_client.get_condition_list()
                        await websocket.send_json({"status": "success", "action": "condition_list", "data": result})
                    except Exception as e:
                        await websocket.send_json({"status": "error", "message": f"조건검색 목록 조회 실패: {str(e)}"})
                
                elif command.get("action") == "condition_search":
                    # 조건검색 요청 (일반)
                    seq = command.get("seq", "4")
                    search_type = command.get("search_type", "0")  # 기본값 "0" (일반조건검색)
                    market_type = command.get("market_type", "K")  # 기본값 "K" (KRX)
                    cont_yn = command.get("cont_yn", "N")          # 기본값 "N" (연속조회 아님)
                    next_key = command.get("next_key", "")         # 기본값 "" (연속조회 키 없음)
                    
                    try:
                        result = await kiwoom_client.request_condition_search(
                            seq=seq,
                            search_type=search_type,
                            market_type=market_type,
                            cont_yn=cont_yn,
                            next_key=next_key
                        )
                        await websocket.send_json({"status": "success", "action": "condition_search", "data": result})
                    except Exception as e:
                        await websocket.send_json({"status": "error", "message": f"조건검색 요청 실패: {str(e)}"})
                
                elif command.get("action") == "condition_realtime":
                    # 조건검색 요청 (실시간)
                    seq = command.get("seq")
                    search_type = command.get("search_type", "1")  # 기본값 "1" (조건검색+실시간조건검색)
                    market_type = command.get("market_type", "K")  # 기본값 "K" (KRX)
                    
                    if seq:
                        try:
                            result = await kiwoom_client.request_realtime_condition(seq, search_type, market_type)
                            # 등록이 성공하면 실시간 조건검색 그룹에 추가
                            condition_group = f"cond_{seq}"
                            if condition_group not in connection_info["groups"]:
                                connection_info["groups"].append(condition_group)
                                
                            # 상태 관리자 업데이트
                            state_manager.add_condition_subscription(seq)
                            
                            await websocket.send_json({"status": "success", "action": "condition_realtime", "data": result})
                        except Exception as e:
                            await websocket.send_json({"status": "error", "message": f"실시간 조건검색 요청 실패: {str(e)}"})
                    else:
                        await websocket.send_json({"status": "error", "message": "조건검색식 일련번호(seq)가 필요합니다"})
                
                elif command.get("action") == "condition_cancel":
                    # 조건검색 실시간 해제
                    seq = command.get("seq")
                    
                    if seq:
                        try:
                            result = await kiwoom_client.cancel_realtime_condition(seq)
                            # 해당 조건검색 그룹에서 제거
                            condition_group = f"cond_{seq}"
                            if condition_group in connection_info["groups"]:
                                connection_info["groups"].remove(condition_group)
                                
                            # 상태 관리자 업데이트
                            state_manager.remove_condition_subscription(seq)
                            
                            await websocket.send_json({"status": "success", "action": "condition_cancel"})
                        except Exception as e:
                            await websocket.send_json({"status": "error", "message": f"실시간 조건검색 해제 실패: {str(e)}"})
                    else:
                        await websocket.send_json({"status": "error", "message": "조건검색식 일련번호(seq)가 필요합니다"})

                elif command.get("action") == "subscribe_price":
                    # 실시간 시세 구독 처리
                    group_no = command.get("group_no", "1")
                    items = command.get("items", [])
                    data_types = command.get("data_types", ["0D"])
                    refresh = command.get("refresh", True)
                    
                    if not items:
                        await websocket.send_json({
                            "status": "error", 
                            "message": "종목 코드(items)가 필요합니다."
                        })
                    else:
                        try:
                            result = await kiwoom_client.subscribe_realtime_price(
                                group_no=group_no,
                                items=items,
                                data_types=data_types,
                                refresh=refresh
                            )
                            
                            if "error" in result:
                                await websocket.send_json({
                                    "status": "error", 
                                    "message": result["error"]
                                })
                            else:
                                # 구독 성공 시 그룹에 추가
                                if group_no not in connection_info["groups"]:
                                    connection_info["groups"].append(group_no)
                                
                                # 상태 관리자 업데이트
                                state_manager.add_subscription(group_no, items, data_types, refresh)
                                
                                await websocket.send_json({
                                    "status": "success", 
                                    "action": "subscribe_price",
                                    "data": {
                                        "group_no": group_no,
                                        "items": items,
                                        "data_types": data_types
                                    }
                                })
                        except Exception as e:
                            logger.error(f"실시간 시세 구독 처리 오류: {str(e)}")
                            await websocket.send_json({
                                "status": "error", 
                                "message": f"실시간 시세 구독 처리 오류: {str(e)}"
                            })
                elif command.get("action") == "unsubscribe_price":
                    # 실시간 시세 구독 해제 처리
                    group_no = command.get("group_no", "1")
                    items = command.get("items")        # None이면 그룹 전체 해제
                    data_types = command.get("data_types")
                    
                    try:
                        result = await kiwoom_client.unsubscribe_realtime_price(
                            group_no=group_no,
                            items=items,
                            data_types=data_types
                        )
                        
                        if "error" in result:
                            await websocket.send_json({
                                "status": "error", 
                                "message": result["error"]
                            })
                        else:
                            # 구독 해제 성공 시 해당 그룹 연결 정보에서 제거 (그룹 전체 해제인 경우)
                            if items is None and group_no in connection_info["groups"]:
                                connection_info["groups"].remove(group_no)
                            
                            # 상태 관리자 업데이트
                            state_manager.remove_subscription(group_no, items, data_types)
                            
                            await websocket.send_json({
                                "status": "success", 
                                "action": "unsubscribe_price",
                                "data": result
                            })
                    except Exception as e:
                        logger.error(f"실시간 시세 구독 해제 처리 오류: {str(e)}")
                        await websocket.send_json({
                            "status": "error", 
                            "message": f"실시간 시세 구독 해제 처리 오류: {str(e)}"
                        })

                elif command.get("action") == "get_tick_chart":
                    # 틱차트 데이터 요청 처리
                    code = command.get("code")
                    tick_scope = command.get("tick_scope", "1")
                    price_type = command.get("price_type", "1")
                    cont_yn = command.get("cont_yn", "N")
                    next_key = command.get("next_key", "")
                    
                    if not code:
                        await websocket.send_json({
                            "status": "error", 
                            "message": "종목 코드(code)가 필요합니다."
                        })
                    else:
                        try:
                            result = await kiwoom_client.get_tick_chart(
                                code=code,
                                tick_scope=tick_scope,
                                price_type=price_type,
                                cont_yn=cont_yn,
                                next_key=next_key
                            )
                            
                            await websocket.send_json({
                                "status": "success", 
                                "action": "get_tick_chart",
                                "data": result
                            })
                        except Exception as e:
                            logger.error(f"틱차트 요청 처리 오류: {str(e)}")
                            await websocket.send_json({
                                "status": "error", 
                                "message": f"틱차트 요청 처리 오류: {str(e)}"
                            })

                elif command.get("action") == "get_minute_chart":
                    # 분봉차트 데이터 요청 처리
                    code = command.get("code")
                    minute_unit = command.get("minute_unit", "1")
                    price_type = command.get("price_type", "1")
                    cont_yn = command.get("cont_yn", "N")
                    next_key = command.get("next_key", "")
                    
                    if not code:
                        await websocket.send_json({
                            "status": "error", 
                            "message": "종목 코드(code)가 필요합니다."
                        })
                    else:
                        try:
                            result = await kiwoom_client.get_minute_chart(
                                code=code,
                                tic_scope=minute_unit,
                                price_type=price_type,
                                cont_yn=cont_yn,
                                next_key=next_key
                            )
                            
                            await websocket.send_json({
                                "status": "success", 
                                "action": "get_minute_chart",
                                "data": result
                            })
                        except Exception as e:
                            logger.error(f"분봉차트 요청 처리 오류: {str(e)}")
                            await websocket.send_json({
                                "status": "error", 
                                "message": f"분봉차트 요청 처리 오류: {str(e)}"
                            })

                elif command.get("action") == "get_daily_chart":
                    # 일봉차트 데이터 요청 처리
                    code = command.get("code")
                    base_dt = command.get("base_dt", "")
                    price_type = command.get("price_type", "1")
                    cont_yn = command.get("cont_yn", "N")
                    next_key = command.get("next_key", "")
                    
                    if not code:
                        await websocket.send_json({
                            "status": "error", 
                            "message": "종목 코드(code)가 필요합니다."
                        })
                    else:
                        try:
                            result = await kiwoom_client.get_daily_chart(
                                code=code,
                                base_dt=base_dt,
                                price_type=price_type,
                                cont_yn=cont_yn,
                                next_key=next_key
                            )
                            
                            await websocket.send_json({
                                "status": "success", 
                                "action": "get_daily_chart",
                                "data": result
                            })
                        except Exception as e:
                            logger.error(f"일봉차트 요청 처리 오류: {str(e)}")
                            await websocket.send_json({
                                "status": "error", 
                                "message": f"일봉차트 요청 처리 오류: {str(e)}"
                            })

                elif command.get("action") == "get_weekly_chart":
                    # 주봉차트 데이터 요청 처리
                    code = command.get("code")
                    base_dt = command.get("base_dt", "")
                    price_type = command.get("price_type", "1")
                    cont_yn = command.get("cont_yn", "N")
                    next_key = command.get("next_key", "")
                    
                    if not code:
                        await websocket.send_json({
                            "status": "error", 
                            "message": "종목 코드(code)가 필요합니다."
                        })
                    else:
                        try:
                            result = await kiwoom_client.get_weekly_chart(
                                code=code,
                                base_dt=base_dt,
                                price_type=price_type,
                                cont_yn=cont_yn,
                                next_key=next_key
                            )
                            
                            await websocket.send_json({
                                "status": "success", 
                                "action": "get_weekly_chart",
                                "data": result
                            })
                        except Exception as e:
                            logger.error(f"주봉차트 요청 처리 오류: {str(e)}")
                            await websocket.send_json({
                                "status": "error", 
                                "message": f"주봉차트 요청 처리 오류: {str(e)}"
                            })

                elif command.get("action") == "get_monthly_chart":
                    # 월봉차트 데이터 요청 처리
                    code = command.get("code")
                    base_dt = command.get("base_dt", "")
                    price_type = command.get("price_type", "1")
                    cont_yn = command.get("cont_yn", "N")
                    next_key = command.get("next_key", "")
                    
                    if not code:
                        await websocket.send_json({
                            "status": "error", 
                            "message": "종목 코드(code)가 필요합니다."
                        })
                    else:
                        try:
                            result = await kiwoom_client.get_monthly_chart(
                                code=code,
                                base_dt=base_dt,
                                price_type=price_type,
                                cont_yn=cont_yn,
                                next_key=next_key
                            )
                            
                            await websocket.send_json({
                                "status": "success", 
                                "action": "get_monthly_chart",
                                "data": result
                            })
                        except Exception as e:
                            logger.error(f"월봉차트 요청 처리 오류: {str(e)}")
                            await websocket.send_json({
                                "status": "error", 
                                "message": f"월봉차트 요청 처리 오류: {str(e)}"
                            })

                elif command.get("action") == "get_yearly_chart":
                    # 년봉차트 데이터 요청 처리
                    code = command.get("code")
                    base_dt = command.get("base_dt", "")
                    price_type = command.get("price_type", "1")
                    cont_yn = command.get("cont_yn", "N")
                    next_key = command.get("next_key", "")
                    
                    if not code:
                        await websocket.send_json({
                            "status": "error", 
                            "message": "종목 코드(code)가 필요합니다."
                        })
                    else:
                        try:
                            result = await kiwoom_client.get_yearly_chart(
                                code=code,
                                base_dt=base_dt,
                                price_type=price_type,
                                cont_yn=cont_yn,
                                next_key=next_key
                            )
                            
                            await websocket.send_json({
                                "status": "success", 
                                "action": "get_yearly_chart",
                                "data": result
                            })
                        except Exception as e:
                            logger.error(f"년봉차트 요청 처리 오류: {str(e)}")
                            await websocket.send_json({
                                "status": "error", 
                                "message": f"년봉차트 요청 처리 오류: {str(e)}"
                            })

                # 상태 조회 명령
                elif command.get("action") == "get_status":
                    # 현재 구독 상태 조회
                    try:
                        subscriptions = state_manager.get_all_subscriptions()
                        condition_subscriptions = state_manager.get_condition_subscriptions()
                        
                        await websocket.send_json({
                            "status": "success",
                            "action": "get_status",
                            "data": {
                                "subscriptions": subscriptions,
                                "condition_subscriptions": condition_subscriptions,
                                "connection_info": {
                                    "client_id": connection_info["client_id"],
                                    "groups": connection_info["groups"]
                                }
                            }
                        })
                    except Exception as e:
                        logger.error(f"상태 조회 처리 오류: {str(e)}")
                        await websocket.send_json({
                            "status": "error",
                            "message": f"상태 조회 처리 오류: {str(e)}"
                        })
                
                # 기타 명령에 대한 오류 응답
                else:
                    await websocket.send_json({
                        "status": "error",
                        "message": f"지원하지 않는 명령: {command.get('action')}"
                    })
                
            except json.JSONDecodeError:
                await websocket.send_json({"status": "error", "message": "유효하지 않은 JSON 형식"})
            except Exception as e:
                logger.error(f"웹소켓 명령 처리 오류: {str(e)}")
                await websocket.send_json({"status": "error", "message": str(e)})
                
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
        logger.info(f"클라이언트 연결 종료: {connection_info['client_id']}")
    except Exception as e:
        logger.error(f"웹소켓 통신 중 예외 발생: {str(e)}")
        try:
            connection_manager.disconnect(websocket)
        except:
            pass