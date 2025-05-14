# db/monitoring.py

import logging
import json
from datetime import datetime
from typing import List, Dict, Optional
from db.postgres import db
from db.redis_client import get_redis_connection, get_keys_by_pattern

logger = logging.getLogger(__name__)

class DataIntegrityMonitor:
    """데이터 무결성 모니터링 및 복구 시스템"""
    
    def __init__(self):
        self.db = db
    
    async def check_data_gaps(self, stock_code: str, date: datetime) -> List[Dict]:
        """특정 종목의 데이터 갭 확인"""
        query = """
            WITH time_series AS (
                SELECT 
                    trade_timestamp,
                    LAG(trade_timestamp) OVER (ORDER BY trade_timestamp) as prev_timestamp,
                    redis_key,
                    price,
                    volume
                FROM stock_executions
                WHERE stock_code = %s 
                AND DATE(trade_timestamp) = %s
                ORDER BY trade_timestamp
            )
            SELECT 
                prev_timestamp,
                trade_timestamp,
                redis_key,
                EXTRACT(EPOCH FROM (trade_timestamp - prev_timestamp)) as gap_seconds,
                price,
                volume
            FROM time_series
            WHERE EXTRACT(EPOCH FROM (trade_timestamp - prev_timestamp)) > 1
            ORDER BY trade_timestamp
        """
        
        return await self.db.execute_query(query, (stock_code, date.date()))
    
    async def find_missing_data(self, stock_code: str, start_time: datetime, end_time: datetime) -> List[str]:
        """Redis에서 누락된 데이터 찾기"""
        redis_client = get_redis_connection()
        
        # Redis에서 해당 시간 범위의 키 찾기
        pattern = f"0B:{stock_code}:*"
        all_keys = await get_keys_by_pattern(redis_client, pattern)
        
        # 시간 범위 내의 키 필터링
        time_range_keys = []
        start_str = start_time.strftime("%H%M%S%f")[:-3]
        end_str = end_time.strftime("%H%M%S%f")[:-3]
        
        for key in all_keys:
            timestamp = key.split(':')[2]
            if start_str <= timestamp <= end_str:
                time_range_keys.append(key)
        
        # DB에 이미 있는 키 확인
        existing_keys = await self._get_existing_keys(time_range_keys)
        
        # 누락된 키 반환
        missing_keys = [key for key in time_range_keys if key not in existing_keys]
        
        logger.info(f"Found {len(missing_keys)} missing records for {stock_code} between {start_time} and {end_time}")
        return missing_keys
    
    async def _get_existing_keys(self, redis_keys: List[str]) -> set:
        """DB에 이미 존재하는 키 확인"""
        if not redis_keys:
            return set()
        
        placeholders = ','.join(['%s'] * len(redis_keys))
        query = f"""
            SELECT DISTINCT redis_key 
            FROM stock_executions 
            WHERE redis_key IN ({placeholders})
        """
        
        results = await self.db.execute_query(query, tuple(redis_keys))
        return {row['redis_key'] for row in results}
    
    async def recover_missing_data(self, stock_code: str, missing_keys: List[str]) -> int:
        """누락된 데이터 복구"""
        from workers.redis_to_postgres_worker import RedisToPostgresWorker
        
        worker = RedisToPostgresWorker()
        redis_client = get_redis_connection()
        recovered_count = 0
        
        batch_records = []
        for key in missing_keys:
            try:
                record = await worker._prepare_execution_record_from_key(redis_client, key)
                if record:
                    batch_records.append(record)
                    
                    # 배치 크기 도달 시 저장
                    if len(batch_records) >= 1000:
                        success = await self.db.insert_stock_executions_batch(batch_records)
                        if success:
                            recovered_count += len(batch_records)
                        batch_records = []
                        
            except Exception as e:
                logger.error(f"Error recovering key {key}: {e}")
        
        # 남은 레코드 저장
        if batch_records:
            success = await self.db.insert_stock_executions_batch(batch_records)
            if success:
                recovered_count += len(batch_records)
        
        logger.info(f"Recovered {recovered_count} records for {stock_code}")
        return recovered_count
    
    async def generate_daily_report(self, date: Optional[datetime] = None) -> Dict:
        """일일 데이터 무결성 리포트 생성"""
        if not date:
            date = datetime.now()
        
        query = """
            SELECT 
                stock_code,
                COUNT(*) as record_count,
                MIN(trade_timestamp) as first_trade,
                MAX(trade_timestamp) as last_trade,
                COUNT(DISTINCT redis_key) as unique_keys,
                SUM(volume) as total_volume,
                AVG(price) as avg_price,
                MIN(price) as min_price,
                MAX(price) as max_price
            FROM stock_executions
            WHERE DATE(trade_timestamp) = %s
            GROUP BY stock_code
            ORDER BY total_volume DESC
        """
        
        stats = await self.db.execute_query(query, (date.date(),))
        
        # 각 종목별 데이터 갭 분석
        gap_summary = []
        total_gaps = 0
        
        for stat in stats:
            gaps = await self.check_data_gaps(stat['stock_code'], date)
            if gaps:
                gap_info = {
                    'stock_code': stat['stock_code'],
                    'gap_count': len(gaps),
                    'max_gap_seconds': max(gap['gap_seconds'] for gap in gaps),
                    'total_gap_seconds': sum(gap['gap_seconds'] for gap in gaps)
                }
                gap_summary.append(gap_info)
                total_gaps += len(gaps)
        
        # 전체 요약
        total_records = sum(stat['record_count'] for stat in stats)
        
        report = {
            "report_date": date.isoformat(),
            "summary": {
                "total_stocks": len(stats),
                "total_records": total_records,
                "total_gaps": total_gaps,
                "stocks_with_gaps": len(gap_summary)
            },
            "stock_stats": stats[:20],  # 상위 20개 종목
            "gap_analysis": gap_summary,
            "generated_at": datetime.now().isoformat()
        }
        
        # 리포트 저장
        await self._save_report(report)
        
        return report
    
    async def _save_report(self, report: Dict):
        """리포트를 DB에 저장"""
        query = """
            INSERT INTO data_integrity_logs (
                check_time, 
                issue_type, 
                issue_details
            ) VALUES (
                %s, 
                'daily_report', 
                %s
            )
        """
        
        await self.db.execute_query(
            query,
            (report['report_date'], json.dumps(report))
        )
    
    async def auto_fix_gaps(self, max_gap_seconds: int = 60) -> int:
        """자동으로 데이터 갭 수정"""
        today = datetime.now()
        total_recovered = 0
        
        # 모든 종목의 갭 찾기
        stock_codes_query = """
            SELECT DISTINCT stock_code 
            FROM stock_executions 
            WHERE DATE(trade_timestamp) = %s
        """
        
        stocks = await self.db.execute_query(stock_codes_query, (today.date(),))
        
        for stock in stocks:
            stock_code = stock['stock_code']
            gaps = await self.check_data_gaps(stock_code, today)
            
            # 작은 갭만 자동 수정
            for gap in gaps:
                if gap['gap_seconds'] <= max_gap_seconds:
                    # 누락된 데이터 찾기 및 복구
                    missing_keys = await self.find_missing_data(
                        stock_code,
                        gap['prev_timestamp'],
                        gap['trade_timestamp']
                    )
                    
                    if missing_keys:
                        recovered = await self.recover_missing_data(stock_code, missing_keys)
                        total_recovered += recovered
        
        logger.info(f"Auto-fix completed. Total recovered: {total_recovered}")
        return total_recovered
    
    async def run_monitoring_cycle(self):
        """모니터링 주기 실행"""
        logger.info("Starting monitoring cycle")
        
        try:
            # 1. 자동 갭 수정
            recovered = await self.auto_fix_gaps()
            
            # 2. 일일 리포트 생성
            report = await self.generate_daily_report()
            
            # 3. 알림 전송 (필요한 경우)
            if report['summary']['total_gaps'] > 100:
                logger.warning(f"High number of gaps detected: {report['summary']['total_gaps']}")
            
            logger.info("Monitoring cycle completed")
            
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")

# 글로벌 모니터 인스턴스
monitor = DataIntegrityMonitor()

# 편의 함수들
async def check_data_integrity(stock_code: str, date: datetime = None):
    """데이터 무결성 확인"""
    if not date:
        date = datetime.now()
    return await monitor.check_data_gaps(stock_code, date)

async def recover_missing_data(stock_code: str, start_time: datetime, end_time: datetime):
    """누락된 데이터 복구"""
    missing_keys = await monitor.find_missing_data(stock_code, start_time, end_time)
    if missing_keys:
        return await monitor.recover_missing_data(stock_code, missing_keys)
    return 0

async def generate_daily_report(date: datetime = None):
    """일일 리포트 생성"""
    return await monitor.generate_daily_report(date)

async def run_monitoring():
    """모니터링 실행"""
    await monitor.run_monitoring_cycle()