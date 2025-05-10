import redis
import logging
from config import settings
from datetime import datetime
import json
import time
import asyncio
from typing import Dict, Any, Optional, List, Union

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
            db=settings.REDIS_DB
        )
        # Redis 연결 테스트
        await run_redis_command(redis_client.ping)
        logging.info("Redis connected successfully")
    except Exception as e:
        logging.error(f"Redis connection error: {e}")
        raise

async def close_redis():
    """Redis 연결을 종료합니다."""
    global redis_client
    if redis_client:
        redis_client.close()
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

async def save_hash_data(redis_client,type_code, item_code, values_dict):
    """
    실시간 데이터를 Redis 해시에 저장 (비동기)
    
    Args:
        type_code (str): 데이터 타입 코드 
        00 : 주문체결 
        02 : 실시간 조건검색 결과   
        04 : 잔고
        0B : 주식체결
        0D : 주식호가
        item_code (str): 종목 코드 (예: "005930")
        values_dict (dict): 필드와 값들의 딕셔너리
    
    Returns:
        bool: 저장 성공 여부
    """
    
    if type_code == "0B" or type_code == "0D": #주식체결, 주식호가
        # 필드 데이터 추출
        values_dict = await extract_field_data(type_code, values_dict)
    
    if type_code == "0D" or type_code == "04": # 주식호가, 잔고 : 최신 데이터만 유지
        try:
            hash_name = f"{type_code}:{item_code}"
            logger.info(f"hash_name redis 데이터 저장 : {hash_name}")

            # 모든 필드를 한번에 저장
            await run_redis_command(redis_client.hmset, hash_name, values_dict)
            
            # 기본 TTL 설정 (필요시 조정)
            await run_redis_command(redis_client.expire, hash_name, 300)  # 5분
            return True
        except Exception as e:
            logger.error(f"해시 데이터 저장 오류 ({type_code}:{item_code}): {str(e)}")
            return False
    
    try:
        timestamp = datetime.now().strftime("%H%M%S%f")[:-3] # 밀리초 단위로 변환
        timestamp_hash_name = f"{type_code}:{item_code}:{timestamp}"
        logger.info(f"hash_name redis 데이터 저장 : {timestamp_hash_name}")

        # 모든 필드를 한번에 저장
        await run_redis_command(redis_client.hmset, timestamp_hash_name, values_dict)
        
        # 기본 TTL 설정 (필요시 조정)
        await run_redis_command(redis_client.expire, timestamp_hash_name, 300)  # 5분
        
        return True
    except Exception as e:
        logger.error(f"해시 데이터 저장 오류 ({type_code}:{item_code}): {str(e)}")
        return False

async def get_hash_data(redis_client, type_code, item_code, limit=10):
    """
    특정 타입과 종목의 모든 타임스탬프 데이터를 가져옵니다 (비동기)
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        type_code (str): 데이터 타입 코드 (예: "0B", "0D")
        item_code (str): 종목 코드 (예: "005930")
        limit (int): 반환할 최대 데이터 수 (기본 10개)
    
    Returns:
        list: 각 타임스탬프별 데이터 딕셔너리 목록 (최신순)
    """
    try:
        # 패턴 검색을 위한 키 형식
        pattern = f"{type_code}:{item_code}:*"
        
        # 모든 매칭 키 찾기
        keys = await run_redis_command(redis_client.keys, pattern)
        
        if not keys:
            return []
        
        # 키를 타임스탬프 기준으로 정렬 (최신순)
        sorted_keys = sorted(keys, key=lambda k: k.decode('utf-8').split(':')[2] if isinstance(k, bytes) else k.split(':')[2], reverse=True)
        
        # 요청한 한도까지만 처리
        keys_to_process = sorted_keys[:limit]
        
        result = []
        for key in keys_to_process:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            # 키에서 타임스탬프 추출
            timestamp = key_str.split(':')[2]
            
            # 해시 데이터 가져오기
            data = await run_redis_command(redis_client.hgetall, key)
            
            if data:
                # 바이트 디코딩 및 숫자 변환
                processed_data = {}
                for k, v in data.items():
                    field = k.decode('utf-8') if isinstance(k, bytes) else k
                    value = v.decode('utf-8') if isinstance(v, bytes) else v
                    
                    # 숫자 문자열인 경우 숫자로 변환 시도
                    try:
                        if value.isdigit() or (value[0] in ['+', '-'] and value[1:].isdigit()):
                            if '.' in value:
                                processed_data[field] = float(value)
                            else:
                                processed_data[field] = int(value)
                            continue
                    except:
                        pass
                        
                    processed_data[field] = value
                
                # 타임스탬프 추가
                processed_data['timestamp'] = timestamp
                result.append(processed_data)
        
        return result
    except Exception as e:
        logger.error(f"모든 해시 데이터 조회 오류 ({type_code}:{item_code}): {str(e)}")
        return []

async def extract_field_data(type_code,values_dict):
    """
    Redis에서 특정 필드의 데이터를 추출합니다.
    
    Returns:
        dict: 필드 데이터
    """
    if type_code == "0D":
        fields_to_extract = [
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
        # 총잔량 관련 (직전대비 제외)
        "121", "125",     # 예상체결가, 예상체결수량
        "23", "24",       # 예상체결가, 예상체결수량
        "128", "129",     # 순매수잔량, 매수비율
        "138"             # 순매도잔량
        ]
    elif type_code == "0B":
        fields_to_extract = [
            "20", # 체결시간
            "10", "11", "12",
            "15", "13", "14",
            "16", "17", "18",
            "25", "26", "29", "30", "31", "32",
            "228", "311", "290", "691",
            "1890", "1891", "1892",
            "1030", "1031", "1032",
            "1071", "1072",
            "1313", "1315", "1316", "1314"
        ]
    else:
        return None

    extracted_data = {k: values_dict.get(k) for k in fields_to_extract}
    return extracted_data

