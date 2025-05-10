import asyncio
import json
import logging
import time
from typing import List
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

class SocketClient() : 
    """키움 API와 통신하는 클라이언트"""
    def __init__(self, 
                real=settings.KIWOOM_REAL_SERVER,
                token_generator: TokenGenerator = Depends(Provide[TokenContainer.token_generator])):
        # 실전투자, 모의투자 선택
        self.host = REAL_HOST if real else MOCK_HOST
        self.socket_uri = REAL_SOCKET if real else MOCK_SOCKET
        self.app_key = settings.KIWOOM_APP_KEY
        self.sec_key = settings.KIWOOM_SECRET_KEY
        self.token = token_generator.get_token()
        self.websocket = None
        self.connected = False
        self.keep_running = True
        self.logger = logging.getLogger(__name__)
        self.registered_groups = []
        # 등록된 종목 추적
        self.registered_items = {}
        
        # 클라이언트 웹소켓 연결 관리
        self.websocket_clients = []  # 타입: List[WebSocket]

        # 이벤트 루프 및 태스크
        self.event_loop = None
        self.connection_task = None
        
        # 연결 상태 관리
        self.last_connected_time = 0
        self.reconnect_attempts = 0
        
        # 응답 대기를 위한 Future 객체 딕셔너리
        self.response_futures = {}
        
        # 실시간 데이터 핸들러
        self.realtime_handler = None

