import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from config import settings

# 글로벌 연결 객체
conn = None

async def init_db():
    """PostgreSQL 데이터베이스 연결을 초기화합니다."""
    global conn
    try:
        conn = psycopg2.connect(
            dbname=settings.PG_DATABASE,
            user=settings.PG_USER,
            password=settings.PG_PASSWORD,
            host=settings.PG_HOST,
            port=settings.PG_PORT
        )
        logging.info("PostgreSQL database connected successfully")
        
        # 테이블 생성 등 초기화 작업 수행
        await create_tables()
    except Exception as e:
        logging.error(f"Database connection error: {e}")
        raise

async def close_db():
    """PostgreSQL 데이터베이스 연결을 종료합니다."""
    global conn
    if conn:
        conn.close()
        conn = None
        logging.info("PostgreSQL database connection closed")

async def create_tables():
    """필요한 테이블을 생성합니다."""
    global conn
    queries = [
        """
        CREATE TABLE IF NOT EXISTS stocks (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(10) NOT NULL,
            name VARCHAR(100) NOT NULL,
            price DECIMAL(10, 2) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        ,
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            stock_id INTEGER REFERENCES stocks(id),
            type VARCHAR(4) NOT NULL CHECK (type IN ('buy', 'sell')),
            quantity INTEGER NOT NULL,
            price DECIMAL(10, 2) NOT NULL,
            transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        ,
        """
            CREATE TABLE IF NOT EXISTS stock_trade_intensity (
                id SERIAL PRIMARY KEY,
                stock_code VARCHAR(10) NOT NULL,
                trade_date DATE NOT NULL,
                trade_time TIME NOT NULL,
                intensity_1min DECIMAL(10, 2) NOT NULL,
                intensity_5min DECIMAL(10, 2) NOT NULL,
                buy_volume_1min INTEGER NOT NULL,
                sell_volume_1min INTEGER NOT NULL,
                buy_volume_5min INTEGER NOT NULL,
                sell_volume_5min INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                UNIQUE (stock_code, trade_date, trade_time)
            );
        """
        ,
        """
            CREATE TABLE IF NOT EXISTS stock_trade_signals (
                id SERIAL PRIMARY KEY,
                stock_code VARCHAR(10) NOT NULL,
                signal_date DATE NOT NULL,
                signal_time TIME NOT NULL,
                signal_type VARCHAR(10) NOT NULL,
                signal_strength DECIMAL(10, 2) NOT NULL,
                intensity_1min DECIMAL(10, 2) NOT NULL,
                intensity_5min DECIMAL(10, 2) NOT NULL,
                change_1min DECIMAL(10, 2) NOT NULL,
                change_5min DECIMAL(10, 2) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """
        ,
        """
            CREATE INDEX IF NOT EXISTS idx_trade_intensity_stock_date ON stock_trade_intensity (stock_code, trade_date);
        """
        ,
        """
            CREATE INDEX IF NOT EXISTS idx_trade_signals_stock_date ON stock_trade_signals (stock_code, signal_date);
        """
        ]
    
    try:
        with conn.cursor() as cur:
            for query in queries:
                cur.execute(query)
        conn.commit()
        logging.info("Database tables created successfully")
    except Exception as e:
        conn.rollback()
        logging.error(f"Error creating tables: {e}")
        raise

def get_db_connection():
    """현재 데이터베이스 연결을 반환합니다."""
    global conn
    if conn is None:
        raise Exception("Database connection not initialized")
    return conn

def execute_query(query, params=None, fetch=True):
    """SQL 쿼리를 실행하고 결과를 반환합니다."""
    connection = get_db_connection()
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or ())
            if fetch:
                result = cur.fetchall()
                return result
            connection.commit()
            return None
    except Exception as e:
        connection.rollback()
        logging.error(f"Query execution error: {e}")
        raise