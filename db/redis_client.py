import redis
import logging
from config import settings
from datetime import datetime
import json
import time
import asyncio
from typing import Dict, Any, Optional, List, Union
from utils.utils import calculate_resistance_support, calculate_buy_sell_ratio

logger = logging.getLogger(__name__)

# 글로벌 Redis 클라이언트
redis_client = None

async def init_redis():
    """Redis 연결을 초기화합니다."""
    global redis_client
    try:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=settings.REDIS_DB,
            decode_responses=True  # 자동 디코딩 설정
        )
        # Redis 연결 테스트
        result = await run_redis_command(redis_client.ping)
        logging.info(f"Redis connected successfully: {result}")
    except Exception as e:
        logging.error(f"Redis connection error: {e}")
        raise

async def close_redis():
    """Redis 연결을 종료합니다."""
    global redis_client
    if redis_client:
        await run_redis_command(redis_client.close)
        redis_client = None
        logging.info("Redis connection closed")

def get_redis_connection():
    """현재 Redis 연결을 반환합니다."""
    global redis_client
    if redis_client is None:
        raise Exception("Redis connection not initialized")
    return redis_client

# 동기식 Redis 명령을 비동기로 실행하는 헬퍼 함수
async def run_redis_command(command, *args, **kwargs):
    """동기식 Redis 명령을 비동기로 실행"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        lambda: command(*args, **kwargs)
    )
    
async def save_hash_data(redis_client, type_code, item_code, values_dict):
    """
    실시간 데이터를 Redis 해시에 저장 (비동기)
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        type_code (str): 데이터 타입 코드 (00: 주문체결, 02: 실시간 조건검색 등)
        item_code (str): 종목 코드 (예: "005930")
        values_dict (dict): 필드와 값들의 딕셔너리
    
    Returns:
        bool: 저장 성공 여부
    """
    try:
        # 필드 데이터 추출이 필요한 타입인지 확인
        if type_code in ["0B", "0D"]:
            extracted_data = await extract_field_data(type_code, values_dict)
            if extracted_data: values_dict = extracted_data
        
        # 저장 방식 결정 (타입코드별로 다른 처리)
        if type_code in ["0D"]:  # 주식호가 - 최신 데이터만 유지
            hash_name = f"{type_code}:{item_code}"
            # None 값 필터링
            filtered_dict = {k: v for k, v in values_dict.items() if v is not None}
            await run_redis_command(redis_client.hmset, hash_name, filtered_dict)
            await run_redis_command(redis_client.expire, hash_name, 3600)  # 1 시간
            logger.debug(f"데이터 저장 (최신값): {hash_name}")
            return True
        
        elif type_code in ["0B"] :  
            timestamp = datetime.now().strftime("%H%M%S%f")[:-3]  # 밀리초
            hash_name = f"{type_code}:{item_code}:{timestamp}"
            ask_bid_data = await get_hash_data(redis_client, "0D", item_code)
            if ask_bid_data:
                try:
                    sell_resistance, buy_support = await calculate_resistance_support(ask_bid_data[0]) 
                    # 저항선, 지지선 계산
                    values_dict["121"] = str(ask_bid_data[0].get("121", "000000"))  # 매도호가총잔량
                    values_dict["125"] = str(ask_bid_data[0].get("125", "000000"))  # 매수호가총잔량
                    values_dict["129"] = str(ask_bid_data[0].get("129", "000000"))  # 매수비율
                    
                    # None 값 체크 및 기본값 설정
                    if sell_resistance is not None:
                        values_dict["sell_resistance"] = str(sell_resistance)
                    else:
                        values_dict["sell_resistance"] = "0"
                        
                    if buy_support is not None:
                        values_dict["buy_support"] = str(buy_support)
                    else:
                        values_dict["buy_support"] = "0"
                except Exception as e:
                    logger.error(f"저항선/지지선 계산 중 오류: {e}")
                    values_dict["sell_resistance"] = "0"
                    values_dict["buy_support"] = "0"
                    values_dict["121"] = str(ask_bid_data[0].get("121", "000000"))
                    values_dict["125"] = str(ask_bid_data[0].get("125", "000000"))
                    values_dict["129"] = str(ask_bid_data[0].get("129", "000000"))
            
            # None 값 필터링 및 문자열 변환 보장
            filtered_dict = {}
            for k, v in values_dict.items():
                if v is not None:
                    # 모든 값을 문자열로 변환 (Redis는 문자열로 저장)
                    filtered_dict[k] = str(v)
            
            # 필드 데이터 변환   
            await run_redis_command(redis_client.hmset, hash_name, filtered_dict)
            await run_redis_command(redis_client.expire, hash_name, 600)  # 10분
            logger.debug(f"데이터 저장 (타임스탬프): {hash_name}")
            return True
        
        elif type_code in ["00","04"] :   # 주문체결(00), 잔고(04) 등 - 타임스탬프 포함 저장
            timestamp = datetime.now().strftime("%H%M%S%f")[:-3]  # 밀리초
            hash_name = f"{type_code}:{item_code}:{timestamp}"
            # None 값 필터링
            filtered_dict = {k: v for k, v in values_dict.items() if v is not None}
            await run_redis_command(redis_client.hmset, hash_name, filtered_dict)
            await run_redis_command(redis_client.expire, hash_name, 3600)  # 1 시간
            logger.debug(f"데이터 저장 (타임스탬프): {hash_name}")
            return True
        
        else : return True  # 기타 타입은 처리하지 않음
    except Exception as e:
        logger.error(f"해시 데이터 저장 오류 ({type_code}:{item_code}): {str(e)}")
        logger.error(f"Values dict: {values_dict}")  # 디버깅을 위한 데이터 로깅
        return False
    
async def get_hash_data(redis_client, type_code, item_code, limit=0):
    """
    특정 타입과 종목의 데이터를 가져옵니다 (비동기)
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        type_code (str): 데이터 타입 코드 (예: "0B", "0D")
        item_code (str): 종목 코드 (예: "005930")
        limit (int): 반환할 최대 데이터 수 (기본 10개, 0이면 모든 데이터)
    
    Returns:
        list: 데이터 딕셔너리 목록 (최신순) 또는 단일 데이터 딕셔너리
    """
    try:
        # 먼저 타임스탬프가 없는 키 확인 (예: "0D:005930")
        direct_key = f"{type_code}:{item_code}"
        exists_result = await run_redis_command(redis_client.exists, direct_key)
        
        if exists_result == 1:  # 키가 존재하면
            data = await run_redis_command(redis_client.hgetall, direct_key)
            if data:
                return [data]  # 단일 데이터도 리스트로 반환하여 일관성 유지
            return []
        
        # 타임스탬프가 있는 키 패턴 검색 (예: "0B:005930:*")
        pattern = f"{type_code}:{item_code}:*"
        keys = await run_redis_command(redis_client.keys, pattern)
        
        if not keys:
            return []
        
        # 키를 타임스탬프 기준으로 정렬 (최신순)
        sorted_keys = sorted(keys, key=lambda k: k.split(':')[2], reverse=True)
        
        # 요청한 한도까지만 처리 (limit=0이면 모든 데이터)
        keys_to_process = sorted_keys if limit == 0 else sorted_keys[:limit]
        
        result = []
        for key in keys_to_process:
            data = await run_redis_command(redis_client.hgetall, key)
            if data:
                # 키에서 타임스탬프 추출 및 추가
                parts = key.split(':')
                if len(parts) > 2:
                    data['timestamp'] = parts[2]
                result.append(data)
        
        return result
    except Exception as e:
        logger.error(f"해시 데이터 조회 오류 ({type_code}:{item_code}): {str(e)}")
        return []

async def extract_field_data(type_code, values_dict):
    """
    특정 타입에 맞는 필드만 추출합니다.
    
    Args:
        type_code (str): 데이터 타입 코드
        values_dict (dict): 원본 데이터 딕셔너리
    
    Returns:
        dict: 추출된 필드 데이터 또는 None
    """
    # 타입별 필요한 필드 정의
    field_mapping = {
        "0D": [  # 주식호가
            "21",  # 호가시간
            # 1~10호가 (직전대비 제외)
            "41", "61", "51", "71",
            "42", "62", "52", "72",
            "43", "63", "53", "73",
            "44", "64", "54", "74",
            "45", "65", "55", "75",
            "46", "66", "56", "76",
            "47", "67", "57", "77",
            "48", "68", "58", "78",
            "49", "69", "59", "79",
            "50", "70", "60", "80",
            # 총잔량 관련
            "121", "125", "23", "24", "128", "129", "138"
        ],
        "0B": [  # 주식체결
            "20",  # 체결시간
            "10", "11", "12", "15", "13", "14",
            "16", "17", "18", "25", "26","27","28", "29", 
            "30", "31", "32", "228", "311", "290", 
            "691", "1890", "1891", "1892", "1030", 
            "1031", "1032", "1071", "1072", "1313", 
            "1315", "1316", "1314"
        ]
    }
    
    if type_code not in field_mapping:
        return None
    
    # 필요한 필드만 추출
    fields_to_extract = field_mapping[type_code]
    extracted_data = {k: v for k, v in values_dict.items() if k in fields_to_extract}
    
    return extracted_data

async def get_keys_by_pattern(redis_client, pattern):
    """
    주어진 패턴과 일치하는 모든 키를 가져옵니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        pattern (str): 키 패턴 (예: "0B:005930:*")
    
    Returns:
        list: 패턴과 일치하는 키 목록
    """
    try:
        keys = await run_redis_command(redis_client.keys, pattern)
        return keys
    except Exception as e:
        logger.error(f"패턴 키 조회 오류 ({pattern}): {str(e)}")
        return []

async def delete_keys_by_pattern(redis_client, pattern):
    """
    주어진 패턴과 일치하는 모든 키를 삭제합니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        pattern (str): 키 패턴 (예: "0B:005930:*")
    
    Returns:
        int: 삭제된 키 수
    """
    try:
        keys = await run_redis_command(redis_client.keys, pattern)
        if not keys:
            return 0
            
        # 키가 많은 경우 파이프라인 사용
        pipeline = redis_client.pipeline()
        for key in keys:
            pipeline.delete(key)
        
        # 파이프라인 실행
        results = await run_redis_command(pipeline.execute)
        return sum(results)  # 삭제된 키 수 합계
    except Exception as e:
        logger.error(f"패턴 키 삭제 오류 ({pattern}): {str(e)}")
        return 0

async def cleanup_old_data(redis_client, max_age_seconds=3600):
    """
    오래된 데이터 정리 (정기적으로 실행)
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        max_age_seconds (int): 최대 보관 시간 (초)
    
    Returns:
        int: 정리된 키 수
    """
    try:
        # 현재 시간 기준 계산
        current_time = time.time()
        deleted_count = 0
        
        # 타임스탬프가 있는 모든 키 패턴
        patterns = ["0B:*:*", "00:*:*", "04:*:*", "02:*:*"]
        
        for pattern in patterns:
            keys = await run_redis_command(redis_client.keys, pattern)
            
            for key in keys:
                # TTL 확인
                ttl = await run_redis_command(redis_client.ttl, key)
                
                # TTL이 음수이거나 max_age_seconds보다 작으면 삭제
                if ttl < 0 or ttl > max_age_seconds:
                    deleted = await run_redis_command(redis_client.delete, key)
                    deleted_count += deleted
        
        logger.info(f"오래된.데이터 정리 완료: {deleted_count}개 키 삭제됨")
        return deleted_count
    except Exception as e:
        logger.error(f"데이터 정리 중 오류 발생: {str(e)}")
        return 0