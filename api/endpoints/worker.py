# api/endpoints/worker.py

import logging
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime, timedelta
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/status")
async def check_worker_status():
    """워커 상태 확인 엔드포인트"""
    conn = None
    try:
        # DB 연결
        conn = psycopg2.connect(
            dbname=settings.PG_DATABASE,
            user=settings.PG_USER,
            password=settings.PG_PASSWORD,
            host=settings.PG_HOST,
            port=settings.PG_PORT,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        
        # 커서 생성
        cur = conn.cursor()
        
        # 최근 저장된 데이터 조회
        query = """
            SELECT 
                COUNT(*) as total_count,
                MAX(created_at) as last_created,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 minute') as last_minute_count,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '5 minutes') as last_5minute_count,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') as last_hour_count,
                COUNT(DISTINCT stock_code) as unique_stocks
            FROM stock_executions
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """
        
        cur.execute(query)
        result = cur.fetchone()
        
        if not result:
            return {
                "status": "warning",
                "message": "No data found in the last 24 hours"
            }
        
        # 마지막 저장 시간
        last_created = result['last_created']
        time_since_last = None
        
        if last_created:
            time_since_last = (datetime.now() - last_created).total_seconds()
            
        return {
            "status": "active" if time_since_last and time_since_last < 60 else "warning",
            "data": {
                "total_records_24h": result['total_count'],
                "unique_stocks": result['unique_stocks'],
                "last_created": last_created.isoformat() if last_created else None,
                "seconds_since_last_record": time_since_last,
                "records_last_minute": result['last_minute_count'],
                "records_last_5minutes": result['last_5minute_count'],
                "records_last_hour": result['last_hour_count']
            }
        }
        
    except Exception as e:
        logger.error(f"Error checking worker status: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": str(e)
            }
        )
    finally:
        if conn:
            conn.close()