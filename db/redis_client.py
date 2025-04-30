import redis
import logging
from config import settings
import json
import time
from typing import Dict, Any, Optional, List, Union

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
        redis_client.ping()
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

# Redis 캐싱 함수
def cache_stock_data(symbol, data, expire_seconds=300):
    """주식 데이터를 Redis에 캐싱합니다."""
    client = get_redis_connection()
    client.setex(f"stock:{symbol}", expire_seconds, str(data))\
    

def get_cached_stock_data(symbol):
    """Redis에서 캐싱된 주식 데이터를 가져옵니다."""
    client = get_redis_connection()
    data = client.get(f"stock:{symbol}")
    return data.decode('utf-8') if data else None

def save_data(key, data, expire_seconds=300):
    """Redis에 데이터 저장"""
    client = get_redis_connection()
    
    # 데이터가 딕셔너리나 리스트인 경우 JSON으로 직렬화
    if isinstance(data, (dict, list)):
        data = json.dumps(data)
    
    # 데이터 저장
    client.set(key, data)
    
    # 만료 시간 설정 (선택적)
    if expire_seconds:
        client.expire(key, expire_seconds)

def get_data(key, default=None):
    """Redis에서 데이터 조회"""
    client = get_redis_connection()
    data = client.get(key)
    
    if data is None:
        return default
    
    # 데이터가 JSON 형식인지 확인하고 파싱 시도
    try:
        return json.loads(data)
    except (TypeError, json.JSONDecodeError):
        # JSON이 아니면 그대로 반환
        return data.decode('utf-8') if isinstance(data, bytes) else data

def save_hash_data(hash_name, key, value):
    """Redis 해시에 데이터 저장"""
    client = get_redis_connection()
    
    # 값이 딕셔너리나 리스트인 경우 JSON으로 직렬화
    if isinstance(value, (dict, list)):
        value = json.dumps(value)
    
    # 해시에 저장
    client.hset(hash_name, key, value)

def get_hash_data(hash_name, key, default=None):
    """Redis 해시에서 데이터 조회"""
    client = get_redis_connection()
    value = client.hget(hash_name, key)
    
    if value is None:
        return default
    
    # 데이터가 JSON 형식인지 확인하고 파싱 시도
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        # JSON이 아니면 그대로 반환
        return value.decode('utf-8') if isinstance(value, bytes) else value

def save_realtime_price(stock_code, price_data, expire_seconds=300):
    """실시간 주식 시세 데이터 저장"""
    key = f"realtime:price:{stock_code}"
    save_data(key, price_data, expire_seconds)

def get_realtime_price(stock_code):
    """실시간 주식 시세 데이터 조회"""
    key = f"realtime:price:{stock_code}"
    return get_data(key)

def save_user_subscription(user_id, subscription_data):
    """사용자 구독 정보 저장"""
    hash_name = "user:subscriptions"
    save_hash_data(hash_name, user_id, subscription_data)

def get_user_subscription(user_id):
    """사용자 구독 정보 조회"""
    hash_name = "user:subscriptions"
    return get_hash_data(hash_name, user_id, default={})




def store_realtime_quote(redis_client: redis.Redis, item_code: str, quote_data: Dict[str, Any], expire_seconds: int = 60) -> bool:
    """
    실시간 호가 데이터를 Redis에 저장합니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        item_code: 종목 코드 (예: '005930')
        quote_data: 호가 데이터 딕셔너리
        expire_seconds: 데이터 만료 시간(초)
        
    Returns:
        bool: 저장 성공 여부
    """
    try:
        # 키 이름 생성 (실시간 호가 데이터용)
        key = f"quote:{item_code}"
        
        # 타임스탬프 추가
        quote_data['timestamp'] = int(time.time())
        
        # JSON으로 직렬화하여 저장
        redis_client.set(key, json.dumps(quote_data))
        
        # 만료 시간 설정
        if expire_seconds > 0:
            redis_client.expire(key, expire_seconds)
        
        # 최근 업데이트 목록에 추가 (정렬된 집합 사용)
        redis_client.zadd("recent_quotes", {item_code: time.time()})
        
        return True
    except Exception as e:
        print(f"Error storing quote data: {e}")
        return False

