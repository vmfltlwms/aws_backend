import redis
import logging
from config import settings

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
    client.setex(f"stock:{symbol}", expire_seconds, str(data))

def get_cached_stock_data(symbol):
    """Redis에서 캐싱된 주식 데이터를 가져옵니다."""
    client = get_redis_connection()
    data = client.get(f"stock:{symbol}")
    return data.decode('utf-8') if data else None