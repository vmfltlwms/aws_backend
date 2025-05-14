import asyncio
import logging
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from config import settings
from db.redis_client import get_redis_connection, get_hash_data, run_redis_command, get_keys_by_pattern
from utils.utils import convert_to_timestamp
logger = logging.getLogger(__name__)

class RedisToPostgresWorker:
    """Redis 데이터를 PostgreSQL로 저장하는 개선된 워커"""
    
    def __init__(self, interval_seconds: int = 30, batch_size: int = 1000):
        """
        워커 초기화
        
        Args:
            interval_seconds: 워커 실행 간격 (초) - 짧게 설정하여 데이터 손실 방지
            batch_size: 한 번에 처리할 최대 레코드 수
        """
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self.is_running = False
        self.worker_task = None
        
        # 데이터베이스 연결 정보
        self.db_params = {
            "dbname": settings.PG_DATABASE,
            "user": settings.PG_USER,
            "password": settings.PG_PASSWORD,
            "host": settings.PG_HOST,
            "port": settings.PG_PORT
        }
        
        # 처리된 키를 추적하기 위한 세트
        self.processed_keys = set()
    
    async def start(self):
        """워커 시작"""
        if self.is_running:
            logger.info("Worker already running")
            return
        
        self.is_running = True
        self.worker_task = asyncio.create_task(self._worker_loop())
        logger.info(f"Redis to PostgreSQL worker started with {self.interval_seconds}s interval")
    
    async def stop(self):
        """워커 중지"""
        if not self.is_running:
            logger.info("Worker not running")
            return
        
        self.is_running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None
        
        logger.info("Redis to PostgreSQL worker stopped")
    
    async def _worker_loop(self):
        """워커 메인 루프"""
        while self.is_running:
            try:
                # 데이터 처리 시작
                start_time = datetime.now()
                
                # 1. Redis 연결 가져오기
                redis_client = get_redis_connection()
                
                # 2. 처리할 데이터 가져오기 (배치 처리)
                exec_data_count = await self._process_execution_data_batch(redis_client)
                
                # 3. 성능 로깅
                elapsed_time = (datetime.now() - start_time).total_seconds()
                if exec_data_count > 0:
                    logger.info(f"Processed {exec_data_count} execution records in {elapsed_time:.2f}s")
                
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
            
            # 다음 실행까지 대기
            await asyncio.sleep(self.interval_seconds)
    
    async def _process_execution_data_batch(self, redis_client) -> int:
        """
        주식 체결 데이터 배치 처리
        
        Args:
            redis_client: Redis 클라이언트
            
        Returns:
            처리된 레코드 수
        """
        try:
            # 1. 처리할 주식체결(0B) 데이터 키 찾기
            pattern = "0B:*:*"
            execution_keys = await get_keys_by_pattern(redis_client, pattern)
            
            if not execution_keys:
                return 0
            
            # 2. 처리하지 않은 키만 필터링
            new_keys = [key for key in execution_keys if key not in self.processed_keys]
            
            # 3. 타임스탬프 기준으로 정렬 (오래된 것부터 처리)
            sorted_keys = sorted(new_keys, key=lambda k: k.split(':')[2])
            
            # 4. 배치 크기만큼만 처리
            keys_to_process = sorted_keys[:self.batch_size]
            
            if not keys_to_process:
                return 0
            
            # 5. 배치로 데이터 수집
            batch_records = []
            
            for key in keys_to_process:
                try:
                    record = await self._prepare_execution_record_from_key(redis_client, key)
                    if record:
                        batch_records.append(record)
                except Exception as e:
                    logger.error(f"Error processing key {key}: {e}")
            
            # 6. PostgreSQL에 배치 저장
            if batch_records:
                success = await self._save_batch_to_postgres(batch_records)
                if success:
                    # 성공적으로 처리된 키 추적
                    self.processed_keys.update(keys_to_process)
                    
                    # 오래된 키 제거 (메모리 관리)
                    if len(self.processed_keys) > 100000:
                        oldest_keys = sorted(self.processed_keys)[:50000]
                        self.processed_keys = set(self.processed_keys) - set(oldest_keys)
                    
                    return len(batch_records)
            
            return 0
            
        except Exception as e:
            logger.error(f"Error in _process_execution_data_batch: {e}")
            return 0
    
    async def _prepare_execution_record_from_key(self, redis_client, key: str) -> Optional[Dict[str, Any]]:
        """
        Redis 키에서 실행 레코드 준비
        
        Args:
            redis_client: Redis 클라이언트
            key: Redis 키
            
        Returns:
            변환된 레코드 또는 None
        """
        try:
            # 키에서 정보 추출
            parts = key.split(':')
            if len(parts) != 3:
                return None
            
            type_code = parts[0]
            stock_code = parts[1]
            timestamp = parts[2]
            
            # 데이터 가져오기
            data = await run_redis_command(redis_client.hgetall, key)
            if not data:
                return None
            
            # 타임스탬프 변환 (HHMMSSMMM -> datetime)
            try:
                # 시간, 분, 초, 밀리초 추출
                hour = int(timestamp[0:2])
                minute = int(timestamp[2:4])
                second = int(timestamp[4:6])
                millisecond = int(timestamp[6:9])
                
                # 오늘 날짜에 시간 추가
                today = datetime.now().date()
                trade_timestamp = datetime(
                    today.year, today.month, today.day,
                    hour, minute, second, millisecond * 1000
                )
                
                # 만약 미래 시간이면 어제 날짜로 처리
                if trade_timestamp > datetime.now():
                    trade_timestamp -= timedelta(days=1)
            except Exception as e:
                logger.error(f"Timestamp conversion error for {timestamp}: {e}")
                trade_timestamp = datetime.now()
            
            # 주식호가 데이터 가져오기
            ask_bid_data_list = await get_hash_data(redis_client, "0D", stock_code)
            ask_bid_data = ask_bid_data_list[0] if ask_bid_data_list else {}
            
            # 레코드 준비
            record = await self._prepare_execution_record(
                stock_code, data, ask_bid_data, timestamp
            )
            
            if record:
                record["trade_timestamp"] = trade_timestamp
                record["redis_key"] = key
                
            return record
            
        except Exception as e:
            logger.error(f"Error preparing record from key {key}: {e}")
            return None
    
    async def _prepare_execution_record(self, stock_code: str, 
                                        execution_data: Dict[str, str],
                                        ask_bid_data: Dict[str, str],
                                        timestamp: str) -> Optional[Dict[str, Any]]:
        """주식 체결 레코드 준비 (기존 코드와 동일)"""
        def safe_int(value):
            if not value or value == "":
                return 0
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return 0
        
        def safe_float(value):
            if not value or value == "":
                return 0.0
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        
        try:
            # 데이터 추출 및 변환
            execution_time_str = execution_data.get("20", "")
            trade_time = timestamp
            price = safe_float(execution_data.get("10", "0"))
            change = safe_float(execution_data.get("11", "0"))
            best_ask_price = safe_float(execution_data.get("27", "0"))
            best_bid_price = safe_float(execution_data.get("28", "0"))
            volume = safe_int(execution_data.get("15", "0"))
            strength = safe_float(execution_data.get("228", "0"))
            sell_total = safe_int(execution_data.get("121", "0"))
            buy_total = safe_int(execution_data.get("125", "0"))
            sell_resistance = safe_float(execution_data.get("sell_resistance", "0"))
            buy_support = safe_float(execution_data.get("buy_support", "0"))
            buy_sell_ratio = safe_float(execution_data.get("129", "0"))
            
            record = {
                "stock_code": stock_code,
                "execution_time": execution_time_str,
                "trade_time": trade_time,
                "price": price if price else None,
                "change": change if change else None,
                "best_ask_price": best_ask_price if best_ask_price else None,
                "best_bid_price": best_bid_price if best_bid_price else None,
                "volume": volume if volume else None,
                "strength": strength if strength else None,
                "sell_total_volume": sell_total if sell_total else None,
                "buy_total_volume": buy_total if buy_total else None,
                "sell_resistance": sell_resistance if sell_resistance else None,
                "buy_support": buy_support if buy_support else None,
                "buy_sell_ratio": buy_sell_ratio if buy_sell_ratio else None
            }
            
            return record
            
        except Exception as e:
            logger.error(f"Error preparing execution record for {stock_code}: {e}")
            return None
    
    async def _save_batch_to_postgres(self, records: List[Dict[str, Any]]) -> bool:
        """
        PostgreSQL에 배치로 데이터 저장
        
        Args:
            records: 저장할 레코드 리스트
            
        Returns:
            성공 여부
        """
        conn = None
        try:
            conn = psycopg2.connect(**self.db_params)
            cur = conn.cursor()
            
            # 데이터 준비
            values = []
            for record in records:
                values.append((
                    record["stock_code"],
                    record["execution_time"],
                    record["trade_time"],
                    record["trade_timestamp"],
                    record["redis_key"],
                    record["price"],
                    record["change"],
                    record["best_ask_price"],
                    record["best_bid_price"],
                    record["volume"],
                    record["strength"],
                    record["sell_total_volume"],
                    record["buy_total_volume"],
                    record["sell_resistance"],
                    record["buy_support"],
                    record["buy_sell_ratio"]
                ))
            
            # 배치 INSERT 쿼리
            query = """
                INSERT INTO stock_executions (
                    stock_code, execution_time, trade_time, trade_timestamp, redis_key,
                    price, change, best_ask_price, best_bid_price, 
                    volume, strength, sell_total_volume, buy_total_volume, 
                    sell_resistance, buy_support, buy_sell_ratio
                ) VALUES %s
                ON CONFLICT (stock_code, trade_timestamp) DO UPDATE SET
                    execution_time = EXCLUDED.execution_time,
                    trade_time = EXCLUDED.trade_time,
                    redis_key = EXCLUDED.redis_key,
                    price = EXCLUDED.price,
                    change = EXCLUDED.change,
                    best_ask_price = EXCLUDED.best_ask_price,
                    best_bid_price = EXCLUDED.best_bid_price,
                    volume = EXCLUDED.volume,
                    strength = EXCLUDED.strength,
                    sell_total_volume = EXCLUDED.sell_total_volume,
                    buy_total_volume = EXCLUDED.buy_total_volume,
                    sell_resistance = EXCLUDED.sell_resistance,
                    buy_support = EXCLUDED.buy_support,
                    buy_sell_ratio = EXCLUDED.buy_sell_ratio
            """
            
            # psycopg2의 execute_values 사용 (배치 삽입 최적화)
            execute_values(cur, query, values)
            conn.commit()
            
            return True
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Error saving batch to PostgreSQL: {e}")
            return False
        finally:
            if conn:
                conn.close()