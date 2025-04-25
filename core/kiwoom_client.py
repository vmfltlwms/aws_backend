import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import requests
import websockets
from fastapi import WebSocket
from config import settings

logger = logging.getLogger(__name__)

class KiwoomClient() : 
    """키움 API와 통신하는 클라이언트"""

    def __init__(self, real=settings.KIWOOM_REAL_SERVER):
        # 실전투자, 모의투자 선택
        self.host = 'https://api.kiwoom.com' if real else 'https://mockapi.kiwoom.com'
        self.socket_uri = 'wss://api.kiwoom.com:10000/api/dostk/websocket' if real else 'wss://mockapi.kiwoom.com:10000/api/dostk/websocket'
        self.app_key = settings.KIWOOM_APP_KEY
        self.sec_key = settings.KIWOOM_SECRET_KEY
        self.token = None
        self.websocket = None
        self.connected = False
        self.keep_running = True
        self.logger = logging.getLogger(__name__)
        self.registered_groups = []
        
        # 등록된 종목 추적
        self.registered_items = {}
        
        # 클라이언트 웹소켓 연결 관리
        self.active_connections: List[WebSocket] = []
        
        # 이벤트 루프 및 태스크
        self.event_loop = None
        self.connection_task = None
        
        # 연결 상태 관리
        self.last_connected_time = 0
        self.reconnect_attempts = 0
        
        # 응답 대기를 위한 Future 객체 딕셔너리
        self.response_futures = {}
    
    async def initialize(self):
        """클라이언트 초기화 및 연결"""
        try:
            self.token = await self.get_token_async()
            await self.connect()
            return True
        except Exception as e:
            logger.error(f"초기화 실패: {str(e)}")
            return False
    
    async def get_token_async(self, max_retries=3, retry_delay=5):
        """비동기 버전의 토큰 발급 함수"""
        url = self.host + '/oauth2/token'
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
        }
        data = {
            'grant_type': 'client_credentials',
            'appkey': self.app_key,
            'secretkey': self.sec_key,
        }
        
        for attempt in range(max_retries):
            try:
                # requests를 비동기로 실행하기 위해 loop.run_in_executor 사용
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, 
                    lambda: requests.post(url, headers=headers, json=data)
                )
                
                # 429 오류에 대한 특별 처리
                if response.status_code == 429:
                    wait_time = retry_delay * (attempt + 1)
                    logger.warning(f"너무 많은 요청 (429 오류). {wait_time}초 후 재시도합니다. (시도 {attempt+1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                    continue
                    
                response.raise_for_status()
                response_data = response.json()
                logger.info("토큰 발급 성공")
                return response_data["token"]
                
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    logger.warning(f"토큰 발급 오류: {str(e)}. {wait_time}초 후 재시도합니다. (시도 {attempt+1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"토큰 발급 실패: {str(e)}")
                    raise
                
        logger.error("최대 재시도 횟수 초과. 토큰 발급 실패")
        raise Exception("토큰 발급 실패: 최대 재시도 횟수 초과")
    
    # WebSocket 서버에 연결
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
    
    # 서버에 메시지 전송하고 응답 기다리기
    async def send_and_wait_for_response(self, message, trnm, timeout=10.0):
        """메시지를 보내고 특정 trnm에 대한 응답을 기다림"""
        if not self.connected:
            logger.warning("연결이 끊겨 있습니다. 재연결 시도 중...")
            await self.connect()
            
        if not self.connected:
            return {"error": "서버에 연결할 수 없습니다."}
            
        try:
            # Future 객체 생성
            future = asyncio.Future()
            
            # 응답 추적을 위해 trnm을 키로 사용
            self.response_futures[trnm] = future
            
            # 메시지 전송
            result = await self.send_message(message)
            if not result:
                if trnm in self.response_futures:
                    del self.response_futures[trnm]
                return {"error": "메시지 전송 실패"}
                
            # 응답 대기
            try:
                response = await asyncio.wait_for(future, timeout)
                return response
            except asyncio.TimeoutError:
                logger.error(f"{trnm} 응답 대기 시간 초과")
                return {"error": f"{trnm} 응답 대기 시간 초과"}
            finally:
                # Future 객체 삭제
                if trnm in self.response_futures:
                    del self.response_futures[trnm]
                
        except Exception as e:
            logger.error(f"메시지 전송 및 응답 대기 중 오류: {str(e)}")
            if trnm in self.response_futures:
                del self.response_futures[trnm]
            return {"error": f"메시지 전송 및 응답 대기 중 오류: {str(e)}"}
    
    # 서버로부터 메시지 수신
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
                
                # trnm 값 추출
                trnm = response.get('trnm', '')
                                
                # 메시지 유형에 따른 처리
                if trnm == 'LOGIN':
                    # 로그인 응답 처리
                    if response.get('return_code') != 0:
                        logger.error(f'로그인 실패: {response.get("return_msg")}')
                        await self.disconnect()
                    else:
                        logger.info('로그인 성공')
                
                elif trnm == 'PING':
                    # PING 응답 처리 (수신값 그대로 송신)
                    logger.debug('PING 메시지 수신, PONG 응답')
                    await self.send_message(response)
                    
                elif trnm == 'RECV':
                    # 실시간 데이터 수신 처리
                    await self.handle_realtime_data(response)
                    await self.broadcast_to_clients(response)  # 기존 코드
                
                # 대기 중인 응답이 있는지 확인
                if trnm in self.response_futures and not self.response_futures[trnm].done():
                    # Future에 응답 설정
                    self.response_futures[trnm].set_result(response)
                
                # PING이 아닌 모든 메시지 로깅
                if trnm != 'PING':
                    logger.info(f'실시간 시세 서버 응답 수신: {response}')

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
    
    # 클라이언트 웹소켓 관리
    async def connect_client(self, websocket: WebSocket):
        """프론트엔드 클라이언트 연결 추가"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"새 클라이언트 연결됨. 현재 {len(self.active_connections)}개 연결")
    
    def disconnect_client(self, websocket: WebSocket):
        """프론트엔드 클라이언트 연결 해제"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"클라이언트 연결 종료. 현재 {len(self.active_connections)}개 연결")
    
    # 프론트엔드 클라이언트에게 메시지 전송
    async def broadcast_to_clients(self, message):
        """모든 연결된 클라이언트에게 메시지 전송"""
        if not self.active_connections:
            return
        
        # 딕셔너리를 JSON 문자열로 변환
        if not isinstance(message, str):
            message = json.dumps(message)
        
        disconnected = []
        
        # 연결된 모든 클라이언트에게 전송
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"클라이언트에 메시지 전송 중 오류: {str(e)}")
                # 연결에 문제가 있는 클라이언트는 목록에서 제거하기 위해 표시
                disconnected.append(connection)
        
        # 연결 끊긴 클라이언트 정리
        for connection in disconnected:
            self.disconnect_client(connection)
    
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

    # 주식 기본 정보 조회 (REST API 예시)
    async def get_stock_info(self, code: str) -> dict:
        """주식 기본 정보 조회"""
        url = f"{self.host}/api/dostk/stkinfo"  # 올바른 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": "N",  # 연속조회여부
            "next-key": "",  # 연속조회키
            "api-id": "ka10001"  # TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code
        }
        
        try:
            loop = asyncio.get_event_loop()
            # GET 대신 POST 사용, params 대신 json 사용
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"응답 내용: {response.text}")
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"주식 정보 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
    
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
            if not data or "trnm" not in data or data["trnm"] != "RECV":
                return
            
            # 그룹 번호, 종목 코드, 데이터 타입 추출
            group_no = data.get("grp_no", "")
            item = data.get("item", "")
            type_code = data.get("typ", "")
            values = data.get("values", {})
            
            # 디버깅 로그
            logger.debug(f"실시간 데이터 수신: 그룹={group_no}, 종목={item}, 타입={type_code}")
            
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
                    "group_no": group_no,
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
            
        except Exception as e:
            logger.error(f"실시간 데이터 처리 중 오류: {str(e)}")

    async def unsubscribe_realtime_price(self, group_no="1", items=None, data_types=None):
        """
        실시간 시세 정보 구독 해제 함수
        
        Args:
            group_no (str): 그룹 번호
            items (list): 종목 코드 리스트 (예: ["005930", "000660"]). None이면 그룹 전체 해제
            data_types (list): 데이터 타입 리스트 (예: ["0D", "01"]). None이면 지정된 종목의, 종목 자체가 None이면, 모든 타입 해제
        
        Returns:
            dict: 요청 결과
        """
        if not self.connected:
            logger.error("키움 API에 연결되어 있지 않습니다.")
            return {"error": "키움 API에 연결되어 있지 않습니다."}
        
        try:
            # 그룹 번호 문자열 변환
            group_no = str(group_no)
            
            # items가 None이면 그룹 전체 해제
            if items is None:
                # 요청 데이터 구성
                request_data = {
                    'trnm': 'REMOVE',                # 등록 해제 명령
                    'grp_no': group_no              # 그룹 번호
                }
                
                # 요청 전송
                logger.info(f"실시간 시세 구독 해제 요청: 그룹={group_no} (전체 해제)")
                result = await self.send_message(request_data)
                
                # 상태 추적 딕셔너리 업데이트
                if group_no in self.registered_items:
                    del self.registered_items[group_no]
                
                if result:
                    return {
                        "status": "success", 
                        "message": f"그룹 {group_no} 실시간 시세 구독 해제 완료 (전체)",
                        "group_no": group_no
                    }
                else:
                    return {"error": "실시간 시세 구독 해제 요청 실패"}
            
            # 특정 종목과 타입만 해제
            else:
                # data_types가 None이면 모든 타입 해제
                if data_types is None and group_no in self.registered_items:
                    # 해당 종목에 등록된 모든 타입 가져오기
                    data_types = []
                    for item in items:
                        if item in self.registered_items[group_no]:
                            data_types.extend(self.registered_items[group_no][item])
                    # 중복 제거
                    data_types = list(set(data_types))
                
                # 요청 데이터 구성
                request_data = {
                    'trnm': 'UNREG',                # 등록 해제 명령
                    'grp_no': group_no,             # 그룹 번호
                    'data': [{
                        'item': items,              # 종목 코드 리스트
                        'type': data_types          # 데이터 타입 리스트
                    }]
                }
                
                # 요청 전송
                logger.info(f"실시간 시세 구독 해제 요청: 그룹={group_no}, 종목={items}, 타입={data_types}")
                result = await self.send_message(request_data)
                
                # 상태 추적 딕셔너리 업데이트
                if group_no in self.registered_items:
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
                
                if result:
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

    async def get_tick_chart(self, code: str, tick_scope: str = "1", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 틱차트 조회 (ka10079)
        
        Args:
            code (str): 종목 코드
            tick_scope (str): 틱범위 - 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 틱차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 틱차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10079"  # 틱챠트조회 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "tic_scope": tick_scope,
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"틱차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"틱차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"틱차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_minute_chart(self, code: str, tic_scope: str = "1", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 분봉차트 조회 (ka10080)
        
        Args:
            code (str): 종목 코드
            minute_unit (str): 분단위 - 1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 60:60분
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 분봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 분봉차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10080"  # 분봉챠트조회 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "tic_scope": tic_scope,
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"분봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"분봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"분봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_daily_chart(self, code: str, base_dt: str = "", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 일봉차트 조회 (ka10081)
        
        Args:
            code (str): 종목 코드
            period_value (str): 기간 - 1:일봉(default)
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 일봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 일봉차트 조회 엔드포인트
        
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10081"  # 일봉챠트조회 TR명
        }
        
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if base_dt == ''  : 
            base_dt = current_date.strftime("%Y%m%d")
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "base_dt": base_dt,  # 20250421
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"일봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"일봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"일봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_weekly_chart(self, code: str,base_dt: str = "", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 주봉차트 조회 (ka10082)
        
        Args:
            code (str): 종목 코드
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 주봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 주봉차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10082"  # 주봉챠트조회 TR명
        }
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if base_dt == ''  : 
            base_dt = current_date.strftime("%Y%m%d")
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "base_dt": base_dt,  # 20250421
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"주봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_monthly_chart(self, code: str,base_dt: str = "", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 월봉차트 조회 (ka10083)
        
        Args:
            code (str): 종목 코드
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 월봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 월봉차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10083"  # 월봉챠트조회 TR명
        }
        
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if base_dt == ''  : 
            base_dt = current_date.strftime("%Y%m%d")
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "base_dt": base_dt,  # 20250421
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"월봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"월봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"월봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_yearly_chart(self, code: str, base_dt: str = "",price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 년봉차트 조회 (ka10094)
        
        Args:
            code (str): 종목 코드
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 년봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 년봉차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10094"  # 년봉챠트조회 TR명
        }
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if base_dt == ''  : 
            base_dt = current_date.strftime("%Y%m%d")
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "base_dt": base_dt,  # 20250421
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"년봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"년봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"년봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise    

    async def get_deposit_detail(self, 
                                query_type: str = "2", 
                                cont_yn: str = "N",
                                next_key: str = "") -> dict:
        """
        예수금상세현황요청 (kt00001)
        
        Args:
            account_no (str): 계좌번호
            query_type (str): 조회구분 (3:추정조회, 2:일반조회)
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 응답의 next-key값
            
        Returns:
            dict: 예수금 상세현황 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "kt00001"  # 예수금상세현황요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "qry_tp": query_type,
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"예수금상세현황 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"예수금상세현황 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"예수금상세현황 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
        
    async def get_order_detail(self, 
                                order_date: str,
                                query_type: str = "1", 
                                stock_bond_type: str = "1", 
                                sell_buy_type: str = "0", 
                                stock_code: str = "", 
                                from_order_no: str = "", 
                                market_type: str = "KRX",
                                cont_yn: str = "N", 
                                next_key: str = "") -> dict:
        """
        계좌별주문체결내역상세요청 (kt00007)
        
        Args:
            order_date (str): 주문일자 (YYYYMMDD)
            query_type (str): 조회구분 - 1:주문순, 2:역순, 3:미체결, 4:체결내역만
            stock_bond_type (str): 주식채권구분 - 0:전체, 1:주식, 2:채권
            sell_buy_type (str): 매도수구분 - 0:전체, 1:매도, 2:매수
            stock_code (str): 종목코드 (공백허용, 공백일때 전체종목)
            from_order_no (str): 시작주문번호 (공백허용, 공백일때 전체주문)
            market_type (str): 국내거래소구분 - %:(전체), KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문체결내역 상세 데이터
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "kt00007"  # 계좌별주문체결내역상세요청 TR명
        }
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if order_date == ''  : 
            order_date = current_date.strftime("%Y%m%d")
        
        # JSON 형식으로 전달할 데이터
        data = {
            "ord_dt": order_date,
            "qry_tp": query_type,
            "stk_bond_tp": stock_bond_type,
            "sell_tp": sell_buy_type,
            "stk_cd": stock_code,
            "fr_ord_no": from_order_no,
            "dmst_stex_tp": market_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주문체결내역 상세 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주문체결내역 상세 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"주문체결내역 상세 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
    async def get_daily_trading_log(self, 
                                base_date: str = "", 
                                ottks_tp: str = "1", 
                                ch_crd_tp : str = "0",
                                cont_yn: str = "N", 
                                next_key: str = "") -> dict:
        """
        당일매매일지요청 (ka10170)
        
        Args:
            base_date (str): 기준일자 (YYYYMMDD) - 공백일 경우 당일
            ottks_tp (str): 단주구분 - 1:당일매수에 대한 당일매도, 2:당일매도 전체
            ch_crd_tp(str) : 0:전체, 1:현금매매만, 2:신용매매만
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 당일 매매일지 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10170"  # 당일매매일지요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "base_dt": base_date,
            "ottks_tp": ottks_tp,
            "ch_crd_tp": ch_crd_tp
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"당일매매일지 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"당일매매일지 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"당일매매일지 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise       
        
        
    async def get_outstanding_orders(self, 
                                all_stk_tp: str = "0", 
                                trde_tp: str = "0", 
                                stk_cd: str = "", 
                                stex_tp: str = "0",
                                cont_yn: str = "N", 
                                next_key: str = "") -> dict:
        """
        미체결요청 (ka10075)
        
        Args:
            all_stk_tp (str): 전체종목구분 - 0:전체, 1:종목
            trde_tp (str): 매매구분 - 0:전체, 1:매도, 2:매수
            stk_cd (str): 종목코드 (all_stk_tp가 1일 경우 필수)
            stex_tp (str): 거래소구분 - 0:통합, 1:KRX, 2:NXT
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 미체결 주문 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10075"  # 미체결요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터 - stk_cd를 항상 포함
        data = {
            "all_stk_tp": all_stk_tp,
            "trde_tp": trde_tp,
            "stk_cd": stk_cd,
            "stex_tp": stex_tp
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"미체결 주문 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"미체결 주문 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"미체결 주문 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
    
    async def get_executed_orders(self, 
                                stk_cd: str = "", 
                                qry_tp: str = "0", 
                                sell_tp: str = "0", 
                                ord_no: str = "", 
                                stex_tp: str = "0",
                                cont_yn: str = "N", 
                                next_key: str = "") -> dict:
        """
        체결요청 (ka10076)
        
        Args:
            stk_cd (str): 종목코드
            qry_tp (str): 조회구분 - 0:전체, 1:종목
            sell_tp (str): 매도수구분 - 0:전체, 1:매도, 2:매수
            ord_no (str): 주문번호 (입력한 주문번호보다 과거에 체결된 내역 조회)
            stex_tp (str): 거래소구분 - 0:통합, 1:KRX, 2:NXT
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 체결 주문 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10076"  # 체결요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": stk_cd,
            "qry_tp": qry_tp,
            "sell_tp": sell_tp,
            "ord_no": ord_no,
            "stex_tp": stex_tp
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"체결 주문 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"체결 주문 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"체결 주문 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
    
    async def get_daily_item_realized_profit(self, 
                                        stk_cd: str, 
                                        strt_dt: str,
                                        cont_yn: str = "N", 
                                        next_key: str = "") -> dict:
        """
        일자별종목별실현손익요청_일자 (ka10072)
        
        Args:
            stk_cd (str): 종목코드
            strt_dt (str): 시작일자 (YYYYMMDD)
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 일자별 종목별 실현손익 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10072"  # 일자별종목별실현손익요청_일자 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": stk_cd,
            "strt_dt": strt_dt
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"일자별종목별실현손익 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"일자별종목별실현손익 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"일자별종목별실현손익 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise    
        
    async def get_daily_realized_profit(self, 
                                    strt_dt: str, 
                                    end_dt: str,
                                    cont_yn: str = "N", 
                                    next_key: str = "") -> dict:
        """
        일자별실현손익요청 (ka10074)
        
        Args:
            strt_dt (str): 시작일자 (YYYYMMDD)
            end_dt (str): 종료일자 (YYYYMMDD)
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 일자별 실현손익 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10074"  # 일자별실현손익요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "strt_dt": strt_dt,
            "end_dt": end_dt
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"일자별 실현손익 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"일자별 실현손익 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"일자별 실현손익 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
    async def order_stock_buy(self, 
                            dmst_stex_tp: str, 
                            stk_cd: str, 
                            ord_qty: str, 
                            ord_uv: str = "", 
                            trde_tp: str = "0", 
                            cond_uv: str = "",
                            cont_yn: str = "N",
                            next_key: str = "") -> dict:
        """
        주식 매수주문 (kt10000)
        
        Args:
            dmst_stex_tp (str): 국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            stk_cd (str): 종목코드
            ord_qty (str): 주문수량
            ord_uv (str): 주문단가 (시장가 주문 시 비워둠)
            trde_tp (str): 매매구분 - 0:보통, 3:시장가, 5:조건부지정가, 6:최유리지정가, 7:최우선지정가 등
            cond_uv (str): 조건단가 (조건부 주문 시 사용)
            cont_yn (str): 연속조회여부
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문 결과 정보
        """
        url = f"{self.host}/api/dostk/ordr"  # 주문 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn, 
            "next-key": next_key,
            "api-id": "kt10000"  # 주식 매수주문 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "dmst_stex_tp": dmst_stex_tp,
            "stk_cd": stk_cd,
            "ord_qty": ord_qty,
            "ord_uv": ord_uv,
            "trde_tp": trde_tp,
            "cond_uv": cond_uv
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주식 매수주문 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주식 매수주문 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            logger.info(f"주식 매수주문 성공: {stk_cd}, {ord_qty}주, 주문번호: {result.get('ord_no', '알 수 없음')}")
            
            return result
        except Exception as e:
            logger.error(f"주식 매수주문 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def order_stock_sell(self, 
                            dmst_stex_tp: str, 
                            stk_cd: str, 
                            ord_qty: str, 
                            ord_uv: str = "", 
                            trde_tp: str = "0", 
                            cond_uv: str = "",
                            cont_yn: str = "N",
                            next_key: str = "") -> dict:
        """
        주식 매도주문 (kt10001)
        
        Args:
            dmst_stex_tp (str): 국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            stk_cd (str): 종목코드
            ord_qty (str): 주문수량
            ord_uv (str): 주문단가 (시장가 주문 시 비워둠)
            trde_tp (str): 매매구분 - 0:보통, 3:시장가, 5:조건부지정가, 6:최유리지정가, 7:최우선지정가 등
            cond_uv (str): 조건단가 (조건부 주문 시 사용)
            cont_yn (str): 연속조회여부
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문 결과 정보
        """
        url = f"{self.host}/api/dostk/ordr"  # 주문 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn, 
            "next-key": next_key,
            "api-id": "kt10001"  # 주식 매도주문 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "dmst_stex_tp": dmst_stex_tp,
            "stk_cd": stk_cd,
            "ord_qty": ord_qty,
            "ord_uv": ord_uv,
            "trde_tp": trde_tp,
            "cond_uv": cond_uv
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주식 매도주문 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주식 매도주문 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            logger.info(f"주식 매도주문 성공: {stk_cd}, {ord_qty}주, 주문번호: {result.get('ord_no', '알 수 없음')}")
            
            return result
        except Exception as e:
            logger.error(f"주식 매도주문 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise


    async def order_stock_modify(self, 
                            dmst_stex_tp: str, 
                            orig_ord_no: str, 
                            stk_cd: str, 
                            mdfy_qty: str, 
                            mdfy_uv: str, 
                            mdfy_cond_uv: str = "",
                            cont_yn: str = "N",
                            next_key: str = "") -> dict:
        """
        주식 정정주문 (kt10002)
        
        Args:
            dmst_stex_tp (str): 국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            orig_ord_no (str): 원주문번호
            stk_cd (str): 종목코드
            mdfy_qty (str): 정정수량
            mdfy_uv (str): 정정단가
            mdfy_cond_uv (str): 정정조건단가
            cont_yn (str): 연속조회여부
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문 결과 정보
        """
        url = f"{self.host}/api/dostk/ordr"  # 주문 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn, 
            "next-key": next_key,
            "api-id": "kt10002"  # 주식 정정주문 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "dmst_stex_tp": dmst_stex_tp,
            "orig_ord_no": orig_ord_no,
            "stk_cd": stk_cd,
            "mdfy_qty": mdfy_qty,
            "mdfy_uv": mdfy_uv,
            "mdfy_cond_uv": mdfy_cond_uv
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주식 정정주문 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주식 정정주문 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            logger.info(f"주식 정정주문 성공: {stk_cd}, 원주문번호: {orig_ord_no}, 정정수량: {mdfy_qty}, 정정단가: {mdfy_uv}")
            
            return result
        except Exception as e:
            logger.error(f"주식 정정주문 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
    async def order_stock_cancel(self, 
                            dmst_stex_tp: str, 
                            orig_ord_no: str, 
                            stk_cd: str, 
                            cncl_qty: str,
                            cont_yn: str = "N",
                            next_key: str = "") -> dict:
        """
        주식 취소주문 (kt10003)
        
        Args:
            dmst_stex_tp (str): 국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            orig_ord_no (str): 원주문번호
            stk_cd (str): 종목코드
            cncl_qty (str): 취소수량 ('0' 입력시 잔량 전부 취소)
            cont_yn (str): 연속조회여부
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문 결과 정보
        """
        url = f"{self.host}/api/dostk/ordr"  # 주문 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn, 
            "next-key": next_key,
            "api-id": "kt10003"  # 주식 취소주문 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "dmst_stex_tp": dmst_stex_tp,
            "orig_ord_no": orig_ord_no,
            "stk_cd": stk_cd,
            "cncl_qty": cncl_qty
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주식 취소주문 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주식 취소주문 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            logger.info(f"주식 취소주문 성공: {stk_cd}, 원주문번호: {orig_ord_no}, 취소수량: {cncl_qty}")
            
            return result
        except Exception as e:
            logger.error(f"주식 취소주문 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise        
            
    async def get_theme_group(self,
                                qry_tp: str = "0",
                                stk_cd: str = "",
                                date_tp: str = "10",
                                thema_nm: str = "",
                                flu_pl_amt_tp: str = "1",
                                stex_tp: str = "1",
                                cont_yn: str = "N", next_key: str = "") -> dict:
        """
        테마그룹별 종목조회 (ka90001)

        Args:
            qry_tp (str): 검색구분 (0:전체, 1:테마, 2:종목)
            stk_cd (str): 종목코드
            date_tp (str): 날짜구분 (1~99일)
            thema_nm (str): 테마명
            flu_pl_amt_tp (str): 수익률 구분 (1~4)
            stex_tp (str): 거래소 구분 (1:KRX, 2:NXT, 3:통합)
            cont_yn (str): 연속조회 여부
            next_key (str): 연속조회 키

        Returns:
            dict: 테마그룹 조회 결과
        """
        url = f"{self.host}/api/dostk/thme"

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka90001"
        }

        data = {
            "qry_tp": qry_tp,
            "stk_cd": stk_cd,
            "date_tp": date_tp,
            "thema_nm": thema_nm,
            "flu_pl_amt_tp": flu_pl_amt_tp,
            "stex_tp": stex_tp
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"테마그룹 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"테마그룹 조회 응답 내용: {response.text}")
            response.raise_for_status()

            result = response.json()
            headers_dict = dict(response.headers)
            result["has_next"] = headers_dict.get("has-next", "N") == "Y"
            result["next_key"] = headers_dict.get("next-key", "")
            return result

        except Exception as e:
            logger.error(f"테마그룹 조회 오류: {str(e)}")
            try:
                if hasattr(e, "response") and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_theme_components(
        self, 
        date_tp: str = "2", 
        thema_grp_cd: str = "100", 
        stex_tp: str = "1",
        cont_yn: str = "N", 
        next_key: str = ""
    ) -> dict:
        """
        테마구성종목 조회 (ka90002)

        Args:
            date_tp (str): 날짜구분 (1~99일)
            thema_grp_cd (str): 테마 그룹 코드
            stex_tp (str): 거래소구분 1:KRX, 2:NXT, 3:통합
            cont_yn (str): 연속조회 여부 (Y/N)
            next_key (str): 연속조회 키

        Returns:
            dict: 테마구성종목 데이터
        """
        url = f"{self.host}/api/dostk/thme"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka90002"
        }

        data = {
            "date_tp": date_tp,
            "thema_grp_cd": thema_grp_cd,
            "stex_tp": stex_tp
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"테마구성종목 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"테마구성종목 조회 응답 내용: {response.text}")

            response.raise_for_status()
            result = response.json()

            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')

            return result
        except Exception as e:
            logger.error(f"테마구성종목 조회 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_sector_prices(self,
                                mrkt_tp: str = "0",
                                inds_cd: str = "001",
                                stex_tp: str = "1",
                                cont_yn: str = "N",
                                next_key: str = ""
                            ) -> dict:
        """
        업종별 주가 조회 (ka20002)

        Args:
            mrkt_tp (str): 시장 구분 (0:코스피, 1:코스닥, 2:코스피200)
            inds_cd (str): 업종 코드 (001:KOSPI 종합 등)
            stex_tp (str): 거래소 구분 (1:KRX, 2:NXT, 3:통합)
            cont_yn (str): 연속조회 여부 (Y/N)
            next_key (str): 연속조회 키

        Returns:
            dict: 업종별 주가 데이터
        """
        url = f"{self.host}/api/dostk/sect"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka20002"
        }

        data = {
            "mrkt_tp": mrkt_tp,
            "inds_cd": inds_cd,
            "stex_tp": stex_tp
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"업종별주가 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"업종별주가 조회 응답 내용: {response.text}")

            response.raise_for_status()
            result = response.json()

            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')

            return result
        except Exception as e:
            logger.error(f"업종별주가 조회 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_all_sector_index(
        self,
        inds_cd: str = "001",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> dict:
        """
        전업종지수 요청 (ka20003)

        Args:
            inds_cd (str): 업종코드 (예: 001:종합(KOSPI), 002:대형주 등)
            cont_yn (str): 연속조회 여부
            next_key (str): 연속조회 키

        Returns:
            dict: 전업종지수 데이터
        """
        url = f"{self.host}/api/dostk/sect"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka20003"
        }

        data = {
            "inds_cd": inds_cd
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"전업종지수 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"전업종지수 응답 내용: {response.text}")

            response.raise_for_status()
            result = response.json()

            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')

            return result
        except Exception as e:
            logger.error(f"전업종지수 조회 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_sector_daily_price(
        self,
        mrkt_tp: str = "0",
        inds_cd: str = "001",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> dict:
        """
        업종현재가일별요청 (ka20009)

        Args:
            mrkt_tp (str): 시장구분 (0:코스피, 1:코스닥, 2:코스피200)
            inds_cd (str): 업종코드 (001:종합(KOSPI) 등)
            cont_yn (str): 연속조회 여부
            next_key (str): 연속조회 키

        Returns:
            dict: 업종 현재가 일별 데이터
        """
        url = f"{self.host}/api/dostk/sect"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka20009"
        }

        data = {
            "mrkt_tp": mrkt_tp,
            "inds_cd": inds_cd
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"업종현재가일별 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"업종현재가일별 응답 내용: {response.text}")

            response.raise_for_status()
            result = response.json()

            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')

            return result
        except Exception as e:
            logger.error(f"업종현재가일별 요청 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise



