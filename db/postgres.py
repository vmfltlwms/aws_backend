import asyncio
import logging
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from config import settings

logger = logging.getLogger(__name__)

class PostgresDatabase:
    """향상된 PostgreSQL 데이터베이스 관리 클래스"""
    
    def __init__(self):
        self.pool = None
        self.db_params = {
            "dbname": settings.PG_DATABASE,
            "user": settings.PG_USER,
            "password": settings.PG_PASSWORD,
            "host": settings.PG_HOST,
            "port": settings.PG_PORT
        }
    
    async def init_db(self, min_connections: int = 5, max_connections: int = 20):
        """데이터베이스 연결 풀 초기화"""
        try:
            self.pool = ThreadedConnectionPool(
                min_connections,
                max_connections,
                **self.db_params
            )
            logger.info(f"PostgreSQL connection pool initialized (min: {min_connections}, max: {max_connections})")
            
            # 테이블 생성 및 초기화
            await self.create_tables()
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise
    
    async def close_db(self):
        """데이터베이스 연결 풀 종료"""
        if self.pool:
            self.pool.closeall()
            self.pool = None
            logger.info("PostgreSQL connection pool closed")
    
    @contextmanager
    def get_connection(self):
        """컨텍스트 매니저를 사용한 연결 관리"""
        conn = None
        try:
            conn = self.pool.getconn()
            yield conn
        finally:
            if conn:
                self.pool.putconn(conn)
    
    @contextmanager
    def get_cursor(self, cursor_factory=None):
        """커서를 위한 컨텍스트 매니저"""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                cursor.close()
    
    async def create_tables(self):
        """필요한 테이블들을 생성"""
        table_queries = [
            # 주식 기본 정보 테이블
            """
            CREATE TABLE IF NOT EXISTS stocks (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(10) NOT NULL UNIQUE,
                name VARCHAR(100) NOT NULL,
                market_type VARCHAR(20),
                sector VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # 주식 체결 데이터 테이블 (개선된 버전)
            """
            CREATE TABLE IF NOT EXISTS stock_executions (
                id SERIAL PRIMARY KEY,
                stock_code VARCHAR(10) NOT NULL,
                execution_time VARCHAR(6) NOT NULL,
                trade_time VARCHAR(9) NOT NULL,
                trade_timestamp TIMESTAMP(3) NOT NULL,
                redis_key VARCHAR(50),
                price DECIMAL(10, 2) NOT NULL,
                change DECIMAL(10, 2),
                best_ask_price DECIMAL(10, 2),
                best_bid_price DECIMAL(10, 2),
                volume INTEGER,
                strength DECIMAL(10, 2),
                sell_total_volume INTEGER,
                buy_total_volume INTEGER,
                sell_resistance DECIMAL(10, 2),
                buy_support DECIMAL(10, 2),
                buy_sell_ratio DECIMAL(10, 2),
                is_processed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT unique_execution_timestamp UNIQUE (stock_code, trade_timestamp)
            )
            """,
            
            # 주식 호가 스냅샷 테이블
            """
            CREATE TABLE IF NOT EXISTS stock_order_book_snapshots (
                id SERIAL PRIMARY KEY,
                stock_code VARCHAR(10) NOT NULL,
                snapshot_time TIMESTAMP(3) NOT NULL,
                ask_price_1 DECIMAL(10, 2),
                ask_volume_1 INTEGER,
                ask_price_2 DECIMAL(10, 2),
                ask_volume_2 INTEGER,
                ask_price_3 DECIMAL(10, 2),
                ask_volume_3 INTEGER,
                ask_price_4 DECIMAL(10, 2),
                ask_volume_4 INTEGER,
                ask_price_5 DECIMAL(10, 2),
                ask_volume_5 INTEGER,
                bid_price_1 DECIMAL(10, 2),
                bid_volume_1 INTEGER,
                bid_price_2 DECIMAL(10, 2),
                bid_volume_2 INTEGER,
                bid_price_3 DECIMAL(10, 2),
                bid_volume_3 INTEGER,
                bid_price_4 DECIMAL(10, 2),
                bid_volume_4 INTEGER,
                bid_price_5 DECIMAL(10, 2),
                bid_volume_5 INTEGER,
                total_ask_volume INTEGER,
                total_bid_volume INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT unique_order_book_snapshot UNIQUE (stock_code, snapshot_time)
            )
            """,
            
            # 거래 강도 분석 테이블
            """
            CREATE TABLE IF NOT EXISTS stock_trade_intensity (
                id SERIAL PRIMARY KEY,
                stock_code VARCHAR(10) NOT NULL,
                trade_date DATE NOT NULL,
                trade_time TIME NOT NULL,
                intensity_1min DECIMAL(10, 2),
                intensity_5min DECIMAL(10, 2),
                intensity_10min DECIMAL(10, 2),
                buy_volume_1min INTEGER,
                sell_volume_1min INTEGER,
                buy_volume_5min INTEGER,
                sell_volume_5min INTEGER,
                price_change_1min DECIMAL(10, 2),
                price_change_5min DECIMAL(10, 2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (stock_code, trade_date, trade_time)
            )
            """,
            
            # 거래 신호 테이블
            """
            CREATE TABLE IF NOT EXISTS stock_trade_signals (
                id SERIAL PRIMARY KEY,
                stock_code VARCHAR(10) NOT NULL,
                signal_time TIMESTAMP(3) NOT NULL,
                signal_type VARCHAR(50) NOT NULL,
                signal_strength DECIMAL(10, 2),
                price_at_signal DECIMAL(10, 2),
                volume_at_signal INTEGER,
                intensity_1min DECIMAL(10, 2),
                intensity_5min DECIMAL(10, 2),
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            
            # 데이터 무결성 로그 테이블
            """
            CREATE TABLE IF NOT EXISTS data_integrity_logs (
                id SERIAL PRIMARY KEY,
                check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                stock_code VARCHAR(10),
                issue_type VARCHAR(50),
                issue_details JSONB,
                resolved BOOLEAN DEFAULT FALSE,
                resolved_at TIMESTAMP
            )
            """
        ]
        
        # 인덱스 생성 쿼리
        index_queries = [
            # stock_executions 인덱스
            """
            CREATE INDEX IF NOT EXISTS idx_executions_stock_timestamp 
            ON stock_executions(stock_code, trade_timestamp DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_executions_timestamp 
            ON stock_executions(trade_timestamp DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_executions_redis_key 
            ON stock_executions(redis_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_executions_unprocessed 
            ON stock_executions(is_processed) WHERE is_processed = FALSE
            """,
            
            # stock_order_book_snapshots 인덱스
            """
            CREATE INDEX IF NOT EXISTS idx_order_book_stock_time 
            ON stock_order_book_snapshots(stock_code, snapshot_time DESC)
            """,
            
            # stock_trade_intensity 인덱스
            """
            CREATE INDEX IF NOT EXISTS idx_intensity_stock_date 
            ON stock_trade_intensity(stock_code, trade_date DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_intensity_date_time 
            ON stock_trade_intensity(trade_date DESC, trade_time DESC)
            """,
            
            # stock_trade_signals 인덱스
            """
            CREATE INDEX IF NOT EXISTS idx_signals_stock_time 
            ON stock_trade_signals(stock_code, signal_time DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_signals_type_time 
            ON stock_trade_signals(signal_type, signal_time DESC)
            """
        ]
        
        try:
            # 테이블 생성 - 동기 방식으로 실행
            for query in table_queries:
                try:
                    self._execute_query_sync(query)
                    logger.info(f"Table created or verified: {query.split()[5]}")
                except Exception as e:
                    logger.error(f"Error creating table: {e}")
                    raise
            
            # 인덱스 생성 - 동기 방식으로 실행
            for query in index_queries:
                try:
                    self._execute_query_sync(query)
                    logger.info(f"Index created or verified: {query.split()[5]}")
                except Exception as e:
                    logger.error(f"Error creating index: {e}")
                    raise
            
            logger.info("Database tables and indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            raise
    
    async def execute_query(self, query: str, params: Optional[Tuple] = None) -> List[Dict]:
        """쿼리 실행 (비동기)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._execute_query_sync(query, params)
        )
    
    def _execute_query_sync(self, query: str, params: Optional[Tuple] = None) -> List[Dict]:
        """쿼리 실행 (동기)"""
        with self.get_cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params or ())
            
            # SELECT 쿼리인 경우 결과 반환
            if cursor.description:
                return cursor.fetchall()
            
            return []
    
    async def execute_many(self, query: str, params_list: List[Tuple]) -> None:
        """여러 파라미터로 쿼리 실행"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._execute_many_sync(query, params_list)
        )
    
    def _execute_many_sync(self, query: str, params_list: List[Tuple]) -> None:
        """여러 파라미터로 쿼리 실행 (동기)"""
        with self.get_cursor() as cursor:
            cursor.executemany(query, params_list)
    
    async def execute_values(self, query: str, values: List[Tuple]) -> None:
        """psycopg2.extras.execute_values를 사용한 대량 삽입"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._execute_values_sync(query, values)
        )
    
    def _execute_values_sync(self, query: str, values: List[Tuple]) -> None:
        """psycopg2.extras.execute_values를 사용한 대량 삽입 (동기)"""
        with self.get_cursor() as cursor:
            execute_values(cursor, query, values)
    
    async def insert_stock_executions_batch(self, records: List[Dict[str, Any]]) -> bool:
        """주식 체결 데이터 배치 삽입"""
        try:
            values = []
            for record in records:
                values.append((
                    record["stock_code"],
                    record["execution_time"],
                    record["trade_time"],
                    record["trade_timestamp"],
                    record.get("redis_key"),
                    record["price"],
                    record.get("change"),
                    record.get("best_ask_price"),
                    record.get("best_bid_price"),
                    record.get("volume"),
                    record.get("strength"),
                    record.get("sell_total_volume"),
                    record.get("buy_total_volume"),
                    record.get("sell_resistance"),
                    record.get("buy_support"),
                    record.get("buy_sell_ratio")
                ))
            
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
                    buy_sell_ratio = EXCLUDED.buy_sell_ratio,
                    updated_at = CURRENT_TIMESTAMP
            """
            
            await self.execute_values(query, values)
            return True
            
        except Exception as e:
            logger.error(f"Error inserting stock executions batch: {e}")
            return False
    
    async def get_latest_execution(self, stock_code: str) -> Optional[Dict]:
        """특정 종목의 최신 체결 데이터 조회"""
        query = """
            SELECT * FROM stock_executions 
            WHERE stock_code = %s 
            ORDER BY trade_timestamp DESC 
            LIMIT 1
        """
        
        results = await self.execute_query(query, (stock_code,))
        return results[0] if results else None
    
    async def get_executions_by_time_range(
        self, 
        stock_code: str, 
        start_time: datetime, 
        end_time: datetime,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """시간 범위로 체결 데이터 조회"""
        query = """
            SELECT * FROM stock_executions 
            WHERE stock_code = %s 
            AND trade_timestamp BETWEEN %s AND %s 
            ORDER BY trade_timestamp ASC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        return await self.execute_query(query, (stock_code, start_time, end_time))
    
    async def check_data_integrity(self, stock_code: str, date: datetime) -> List[Dict]:
        """데이터 무결성 검사"""
        query = """
            WITH time_gaps AS (
                SELECT 
                    trade_timestamp,
                    LAG(trade_timestamp) OVER (ORDER BY trade_timestamp) as prev_timestamp,
                    redis_key
                FROM stock_executions
                WHERE stock_code = %s 
                AND DATE(trade_timestamp) = %s
            )
            SELECT 
                prev_timestamp,
                trade_timestamp,
                EXTRACT(EPOCH FROM (trade_timestamp - prev_timestamp)) as gap_seconds,
                redis_key
            FROM time_gaps
            WHERE EXTRACT(EPOCH FROM (trade_timestamp - prev_timestamp)) > 1
            ORDER BY trade_timestamp
        """
        
        return await self.execute_query(query, (stock_code, date.date()))
    
    async def get_stock_summary(self, stock_code: str, date: datetime) -> Dict:
        """종목별 일일 요약 정보"""
        query = """
            SELECT 
                stock_code,
                DATE(trade_timestamp) as trade_date,
                COUNT(*) as total_records,
                MIN(trade_timestamp) as first_trade,
                MAX(trade_timestamp) as last_trade,
                MIN(price) as min_price,
                MAX(price) as max_price,
                AVG(price) as avg_price,
                SUM(volume) as total_volume,
                AVG(strength) as avg_strength
            FROM stock_executions
            WHERE stock_code = %s 
            AND DATE(trade_timestamp) = %s
            GROUP BY stock_code, DATE(trade_timestamp)
        """
        
        results = await self.execute_query(query, (stock_code, date.date()))
        return results[0] if results else {}
    
    async def mark_as_processed(self, record_ids: List[int]) -> None:
        """레코드를 처리됨으로 표시"""
        query = "UPDATE stock_executions SET is_processed = TRUE WHERE id = ANY(%s)"
        await self.execute_query(query, (record_ids,))
    
    async def get_unprocessed_records(self, limit: int = 1000) -> List[Dict]:
        """미처리 레코드 조회"""
        query = """
            SELECT * FROM stock_executions 
            WHERE is_processed = FALSE 
            ORDER BY trade_timestamp ASC 
            LIMIT %s
        """
        
        return await self.execute_query(query, (limit,))
    
    async def vacuum_analyze(self, table_name: str = None):
        """VACUUM ANALYZE 실행 (성능 최적화)"""
        try:
            with self.get_connection() as conn:
                old_isolation_level = conn.isolation_level
                conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                
                with conn.cursor() as cursor:
                    if table_name:
                        cursor.execute(f"VACUUM ANALYZE {table_name}")
                    else:
                        cursor.execute("VACUUM ANALYZE")
                
                conn.set_isolation_level(old_isolation_level)
                logger.info(f"VACUUM ANALYZE completed for {table_name or 'all tables'}")
        except Exception as e:
            logger.error(f"Error during VACUUM ANALYZE: {e}")
    
    async def get_table_stats(self) -> List[Dict]:
        """테이블 통계 정보 조회"""
        query = """
            SELECT 
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
                n_live_tup as row_count,
                n_dead_tup as dead_rows,
                last_vacuum,
                last_autovacuum,
                last_analyze
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
        """
        
        return await self.execute_query(query)
    
    async def verify_tables_exist(self) -> Dict[str, bool]:
        """생성된 테이블 존재 여부 확인"""
        query = """
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """
        
        results = await self.execute_query(query)
        existing_tables = {row['tablename'] for row in results}
        
        expected_tables = [
            'stocks',
            'stock_executions',
            'stock_order_book_snapshots',
            'stock_trade_intensity',
            'stock_trade_signals',
            'data_integrity_logs'
        ]
        
        table_status = {}
        for table in expected_tables:
            table_status[table] = table in existing_tables
            
        return table_status

# 글로벌 데이터베이스 인스턴스
db = PostgresDatabase()

# 기존 API와의 호환성을 위한 함수들
async def init_db():
    """데이터베이스 초기화 (호환성)"""
    await db.init_db()

async def close_db():
    """데이터베이스 종료 (호환성)"""
    await db.close_db()

def get_db_connection():
    """데이터베이스 연결 반환 (호환성)"""
    if not db.pool:
        raise Exception("Database not initialized")
    return db.pool.getconn()

def execute_query(query: str, params: Optional[Tuple] = None, fetch: bool = True):
    """쿼리 실행 (호환성)"""
    result = db._execute_query_sync(query, params)
    return result if fetch else None