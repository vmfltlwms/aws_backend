# services/realtime_handler.py
import logging
import json
from typing import Dict, Any, List, Callable, Optional
import asyncio
from db.redis_client import get_redis_connection,save_hash_data , get_hash_data 
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class RealtimeHandler:
    """실시간 데이터 처리 핸들러"""
    
    def __init__(self):
        self.websocket_clients = []
        self.callback_registry = {}
        self.redis_client = None
        # 데이터 타입별 핸들러 등록
        self.type_handlers = {
            "00": self.handle_order_execution,  # 주문체결
            "02": self.cond_search,  # 실시간 조건검색 
            "04": self.handle_balance,  # 잔고
            "0B": self.handle_stock_execution,  # 주식체결
            "0D": self.handle_stock_ask_bid,  # 주식호가잔량
            # 기타 데이터 타입 핸들러 추가
        }
        
    async def initialize(self):
        """핸들러 초기화"""
        try:
            self.redis_client = get_redis_connection()
            logger.info(f"실시간 데이터 핸들러 초기화 완료: {self.redis_client}")
            return True
        except Exception as e:
            logger.error(f"실시간 데이터 핸들러 초기화 실패: {str(e)}")
            return False
    
    async def register_client(self, client: WebSocket):
        """웹소켓 클라이언트 등록"""
        if client not in self.websocket_clients:
            self.websocket_clients.append(client)
            logger.info(f"새 클라이언트 등록. 현재 {len(self.websocket_clients)}개 연결")
    
    async def unregister_client(self, client: WebSocket):
        """웹소켓 클라이언트 해제"""
        if client in self.websocket_clients:
            self.websocket_clients.remove(client)
            logger.info(f"클라이언트 해제. 현재 {len(self.websocket_clients)}개 연결")
    
    async def process_real_time_data(self, message: Dict[str, Any]):
        """실시간 데이터 처리"""
        try:
            # 병렬 실행할 작업들을 리스트에 담음
            tasks = []
            if self.redis_client is None :
                await self.initialize()

            # 1. Redis 저장 (비동기 함수로 감싸야 함)
            if self.redis_client:
                for item_data in message.get("data", []):
                    type_code = item_data.get("type")
                    item_code = item_data.get("item")
                    values = item_data.get("values", {})
                    logger.info(f"hash_name redis 데이터 저장 : {type_code}:{item_code}")
                    tasks.append(asyncio.create_task(save_hash_data(self.redis_client, type_code, item_code, values)))

            # 2. 클라이언트 브로드캐스트
            tasks.append(asyncio.create_task(self.broadcast_to_clients(message)))

            # 3. 데이터 타입별 개별 처리
            for item_data in message.get("data", []):
                type_code = item_data.get("type")
                item_code = item_data.get("item")
                values = item_data.get("values", {})
                logger.info(f"핸들러 호출: {type_code}:{item_code}")
                handler = self.type_handlers.get(type_code)
                if handler:
                    tasks.append(asyncio.create_task(handler(item_code, values)))

                else:
                    logger.debug(f"처리기가 없는 데이터 타입: {type_code}")

            # 병렬 실행
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"실시간 데이터 처리 중 오류: {str(e)}")
        
    async def broadcast_to_clients(self, message: Dict[str, Any]):
        """모든 클라이언트에게 메시지 전송"""
        if not self.websocket_clients:
            return
            
        disconnected = []
        message_str = json.dumps(message) if not isinstance(message, str) else message
        
        for client in self.websocket_clients:
            try:
                await client.send_text(message_str)
            except Exception as e:
                logger.error(f"클라이언트에 메시지 전송 중 오류: {str(e)}")
                disconnected.append(client)
                
        # 연결 끊긴 클라이언트 정리
        for client in disconnected:
            await self.unregister_client(client)
    
    # 데이터 타입별 핸들러 구현
    async def handle_stock_ask_bid(self, item_code: str, values: Dict[str, Any]):
        """주식호가잔량 (0D) 처리"""
        res = await get_hash_data(self.redis_client, "0D", item_code)
        logger.info(f"주식호가잔량 데이터 수신: {res}")
        # 호가 데이터 처리 로직 구현
        
    async def handle_stock_execution(self, item_code: str, values: Dict[str, Any]):
        """주식체결 (0B) 처리"""
        res = await get_hash_data(self.redis_client, "0B", item_code)
        logger.info(f"주식체결 데이터 수신: {item_code}")
        # 체결 데이터 처리 로직 구현
        
    async def handle_order_execution(self, item_code: str, values: Dict[str, Any]):
        """주문체결 (00) 처리"""
        res = await get_hash_data(self.redis_client, "00", item_code)
        logger.info(f"주문체결 데이터 수신: {item_code} {res}")
        # 주문체결 데이터 처리 로직 구현
        
    async def handle_balance(self, item_code: str, values: Dict[str, Any]):
        """잔고 (04) 처리"""
        res = await get_hash_data(self.redis_client, "04", item_code)
        logger.info(f"잔고 데이터 수신: {item_code} {res}")
        # 잔고 데이터 처리 로직 구현
    async def cond_search(self, item_code: str, values: Dict[str, Any]):
        logger.info(f"실시간 조건검색색: {item_code} {values}")
        pass
        """실시간 조건검색 (02) 처리"""