# core/socket_client.py (initialize 메서드 수정)

    @inject
    async def initialize(self, 
                        token_generator: TokenGenerator = Depends(Provide[TokenContainer.token_generator]),
                        realtime_handler = None):
        """클라이언트 초기화 및 연결"""
        try:
            self.token = token_generator.get_token()
            
            # 실시간 데이터 핸들러 설정
            self.realtime_handler = realtime_handler
            
            await self.connect()
            return True
        except Exception as e:
            logger.error(f"초기화 실패: {str(e)}")
            return False

    async def connect(self):
        """키움 WebSocket 서버에 연결"""
        try:
            logger.info(f"키움 WebSocket 서버 연결 시도: {self.socket_uri}")
            self.websocket = await websockets.connect(self.socket_uri)
            self.connected = True
            self.last_connected_time = time.time()
            self.reconnect_attempts = 0
            logger.info("키움 WebSocket 서버에 연결되었습니다.")

            # 로그인 패킷
            param = {
                'trnm': 'LOGIN',
                'token': self.token
            }

            logger.info('실시간 시세 서버로 로그인 패킷을 전송합니다.')
            # 웹소켓 연결 시 로그인 정보 전달
            await self.send_message(message=param)
            
            # 연결 유지를 위한 수신 태스크 시작
            asyncio.create_task(self.receive_messages())

        except Exception as e:
            self.connected = False
            logger.error(f'키움 WebSocket 연결 오류: {str(e)}')
            raise

    # 연결 종료
    async def disconnect(self):
        """키움 서버와의 연결 종료"""
        self.keep_running = False
        if self.websocket:
            try:
                await self.websocket.close()
                logger.info("키움 서버와의 연결이 종료되었습니다.")
            except Exception as e:
                logger.error(f"연결 종료 중 오류: {str(e)}")
        self.connected = False
        self.websocket = None
    

    # 서버에 메시지 전송
    async def send_message(self, message):
        """키움 서버에 메시지 전송"""
        if not self.connected:
            logger.warning("연결이 끊겨 있습니다. 재연결 시도 중...")
            await self.connect()  # 연결이 끊겼다면 재연결
            
        if self.connected:
            try:
                # message가 문자열이 아니면 JSON으로 직렬화
                if not isinstance(message, str):
                    message = json.dumps(message)

                await self.websocket.send(message)
                logger.debug(f'키움 서버로 메시지 전송: {message}')
                return True
            except websockets.ConnectionClosed as e:
                logger.error(f'연결이 닫혔습니다: {str(e)}')
                self.connected = False
                return False
            except Exception as e:
                logger.error(f'메시지 전송 오류: {str(e)}')
                self.connected = False
                return False
        return False
    
    async def send_and_wait_for_response(self, message, trnm, timeout=10.0):
        """메시지를 보내고 특정 trnm에 대한 응답을 기다림"""
        if not self.connected:
            logger.warning("연결이 끊겨 있습니다. 재연결 시도 중...")
            await self.connect()
            
        if not self.connected:
            return {"error": "서버에 연결할 수 없습니다."}
            
        try:
            # 현재 존재하는 Future 확인 로깅
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
        
    # receive_messages 메서드 수정
    async def receive_messages(self):
        """키움 서버로부터 메시지 수신"""
        while self.keep_running:
            try:
                if not self.connected or self.websocket is None:
                    logger.warning("연결이 끊겨 있습니다. 재연결 시도 중...")
                    await self.try_reconnect()
                    continue
                
                # 서버로부터 수신한 메시지를 JSON 형식으로 파싱
                raw_message = await self.websocket.recv()
                response = json.loads(raw_message)
                
                # 로그 추가 (응답 확인용)
                logger.debug(f"수신 메시지 전문: {response}")
                
                # trnm 값 추출
                trnm = response.get('trnm', '')
                
                # PING 응답은 클라이언트에서 처리 (즉시 응답 필요)
                if trnm == 'PING':
                    # PING 응답 처리 (수신값 그대로 송신)
                    logger.debug('PING 메시지 수신, PONG 응답')
                    await self.send_message(response)
                    continue
                    
                # Future 객체가 있는 응답 처리 (CNSRLST, CNSRREQ, CNSRCNC 등)
                if trnm in self.response_futures:
                    logger.info(f'{trnm} 응답 수신, Future 객체에 결과 설정: {response}')
                    future = self.response_futures[trnm]
                    if not future.done():
                        future.set_result(response)
                    continue
                    
                # 로그인 응답 처리
                if trnm == 'LOGIN':
                    if response.get('return_code') != 0:
                        logger.error(f'로그인 실패: {response.get("return_msg")}')
                        await self.disconnect()
                    else:
                        logger.info('로그인 성공')
                    continue
                    
                # 실시간 데이터 처리 (위 조건에 해당하지 않는 메시지)
                if self.realtime_handler:
                    # 실시간 데이터인 경우 바로 process_real_time_data로 전달
                    if trnm == 'REAL':
                        await self.realtime_handler.process_real_time_data(response)
                    else:
                        # 기타 메시지는 로그만 남김
                        logger.info(f'기타 메시지 수신: {trnm} - {response}')
                else:
                    logger.error('realtime_handler가 없습니다')
                    logger.info(f'실시간 시세 서버 응답 수신 (핸들러 없음): {trnm}')
                            
            except websockets.ConnectionClosed:
                logger.warning('키움 서버에서 연결이 종료되었습니다.')
                self.connected = False
                # 재연결 시도
                await self.try_reconnect()
            except json.JSONDecodeError as e:
                logger.error(f'JSON 파싱 오류: {str(e)}')
            except Exception as e:
                logger.error(f'메시지 수신 중 오류: {str(e)}')
                await asyncio.sleep(1)  # 오류 발생 시 잠시 대기
        
    
    # 재연결 시도
    async def try_reconnect(self, max_retries=5, retry_delay=5):
        """연결 끊김 시 재연결 시도"""
        if self.reconnect_attempts >= max_retries:
            logger.error(f"최대 재시도 횟수({max_retries})를 초과했습니다. 재연결을 중단합니다.")
            return False
        
        self.reconnect_attempts += 1
        wait_time = retry_delay * self.reconnect_attempts
        
        logger.info(f"재연결 시도 {self.reconnect_attempts}/{max_retries} - {wait_time}초 후 시도")
        await asyncio.sleep(wait_time)
        
        try:
            # 토큰 갱신이 필요한지 확인 (1시간 지났으면 갱신)
            current_time = time.time()
            if current_time - self.last_connected_time > 3600:  # 1시간 = 3600초
                logger.info("토큰 갱신 필요, 새 토큰 발급 중...")
                self.token = await self.get_token_async()
            
            # 재연결 시도
            await self.connect()
            if self.connected:
                logger.info("재연결 성공")
                return True
        except Exception as e:
            logger.error(f"재연결 실패: {str(e)}")
            
        return False
    
    # 실시간 데이터 등록
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
    
    # 그룹 내 특정 종목 삭제
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
    
    # 그룹 전체 해제
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

    # 조건검색 요청 일반 메서드
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

    # 조건검색 요청 실시간 메서드
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

    # 조건검색 실시간 해제 메서드
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
    
    async def subscribe_realtime_price(self, group_no="1", items=None, data_types=None, refresh=True):
        """
        실시간 시세 정보 구독 함수
        
        Args:
            group_no (str): 그룹 번호
            items (list): 종목 코드 리스트 (예: ["005930", "000660"])
            data_types (list): 데이터 타입 리스트 (예: ["0D", "01"])
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
            if not refresh:  # refresh=False(0)이면 초기화
                self.registered_items[str(group_no)] = {}
            else:  # refresh=True(1)이면 기존 유지
                if str(group_no) not in self.registered_items:
                    self.registered_items[str(group_no)] = {}
            #debug
            print("debug purpose")
            print(self.registered_items)

            # 요청 전송
            logger.info(f"실시간 시세 구독 요청: 그룹={group_no}, 종목={items}, 타입={data_types}")
            result = await self.send_message(request_data)
            
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
                
            elif type_code == "01":  # 체결 정보
                # 체결 데이터 처리
                # ...
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

    async def unsubscribe_realtime_price(self, group_no="1", items=None, data_types=None):
        """
        실시간 시세 정보 구독 해제 함수
        
        Args:
            group_no (str): 그룹 번호 (필수)
            items (list): 종목 코드 리스트 (예: ["005930", "000660"]). None이면 그룹 전체 해제
            data_types (list): 데이터 타입 리스트 (예: ["0D", "01"]). None이면 지정된 종목의 모든 타입 해제
        
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
                    'trnm': 'REMOVE',             # 등록 해제 명령
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



            logger.error(f"업종현재가일별 요청 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise


