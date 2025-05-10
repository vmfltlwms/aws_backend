import logging
import json
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from core.socket_client import SocketClient
from services.realtime_services import RealtimeStateManager
from services.realtime_handler import RealtimeHandler

from dependencies import get_socket_client, get_realtime_state_manager, get_realtime_handler

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/realdata")
async def market_websocket(
    websocket: WebSocket,
    socket_client: SocketClient = Depends(get_socket_client),
    state_manager: RealtimeStateManager = Depends(get_realtime_state_manager),
    realtime_handler: RealtimeHandler = Depends(get_realtime_handler)
):
    """시장 데이터 웹소켓 연결"""
    # 웹소켓 연결 수락 및 클라이언트 등록
    await websocket.accept()
    await realtime_handler.register_client(websocket)
    
    # 클라이언트 식별 및 그룹 정보 저장 (구독 추적용)
    client_id = str(id(websocket))
    client_groups = []
    
    try:
        while True:
            # 클라이언트로부터 메시지 수신
            data = await websocket.receive_text()
            print("="*20)
            print(f"Received data: {data}")
            print("="*20)
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
                        result = await socket_client.register_real_data(group_no, items, types, refresh)
                        # 등록이 성공하면 클라이언트를 해당 그룹에 추가
                        if result:
                            if group_no not in client_groups:
                                client_groups.append(group_no)
                            
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
                        result = await socket_client.get_condition_list()
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
                        result = await socket_client.request_condition_search(
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
                            result = await socket_client.request_realtime_condition(seq, search_type, market_type)
                            # 등록이 성공하면 실시간 조건검색 그룹에 추가
                            condition_group = f"cond_{seq}"
                            if condition_group not in client_groups:
                                client_groups.append(condition_group)
                                
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
                            result = await socket_client.cancel_realtime_condition(seq)
                            # 해당 조건검색 그룹에서 제거
                            condition_group = f"cond_{seq}"
                            if condition_group in client_groups:
                                client_groups.remove(condition_group)
                                
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
                            result = await socket_client.subscribe_realtime_price(
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
                                if group_no not in client_groups:
                                    client_groups.append(group_no)
                                
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
                        result = await socket_client.unsubscribe_realtime_price(
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
                            if items is None and group_no in client_groups:
                                client_groups.remove(group_no)
                            
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
                                    "client_id": client_id,
                                    "groups": client_groups
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
        # 연결 종료 시 클라이언트 등록 해제
        await realtime_handler.unregister_client(websocket)
        logger.info(f"클라이언트 연결 종료: {client_id}")
    except Exception as e:
        logger.error(f"웹소켓 통신 중 예외 발생: {str(e)}")
        try:
            await realtime_handler.unregister_client(websocket)
        except:
            pass