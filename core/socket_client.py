import asyncio
import json
import logging
import time
from typing import List, Optional
from datetime import datetime
import requests
import websockets
from fastapi import WebSocket, Depends
from config import settings
from dependency_injector.wiring import inject, Provide
from container.token_di import TokenContainer
from core.token_client import TokenGenerator
from db.redis_client import get_hash_data, get_redis_connection

REAL_HOST = 'https://api.kiwoom.com'
MOCK_HOST = 'https://mockapi.kiwoom.com'
REAL_SOCKET = 'wss://api.kiwoom.com:10000/api/dostk/websocket'
MOCK_SOCKET = 'wss://mockapi.kiwoom.com:10000/api/dostk/websocket'

logger = logging.getLogger(__name__)

class SocketClient():
    """키움 API와 통신하는 개선된 클라이언트 (recv 동시성 문제 완전 해결)"""
    
    def __init__(self, 
                real=settings.KIWOOM_REAL_SERVER,
                token_generator: TokenGenerator = Depends(Provide[TokenContainer.token_generator])):
        # 기본 설정
        self.host = REAL_HOST if real else MOCK_HOST
        self.socket_uri = REAL_SOCKET if real else MOCK_SOCKET
        self.app_key = settings.KIWOOM_APP_KEY
        self.sec_key = settings.KIWOOM_SECRET_KEY
        self.token = token_generator.get_token()
        self.token_generator = token_generator
        
        # WebSocket 관련
        self.websocket = None
        self.connected = False
        self.keep_running = True
        
        # 로거
        self.logger = logging.getLogger(__name__)
        
        # 실시간 데이터 관리
        self.registered_groups = []
        self.registered_items = {}
        self.websocket_clients = []
        
        # 태스크 관리
        self.receive_task = None
        self.monitor_task = None
        
        # 동기화 락
        self._connect_lock = asyncio.Lock()
        self._receive_lock = asyncio.Lock()
        self._reconnect_lock = asyncio.Lock()
        
        # 연결 상태 관리
        self.last_connected_time = 0
        self.reconnect_attempts = 0
        self.is_reconnecting = False
        
        # 응답 대기
        self.response_futures = {}
        

        
        # 핸들러
        self.realtime_handler = None

        # 구독 정보 저장용
        self.saved_subscriptions = {
            "groups": {},
            "conditions": []
    }

    @inject
    async def initialize(self, 
                        token_generator: TokenGenerator = Depends(Provide[TokenContainer.token_generator]),
                        realtime_handler = None):
        """클라이언트 초기화 및 연결"""
        try:
            self.token = token_generator.get_token()
            self.token_generator = token_generator
            self.realtime_handler = realtime_handler
            
            success = await self.connect()
            
            if success:
                # 연결 모니터링 시작
                self.monitor_task = asyncio.create_task(self.monitor_connection())
            
            return success
        except Exception as e:
            logger.error(f"초기화 실패: {str(e)}")
            return False

    # connect 메서드 수정
    async def connect(self):
        """WebSocket 서버에 연결 (구독 복원 기능 추가)"""
        async with self._connect_lock:
            try:
                logger.info(f"키움 WebSocket 서버 연결 시도: {self.socket_uri}")
                
                # 연결 전 현재 구독 정보 저장
                if self.registered_items or self.registered_groups:
                    await self.save_subscriptions()
                
                # 1. 기존 연결 완전 정리
                await self._cleanup_connection()
                
                # 2. 새 연결 생성
                self.websocket = await websockets.connect(self.socket_uri)
                self.connected = True
                self.last_connected_time = time.time()
                self.reconnect_attempts = 0
                logger.info("키움 WebSocket 서버에 연결되었습니다.")

                # 3. 로그인
                param = {
                    'trnm': 'LOGIN',
                    'token': self.token
                }
                logger.info('실시간 시세 서버로 로그인 패킷을 전송합니다.')
                await self.send_message(message=param)
                
                # 4. 로그인 응답 대기
                await asyncio.sleep(0.5)
                
                # 5. 수신 태스크 시작
                if not self.receive_task or self.receive_task.done():
                    self.receive_task = asyncio.create_task(self._receive_messages_wrapper())
                    logger.info("새로운 수신 태스크 시작")
                
                # 6. 이전 구독 정보 복원
                if hasattr(self, 'saved_subscriptions') and self.saved_subscriptions:
                    # 로그인 완료 후 잠시 대기
                    await asyncio.sleep(1.0)
                    # 구독 복원 시작
                    asyncio.create_task(self.restore_subscriptions())
                    

                return True
                
            except Exception as e:
                self.connected = False
                logger.error(f'키움 WebSocket 연결 오류: {str(e)}')
                return False
        
    async def _cleanup_connection(self):
        """기존 연결 완전 정리"""
        # 1. 수신 태스크 정리
        if self.receive_task and not self.receive_task.done():
            logger.info("기존 수신 태스크 정리 중...")
            self.receive_task.cancel()
            try:
                await asyncio.wait_for(self.receive_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                logger.info("수신 태스크 정리 완료")
            except Exception as e:
                logger.error(f"수신 태스크 정리 중 오류: {e}")
            self.receive_task = None
        
        # 2. WebSocket 연결 정리
        if self.websocket:
            logger.info("기존 WebSocket 연결 정리 중...")
            try:
                await self.websocket.close()
            except Exception as e:
                logger.debug(f"WebSocket 정리 중 오류: {e}")
            self.websocket = None
        
        # 3. 상태 초기화
        self.connected = False
        
    async def start_keep_alive(self):
        """Keep-Alive 메시지 주기적 전송"""
        while self.keep_running and self.connected:
            try:
                if self.websocket and not self.websocket.closed:
                    # Ping 메시지 전송
                    pong_waiter = await self.websocket.ping()
                    
                    # Pong 응답 대기 (타임아웃 5초)
                    try:
                        await asyncio.wait_for(pong_waiter, timeout=5.0)
                        logger.debug("Ping-Pong 성공")
                    except asyncio.TimeoutError:
                        logger.warning("Pong 응답 없음 - 연결 상태 확인 필요")
                        self.connected = False
                        break
                
                # 설정된 간격으로 대기 (기본 30초)
                await asyncio.sleep(self.keep_alive_interval)
                
            except Exception as e:
                logger.error(f"Keep-alive 중 오류: {e}")
                self.connected = False
                break
        
        logger.info("Keep-alive 종료")
    
    
    async def _receive_messages_wrapper(self):
        """수신 태스크 래퍼 (단일 인스턴스 보장)"""
        try:
            await self.receive_messages()
        except Exception as e:
            logger.error(f"수신 태스크 오류: {e}")
        finally:
            logger.info("수신 태스크 종료")

    async def receive_messages(self):
        """키움 서버로부터 메시지 수신 (개선된 버전)"""
        logger.info("메시지 수신 시작")
        
        while self.keep_running:
            try:
                # 연결 상태 확인
                if not self.connected or not self.websocket:
                    logger.warning("연결되지 않았습니다.")
                    if not self.is_reconnecting:
                        asyncio.create_task(self._handle_disconnection())
                    await asyncio.sleep(5)
                    continue
                
                # WebSocket 상태 확인
                if not self._is_websocket_open():
                    logger.warning("WebSocket이 열려있지 않습니다.")
                    self.connected = False
                    continue
                
                # 메시지 수신 (단일 수신 보장)
                async with self._receive_lock:
                    try:
                        raw_message = await asyncio.wait_for(
                            self.websocket.recv(), 
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        # 타임아웃 시 연결 확인
                        if await self._check_connection():
                            continue
                        else:
                            self.connected = False
                            continue
                
                # 메시지 처리
                await self._process_message(raw_message)
                
            except websockets.ConnectionClosed:
                logger.warning('키움 서버에서 연결이 종료되었습니다.')
                self.connected = False
                
            except asyncio.CancelledError:
                logger.info("수신 태스크가 취소되었습니다.")
                break
                
            except Exception as e:
                error_msg = str(e)
                
                if "already running recv" in error_msg:
                    logger.error("recv 동시성 문제 감지 - 재시작 필요")
                    self.connected = False
                    return  # 태스크 종료
                    
                elif "connection is closed" in error_msg.lower():
                    logger.warning("연결이 닫혔습니다")
                    self.connected = False
                    
                else:
                    logger.error(f'메시지 수신 중 오류: {error_msg}')
                    
                await asyncio.sleep(1)
        
        logger.info("메시지 수신 종료")

    def _is_websocket_open(self):
        """WebSocket이 열려있는지 확인"""
        if not self.websocket:
            return False
            
        if hasattr(self.websocket, 'closed') and self.websocket.closed:
            return False
            
        if hasattr(self.websocket, 'state'):
            try:
                state_value = self.websocket.state.value if hasattr(self.websocket.state, 'value') else self.websocket.state
                return state_value == 1  # OPEN
            except:
                return False
                
        return True

    async def _check_connection(self):
        """연결 상태 확인 (ping)"""
        try:
            await self.websocket.ping()
            return True
        except Exception:
            return False

    # _process_message 메서드 수정 (로그인 성공 시 구독 복원)
    async def _process_message(self, raw_message):
        """메시지 처리"""
        try:
            response = json.loads(raw_message)
            trnm = response.get('trnm', '')
            
            # PING 응답
            if trnm == 'PING':
                logger.debug('PING 메시지 수신, PONG 응답')
                await self.send_message(response)
                return
                
            # Future 응답
            if trnm in self.response_futures:
                future = self.response_futures[trnm]
                if not future.done():
                    future.set_result(response)
                return
                
            # 로그인 응답
            if trnm == 'LOGIN':
                if response.get('return_code') != 0:
                    logger.error(f'로그인 실패: {response.get("return_msg")}')
                    self.connected = False
                else:
                    logger.info('로그인 성공')
                    self.connected = True
                    
                    # 로그인 성공 시 구독 복원
                    if hasattr(self, 'saved_subscriptions') and self.saved_subscriptions:
                        asyncio.create_task(self.restore_subscriptions())
                return
                
            # 실시간 데이터
            if self.realtime_handler and trnm == 'REAL':
                await self.realtime_handler.process_real_time_data(response)
            else:
                logger.debug(f'처리되지 않은 메시지: {trnm}')
                
        except json.JSONDecodeError as e:
            logger.error(f'JSON 파싱 오류: {str(e)}')
        except Exception as e:
            logger.error(f'메시지 처리 중 오류: {str(e)}')

    async def save_current_subscriptions(self):
        """현재 구독 정보를 수동으로 저장"""
        await self.save_subscriptions()
        return {
            "status": "success",
            "message": "구독 정보가 저장되었습니다.",
            "saved_data": self.saved_subscriptions
        }

    async def _handle_disconnection(self):
        """연결 끊김 처리"""
        if self.is_reconnecting:
            return
            
        self.is_reconnecting = True
        try:
            await self.try_reconnect()
        finally:
            self.is_reconnecting = False

    async def try_reconnect(self, max_retries=5, retry_delay=1):
        """재연결 시도"""
        async with self._reconnect_lock:
            for attempt in range(1, max_retries + 1):
                if self.connected:
                    logger.info("이미 연결되어 있습니다.")
                    return True
                
                wait_time = min(retry_delay * attempt, 60)
                logger.info(f"재연결 시도 {attempt}/{max_retries} - {wait_time}초 후 시도")
                
                if attempt > 1:  # 첫 시도는 즉시
                    await asyncio.sleep(wait_time)
                
                try:
                    # 토큰 갱신 확인
                    current_time = time.time()
                    if current_time - self.last_connected_time > 3600:
                        logger.info("토큰 갱신 필요")
                        if self.token_generator:
                            self.token = self.token_generator.get_token()
                    
                    # 재연결
                    success = await self.connect()
                    
                    if success:
                        logger.info("재연결 성공")
                        self.reconnect_attempts = 0
                        return True
                        
                except Exception as e:
                    logger.error(f"재연결 중 오류: {str(e)}")
            
            logger.error(f"최대 재시도 횟수({max_retries})를 초과했습니다.")
            return False

    async def disconnect(self):
        """연결 종료"""
        logger.info("연결 종료 시작...")
        self.keep_running = False
        
        # 모니터 태스크 정리
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        # 연결 정리
        await self._cleanup_connection()
        
        logger.info("연결 종료 완료")

    async def send_message(self, message):
        """메시지 전송"""
        if not self.connected or not self.websocket:
            logger.warning("연결되지 않은 상태에서 메시지 전송 시도")
            return False
            
        try:
            if not isinstance(message, str):
                message = json.dumps(message)
                
            await self.websocket.send(message)
            logger.debug(f'메시지 전송: {message}')
            return True
            
        except Exception as e:
            logger.error(f'메시지 전송 오류: {str(e)}')
            self.connected = False
            return False

    async def monitor_connection(self):
        """연결 상태 모니터링"""
        while self.keep_running:
            try:
                await asyncio.sleep(60)  # 1분마다 체크
                
                if self.connected and self.websocket:
                    if not await self._check_connection():
                        logger.warning("연결 상태 이상 감지")
                        self.connected = False
                        
                        # 수신 태스크가 살아있는지 확인
                        if not self.receive_task or self.receive_task.done():
                            await self._handle_disconnection()
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"모니터링 중 오류: {e}")

    # 나머지 메서드들은 기존과 동일하게 유지
    # (send_and_wait_for_response, register_real_data, 등등)

    async def send_and_wait_for_response(self, message, trnm, timeout=10.0):
        """메시지를 보내고 특정 trnm에 대한 응답을 기다림"""
        if not self.connected:
            logger.warning("연결이 끊겨 있습니다. 재연결 시도 중...")
            await self.connect()
            
        if not self.connected:
            return {"error": "서버에 연결할 수 없습니다."}
            
        try:
            logger.info(f"현재 등록된 response_futures 목록: {list(self.response_futures.keys())}")
            
            # Future 객체 생성
            future = asyncio.Future()
            
            # 응답 추적을 위해 trnm을 키로 사용
            logger.info(f"{trnm} 응답 대기를 위한 Future 객체 생성")
            self.response_futures[trnm] = future
            
            # 메시지에 trnm 값이 있는지 확인
            msg_trnm = message.get('trnm') if isinstance(message, dict) else None
            logger.info(f"전송할 메시지 trnm: {msg_trnm}, 기다릴 응답 trnm: {trnm}")
            
            # 메시지 전송
            logger.info(f"{trnm} 요청 메시지 전송: {message}")
            result = await self.send_message(message)
            if not result:
                if trnm in self.response_futures:
                    del self.response_futures[trnm]
                logger.error(f"{trnm} 메시지 전송 실패")
                return {"error": "메시지 전송 실패"}
                
            # 응답 대기
            try:
                logger.info(f"{trnm} 응답 대기 시작 (타임아웃: {timeout}초)")
                response = await asyncio.wait_for(future, timeout)
                logger.info(f"{trnm} 응답 수신 성공: {response}")
                return response
            except asyncio.TimeoutError:
                logger.error(f"{trnm} 응답 대기 시간 초과")
                return {"error": f"{trnm} 응답 대기 시간 초과"}
            finally:
                # Future 객체 삭제
                if trnm in self.response_futures:
                    logger.info(f"{trnm} Future 객체 삭제")
                    del self.response_futures[trnm]
                    
        except Exception as e:
            logger.error(f"메시지 전송 및 응답 대기 중 오류: {str(e)}")
            if trnm in self.response_futures:
                del self.response_futures[trnm]
            return {"error": f"메시지 전송 및 응답 대기 중 오류: {str(e)}"}

    async def register_real_data(self, group_number, items, types, refresh=False):
        """그룹에 실시간 데이터 등록"""
        group_no = str(group_number)
        
        # 상태 추적 딕셔너리 업데이트
        if refresh:
            # refresh가 True면 기존 항목 초기화
            self.registered_items[group_no] = {}
        else:
            # 딕셔너리가 없으면 초기화
            if group_no not in self.registered_items:
                self.registered_items[group_no] = {}
        
        # 각 종목과 타입 기록
        for item in items:
            if item not in self.registered_items[group_no]:
                self.registered_items[group_no][item] = []
            
            for type_code in types:
                if type_code not in self.registered_items[group_no][item]:
                    self.registered_items[group_no][item].append(type_code)
        
        # 실제 등록 요청
        result = await self.send_message({ 
            'trnm': 'REG',
            'grp_no': group_no,
            'refresh': '1' if refresh else '0',
            'data': [{ 
                'item': items,
                'type': types,
            }]
        })
        
        logger.info(f"그룹 {group_no} 등록 상태: {self.registered_items[group_no]}")
        return result

    async def remove_items_from_group(self, group_number, items, types):
        """그룹에서 특정 종목 삭제"""
        group_no = str(group_number)
        
        # 상태 추적 딕셔너리 업데이트
        if group_no in self.registered_items:
            for item in items:
                if item in self.registered_items[group_no]:
                    for type_code in types:
                        if type_code in self.registered_items[group_no][item]:
                            self.registered_items[group_no][item].remove(type_code)
                    
                    # 종목에 등록된 타입이 없으면 종목 자체를 삭제
                    if not self.registered_items[group_no][item]:
                        del self.registered_items[group_no][item]
        
        # 실제 해제 요청
        result = await self.send_message({ 
            'trnm': 'REMOVE',
            'grp_no': group_no,
            'data': [{ 
                'item': items,
                'type': types,
            }]
        })
        
        logger.info(f"종목 삭제 후 그룹 {group_no} 등록 상태: {self.registered_items.get(group_no, {})}")
        return result

    async def unregister_group(self, group_number):
        """그룹 전체 해제"""
        group_no = str(group_number)
        
        # 상태 추적 딕셔너리에서 그룹 삭제
        if group_no in self.registered_items:
            del self.registered_items[group_no]
        
        # 실제 해제 요청
        result = await self.send_message({ 
            'trnm': 'UNREG',
            'grp_no': group_no,
        })
        
        logger.info(f"그룹 {group_no} 전체가 해제되었습니다.")
        return result

    async def subscribe_realtime_price(self, group_no="1", items=None, data_types=None, refresh=True):
        """
        실시간 시세 정보 구독 함수
        
        Args:
            group_no (str): 그룹 번호
            items (list): 종목 코드 리스트 (예: ["005930", "000660"])
            data_types (list): 데이터 타입 리스트 (예: ["0D", "0B"])
            refresh (bool): 새로고침 여부 (True: 기존 등록 초기화, False: 기존에 추가)
        
        Returns:
            dict: 요청 결과
        """
        if not self.connected:
            logger.error("키움 API에 연결되어 있지 않습니다.")
            return {"error": "키움 API에 연결되어 있지 않습니다."}
        
        # 기본값 설정
        if items is None:
            items = []
        
        if data_types is None:
            data_types = ["0D"]  # 기본적으로 현재가 구독
        
        try:
            # 요청 데이터 구성
            request_data = {
                'trnm': 'REG',                      # 등록 명령
                'grp_no': str(group_no),            # 그룹 번호
                'refresh': '1' if refresh else '0', # 새로고침 여부
                'data': [{
                    'item': items,                  # 종목 코드 리스트
                    'type': data_types              # 데이터 타입 리스트
                }]
            }
            
            # 상태 추적 딕셔너리 업데이트
            if refresh:
                # 새로고침인 경우 기존 항목 초기화
                self.registered_items[str(group_no)] = {}
            else:
                # 딕셔너리가 없으면 초기화
                if str(group_no) not in self.registered_items:
                    self.registered_items[str(group_no)] = {}
            
            # 각 종목과 타입 기록
            for item in items:
                if item not in self.registered_items[str(group_no)]:
                    self.registered_items[str(group_no)][item] = []
                
                for type_code in data_types:
                    if type_code not in self.registered_items[str(group_no)][item]:
                        self.registered_items[str(group_no)][item].append(type_code)
            
            # 요청 전송
            logger.info(f"실시간 시세 구독 요청: 그룹={group_no}, 종목={items}, 타입={data_types}")
            result = await self.send_message(request_data)
            
            if result:
                return {
                    "status": "success", 
                    "message": "실시간 시세 구독 요청 완료",
                    "group_no": group_no,
                    "items": items,
                    "types": data_types
                }
            else:
                return {"error": "실시간 시세 구독 요청 실패"}
                
        except Exception as e:
            logger.error(f"실시간 시세 구독 오류: {str(e)}")
            return {"error": f"실시간 시세 구독 오류: {str(e)}"}

    async def unsubscribe_realtime_price(self, group_no="1", items=None, data_types=None):
        """
        실시간 시세 정보 구독 해제 함수
        
        Args:
            group_no (str): 그룹 번호 (필수)
            items (list): 종목 코드 리스트 (예: ["005930", "000660"]). None이면 그룹 전체 해제
            data_types (list): 데이터 타입 리스트 (예: ["0D", "0B"]). None이면 지정된 종목의 모든 타입 해제
        
        Returns:
            dict: 요청 결과
        """
        if not self.connected:
            logger.error("키움 API에 연결되어 있지 않습니다.")
            return {"error": "키움 API에 연결되어 있지 않습니다."}
        
        try:
            # 그룹 번호 문자열 변환
            group_no = str(group_no)
            
            # 그룹이 등록되어 있는지 확인
            if group_no not in self.registered_items:
                logger.warning(f"그룹 {group_no}에 등록된 데이터가 없습니다.")
                return {
                    "status": "warning", 
                    "message": f"그룹 {group_no}에 등록된 데이터가 없습니다."
                }
            
            # items, data_types이 None이면 그룹 전체 삭제
            if items is None and data_types is None:
                # 요청 데이터 구성
                request_data = {
                    'trnm': 'UNREG',             # 등록 해제 명령
                    'grp_no': group_no            # 그룹 번호
                }
                
                # 요청 전송
                logger.info(f"실시간 시세 구독 해제 요청: 그룹={group_no} (전체 해제)")
                result = await self.send_message(request_data)
                
                # 상태 추적 딕셔너리 업데이트
                if result:
                    del self.registered_items[group_no]
                    return {
                        "status": "success", 
                        "message": f"그룹 {group_no} 실시간 시세 구독 해제 완료 (전체)",
                        "group_no": group_no
                    }
                else:
                    return {"error": "실시간 시세 구독 해제 요청 실패"}
            
            # 특정 종목과 타입 해제
            else:
                # items가 제공되었는지 확인
                if not items:
                    return {"error": "종목 코드가 제공되지 않았습니다."}
                
                # 종목이 등록되어 있는지 확인
                invalid_items = [item for item in items if item not in self.registered_items[group_no]]
                if invalid_items:
                    logger.warning(f"그룹 {group_no}에 등록되지 않은 종목: {invalid_items}")
                    return {
                        "status": "warning", 
                        "message": f"그룹 {group_no}에 등록되지 않은 종목이 있습니다: {invalid_items}"
                    }
                
                # data_types가 None이면 해당 종목의 모든 타입 가져오기
                if data_types is None:
                    data_types_by_item = {}
                    all_data_types = set()
                    
                    for item in items:
                        if item in self.registered_items[group_no]:
                            data_types_by_item[item] = self.registered_items[group_no][item].copy()
                            all_data_types.update(data_types_by_item[item])
                    
                    # 모든 종목에 대해 모든 타입 해제
                    data_types = list(all_data_types)
                else:
                    # 타입이 등록되어 있는지 확인
                    for item in items:
                        invalid_types = [t for t in data_types if t not in self.registered_items[group_no][item]]
                        if invalid_types:
                            logger.warning(f"종목 {item}에 등록되지 않은 타입: {invalid_types}")
                            return {
                                "status": "warning", 
                                "message": f"종목 {item}에 등록되지 않은 타입이 있습니다: {invalid_types}"
                            }
                
                # 요청 데이터 구성
                request_data = {
                    'trnm': 'REMOVE',           # 등록 해제 명령
                    'grp_no': group_no,         # 그룹 번호
                    'data': [{
                        'item': items,          # 종목 코드 리스트
                        'type': data_types      # 데이터 타입 리스트
                    }]
                }
                
                # 요청 전송
                logger.info(f"실시간 시세 구독 해제 요청: 그룹={group_no}, 종목={items}, 타입={data_types}")
                result = await self.send_message(request_data)
                
                # 상태 추적 딕셔너리 업데이트
                if result:
                    for item in items:
                        if item in self.registered_items[group_no]:
                            for type_code in data_types:
                                if type_code in self.registered_items[group_no][item]:
                                    self.registered_items[group_no][item].remove(type_code)
                            
                            # 종목에 등록된 타입이 없으면 종목 자체를 삭제
                            if not self.registered_items[group_no][item]:
                                del self.registered_items[group_no][item]
                    
                    # 그룹에 등록된 종목이 없으면 그룹 자체를 삭제
                    if not self.registered_items[group_no]:
                        del self.registered_items[group_no]
                    
                    return {
                        "status": "success", 
                        "message": "실시간 시세 구독 해제 완료",
                        "group_no": group_no,
                        "items": items,
                        "types": data_types
                    }
                else:
                    return {"error": "실시간 시세 구독 해제 요청 실패"}
                
        except Exception as e:
            logger.error(f"실시간 시세 구독 해제 오류: {str(e)}")
            return {"error": f"실시간 시세 구독 해제 오류: {str(e)}"}

    async def get_condition_list(self):
        """조건검색 목록 조회 (ka10171)"""
        if not self.connected:
            logger.error("키움 API에 연결되어 있지 않습니다.")
            return {"error": "키움 API에 연결되어 있지 않습니다."}
        
        try:
            # 조건검색 목록 요청 메시지 작성
            request_data = {
                'trnm': 'CNSRLST'  # TR명 (조건검색 목록 조회)
            }
            
            # 요청 전송 및 응답 대기
            response = await self.send_and_wait_for_response(request_data, 'CNSRLST', timeout=10.0)
            
            # 오류 확인
            if isinstance(response, dict) and "error" in response:
                return response
                
            return response
            
        except Exception as e:
            logger.error(f"조건검색 목록 조회 오류: {str(e)}")
            return {"error": f"조건검색 목록 조회 오류: {str(e)}"}

    async def request_condition_search(self, seq="4", search_type="0", market_type="K", cont_yn="N", next_key=""):
        """조건검색 요청 일반 (ka10172)"""
        if not self.connected:
            logger.error("키움 API에 연결되어 있지 않습니다.")
            return {"error": "키움 API에 연결되어 있지 않습니다."}
        
        try:
            # 조건검색 요청 메시지 작성
            request_data = {
                'trnm': 'CNSRREQ',  # TR명 (조건검색 요청 일반)
                'seq': seq,  # 조건검색식 일련번호
                'search_type': search_type,  # 조회타입 (0: 일반조건검색)
                'stex_tp': market_type,  # K: KRX
                'cont_yn': cont_yn,  # 연속조회 여부
                'next_key': next_key  # 연속조회 키
            }
            
            # 요청 전송 및 응답 대기
            response = await self.send_and_wait_for_response(request_data, 'CNSRREQ', timeout=20.0)
            
            # 오류 확인
            if isinstance(response, dict) and "error" in response:
                return response
                
            return response
            
        except Exception as e:
            logger.error(f"조건검색 요청 오류: {str(e)}")
            return {"error": f"조건검색 요청 오류: {str(e)}"}

    async def request_realtime_condition(self, seq, search_type="1", market_type="K"):
        """조건검색 요청 실시간 (ka10173)"""
        if not self.connected:
            logger.error("키움 API에 연결되어 있지 않습니다.")
            return {"error": "키움 API에 연결되어 있지 않습니다."}
        
        try:
            # 실시간 조건검색 요청 메시지 작성
            request_data = {
                'trnm': 'CNSRREQ',  # TR명 (조건검색 요청 실시간)
                'seq': seq,  # 조건검색식 일련번호
                'search_type': search_type,  # 조회타입 (1: 조건검색+실시간조건검색)
                'stex_tp': market_type  # K: KRX
            }
            
            # 요청 전송 및 응답 대기
            response = await self.send_and_wait_for_response(request_data, 'CNSRREQ', timeout=10.0)
            
            # 오류 확인
            if isinstance(response, dict) and "error" in response:
                return response
            
            # 실시간 조건검색 그룹 등록
            condition_group = f"cond_{seq}"
            if condition_group not in self.registered_groups:
                self.registered_groups.append(condition_group)
            
            return response
            
        except Exception as e:
            logger.error(f"실시간 조건검색 요청 오류: {str(e)}")
            return {"error": f"실시간 조건검색 요청 오류: {str(e)}"}

    async def cancel_realtime_condition(self, seq):
        """조건검색 실시간 해제 (ka10174)"""
        if not self.connected:
            logger.error("키움 API에 연결되어 있지 않습니다.")
            return {"error": "키움 API에 연결되어 있지 않습니다."}
        
        try:
            # 실시간 조건검색 해제 메시지 작성
            request_data = {
                'trnm': 'CNSRCNC',  # TR명 (조건검색 실시간 해제)
                'seq': seq  # 조건검색식 일련번호
            }
            
            # 요청 전송 및 응답 대기
            response = await self.send_and_wait_for_response(request_data, 'CNSRCNC', timeout=10.0)
            
            # 오류 확인
            if isinstance(response, dict) and "error" in response:
                return response
                
            # 실시간 조건검색 그룹 제거
            condition_group = f"cond_{seq}"
            if condition_group in self.registered_groups:
                self.registered_groups.remove(condition_group)
            
            return response
            
        except Exception as e:
            logger.error(f"실시간 조건검색 해제 오류: {str(e)}")
            return {"error": f"실시간 조건검색 해제 오류: {str(e)}"}

    async def handle_realtime_data(self, data):
        """
        실시간 데이터 수신 처리
        
        Args:
            data (dict): 수신된 실시간 데이터
        """
        try:
            if not data or "trnm" not in data or data["trnm"] != "REAL":
                return
            
            # 그룹 번호, 종목 코드, 데이터 타입 추출
            item = data.get("item", "")
            type_code = data.get("type", "")
            values = data.get("values", {})
            
            # 디버깅 로그
            logger.debug(f"실시간 데이터 수신:  종목={item}, 타입={type_code}")
            
            # 데이터 타입별 처리
            if type_code == "0D":  # 현재가 정보
                # 필요한 필드 추출 (필드명은 키움 API 문서 참조)
                price = values.get("81", 0)  # 현재가
                change = values.get("86", 0)  # 전일대비
                change_ratio = values.get("25", 0)  # 등락율
                volume = values.get("13", 0)  # 거래량
                
                # 실시간 데이터 구조화
                realtime_data = {
                    "type": "realtime_price",
                    "item": item,
                    "data": {
                        "price": price,
                        "change": change,
                        "change_ratio": change_ratio,
                        "volume": volume,
                        "timestamp": int(time.time() * 1000)  # 밀리초 타임스탬프
                    }
                }
                
                # 클라이언트에게 데이터 전송
                await self.broadcast_to_clients(realtime_data)
                
            elif type_code == "0B":  # 체결 정보
                # 체결 데이터 처리
                pass
                
            # 기타 데이터 타입 처리
            # ...
            
            # Redis에 데이터 저장
            redis_client = get_redis_connection()
            # store_realtime_market_data(redis_client, data)
            
            # 클라이언트에 데이터 전송
            await self.broadcast_to_clients(data)

        except Exception as e:
            logger.error(f"실시간 데이터 처리 중 오류: {str(e)}")

    async def broadcast_to_clients(self, data):
        """모든 연결된 WebSocket 클라이언트에게 데이터 브로드캐스트"""
        if not self.websocket_clients:
            return
            
        # 연결이 끊어진 클라이언트 제거
        disconnected_clients = []
        
        for client in self.websocket_clients:
            try:
                await client.send_json(data)
            except Exception as e:
                logger.warning(f"클라이언트 전송 실패: {e}")
                disconnected_clients.append(client)
        
        # 연결이 끊어진 클라이언트 제거
        for client in disconnected_clients:
            self.websocket_clients.remove(client)

    # 실시간 조건검색 이벤트 처리 메서드
    def handle_condition_realtime_event(self, data):
        """실시간 조건검색 이벤트 처리"""
        try:
            if data and "trnm" in data and data["trnm"] == "REAL":
                # 조건검색 데이터 처리
                values = data.get("values", {})
                code = values.get("9001", "")  # 종목코드
                signal_type = values.get("841", "")  # 신호종류
                insert_delete_type = values.get("843", "")  # 삽입삭제 구분
                
                # 조건검색 결과를 그룹으로 전달
                condition_group = f"cond_{self.extract_condition_seq(data)}"
                
                if condition_group in self.registered_groups:
                    message = {
                        "type": "condition_realtime",
                        "code": code,
                        "signal_type": signal_type,
                        "insert_delete_type": insert_delete_type,
                        "data": values
                    }
                    
                    # WebSocket을 통해 클라이언트에게 전달
                    asyncio.create_task(self.broadcast_to_clients(message))
        except Exception as e:
            logger.error(f"실시간 조건검색 이벤트 처리 오류: {str(e)}")

    # 조건검색 일련번호 추출 메서드
    def extract_condition_seq(self, data):
        """실시간 데이터에서 조건검색 일련번호 추출"""
        # 실시간 데이터에서 조건검색 일련번호를 추출하는 로직 구현
        return data.get("seq", "unknown")

    async def save_subscriptions(self):
        """현재 구독 상태를 저장"""
        self.saved_subscriptions = {
            "groups": {},
            "conditions": []
        }
        
        # 그룹별 구독 정보 저장
        for group_no, items_dict in self.registered_items.items():
            if items_dict:  # 비어있지 않은 그룹만
                all_items = list(items_dict.keys())
                all_types = set()
                for item_types in items_dict.values():
                    all_types.update(item_types)
                
                self.saved_subscriptions["groups"][group_no] = {
                    "items": all_items,
                    "types": list(all_types)
                }
        
        # 조건검색 구독 정보 저장
        self.saved_subscriptions["conditions"] = self.registered_groups.copy()
        
        logger.info(f"구독 정보 저장 완료: {self.saved_subscriptions}")

    async def restore_subscriptions(self):
        """저장된 구독 정보를 복원"""
        if not hasattr(self, 'saved_subscriptions') or not self.saved_subscriptions:
            logger.info("복원할 구독 정보가 없습니다.")
            return
        
        logger.info("이전 구독 정보 복원 시작...")
        restored_count = 0
        
        try:
            # 그룹별 구독 복원
            for group_no, sub_info in self.saved_subscriptions.get("groups", {}).items():
                items = sub_info.get("items", [])
                types = sub_info.get("types", [])
                
                if items and types:
                    logger.info(f"그룹 {group_no} 구독 복원: 종목={items}, 타입={types}")
                    
                    result = await self.subscribe_realtime_price(
                        group_no=group_no,
                        items=items,
                        data_types=types,
                        refresh=True  # 그룹 전체를 다시 설정
                    )
                    
                    if "error" not in result:
                        restored_count += 1
                        logger.info(f"그룹 {group_no} 복원 성공")
                    else:
                        logger.error(f"그룹 {group_no} 복원 실패: {result['error']}")
                    
                    # 요청 간 짧은 대기
                    await asyncio.sleep(0.1)
            
            # 조건검색 구독 복원
            for condition_group in self.saved_subscriptions.get("conditions", []):
                if condition_group.startswith("cond_"):
                    seq = condition_group.replace("cond_", "")
                    logger.info(f"조건검색 {seq} 구독 복원")
                    
                    result = await self.request_realtime_condition(seq)
                    
                    if "error" not in result:
                        restored_count += 1
                        logger.info(f"조건검색 {seq} 복원 성공")
                    else:
                        logger.error(f"조건검색 {seq} 복원 실패")
            
            logger.info(f"구독 복원 완료: {restored_count}개 항목 복원됨")
            
        except Exception as e:
            logger.error(f"구독 복원 중 오류: {e}")