def get_realtime_quote(redis_client: redis.Redis, item_code: str) -> Optional[Dict[str, Any]]:
    """
    Redis에서 실시간 호가 데이터를 조회합니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        item_code: 종목 코드 (예: '005930')
        
    Returns:
        Optional[Dict]: 호가 데이터 또는 None (데이터 없을 경우)
    """
    try:
        key = f"quote:{item_code}"
        data = redis_client.get(key)
        
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        print(f"Error retrieving quote data: {e}")
        return None

def get_recent_updated_quotes(redis_client: redis.Redis, count: int = 10) -> List[str]:
    """
    최근에 업데이트된 종목 코드 목록을 가져옵니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        count: 가져올 종목 수
        
    Returns:
        List[str]: 최근 업데이트된 종목 코드 목록
    """
    try:
        # 정렬된 집합에서 가장 최근(점수가 높은) 항목부터 가져옴
        items = redis_client.zrevrange("recent_quotes", 0, count-1)
        return [item.decode('utf-8') for item in items]
    except Exception as e:
        print(f"Error retrieving recent quotes: {e}")
        return []

def store_realtime_transaction(redis_client: redis.Redis, item_code: str, transaction_data: Dict[str, Any], max_transactions: int = 100) -> bool:
    """
    실시간 체결 데이터를 Redis 리스트에 저장합니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        item_code: 종목 코드
        transaction_data: 체결 데이터
        max_transactions: 저장할 최대 체결 수
        
    Returns:
        bool: 저장 성공 여부
    """
    try:
        # 키 이름 생성 (실시간 체결 데이터용 리스트)
        key = f"transactions:{item_code}"
        
        # 타임스탬프 추가
        transaction_data['timestamp'] = int(time.time())
        
        # 리스트 왼쪽에 추가 (가장 최근 데이터가 리스트의 첫 번째 요소)
        redis_client.lpush(key, json.dumps(transaction_data))
        
        # 리스트 크기 제한
        redis_client.ltrim(key, 0, max_transactions - 1)
        
        # 24시간 만료 시간 설정
        redis_client.expire(key, 86400)
        
        return True
    except Exception as e:
        print(f"Error storing transaction data: {e}")
        return False

def get_recent_transactions(redis_client: redis.Redis, item_code: str, count: int = 10) -> List[Dict[str, Any]]:
    """
    최근 체결 데이터를 가져옵니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        item_code: 종목 코드
        count: 가져올 체결 수
        
    Returns:
        List[Dict]: 최근 체결 데이터 목록
    """
    try:
        key = f"transactions:{item_code}"
        
        # 리스트에서 여러 항목 가져오기
        items = redis_client.lrange(key, 0, count - 1)
        
        # JSON 파싱하여 반환
        return [json.loads(item) for item in items]
    except Exception as e:
        print(f"Error retrieving transactions: {e}")
        return []

def store_realtime_market_data(redis_client: redis.Redis, data: Dict[str, Any]) -> bool:
    """
    실시간 시장 데이터를 처리하여 Redis에 저장합니다.
    
    Args:
        redis_client: Redis 클라이언트 인스턴스
        data: 실시간 데이터
        
    Returns:
        bool: 처리 성공 여부
    """
    try:
        if data.get('trnm') != 'REAL':
            return False
            
        for item_data in data.get('data', []):
            item_code = item_data.get('item')
            data_type = item_data.get('type')
            values = item_data.get('values', {})
            
            if not item_code or not data_type:
                continue
                
            # 데이터 타입에 따른 처리
            if data_type == '0D':  # 호가 데이터
                store_realtime_quote(redis_client, item_code, values)
                
            elif data_type == '01':  # 체결 데이터 (가정)
                store_realtime_transaction(redis_client, item_code, values)
                
            # 다른 데이터 타입도 필요에 따라 처리 가능
                
        return True
    except Exception as e:
        print(f"Error processing market data: {e}")
        return False

async def handle_realtime_data(data):
    """
    수신한 실시간 데이터를 처리합니다.
    """
    if not isinstance(data, dict):
        try:
            data = json.loads(data)
        except:
            print("Invalid data format")
            return False
    
    # Redis 클라이언트 가져오기
    redis_client = get_redis_connection()
    
    # 실시간 데이터 저장
    return store_realtime_market_data(redis_client, data)        