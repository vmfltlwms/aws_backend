# service/trade_intensity_signal.py

import logging
import json
import time
import datetime
from typing import Dict, List, Optional
import redis

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("trade_intensity_signal")

class TradeIntensitySignal:
    """
    실시간 체결 데이터를 수신하여 체결강도를 계산하고 매매 시그널을 생성하는 클래스
    """
    
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0, redis_password=''):
        """
        초기화
        
        Args:
            redis_host: Redis 호스트
            redis_port: Redis 포트
            redis_db: Redis DB 번호
            redis_password: Redis 비밀번호
        """
        # Redis 클라이언트 초기화
        self.redis = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            decode_responses=True  # 결과를 문자열로 디코딩
        )
        
        # 모니터링 중인 종목 목록
        self.monitored_stocks = set()
        
        logger.info("TradeIntensitySignal 서비스 초기화 완료")
    
    def add_stock(self, stock_code: str) -> bool:
        """
        모니터링할 종목 추가
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 성공 여부
        """
        try:
            # 종목코드 6자리 확인
            if not stock_code.isdigit() or len(stock_code) != 6:
                logger.warning(f"유효하지 않은 종목코드: {stock_code}")
                return False
                
            # 모니터링 목록에 추가
            self.monitored_stocks.add(stock_code)
            
            # Redis에 초기 데이터 설정
            trade_counts_key = f"trade_counts:{stock_code}"
            if not self.redis.exists(trade_counts_key):
                self.redis.hset(trade_counts_key, mapping={
                    "buy_volume_1min": 0,
                    "sell_volume_1min": 0,
                    "buy_volume_5min": 0,
                    "sell_volume_5min": 0,
                    "last_update": int(time.time())
                })
                
            logger.info(f"종목 모니터링 추가: {stock_code}")
            return True
        except Exception as e:
            logger.error(f"종목 추가 오류: {str(e)}")
            return False
    
    def remove_stock(self, stock_code: str) -> bool:
        """
        모니터링 종목 제거
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 성공 여부
        """
        try:
            if stock_code in self.monitored_stocks:
                self.monitored_stocks.remove(stock_code)
                logger.info(f"종목 모니터링 제거: {stock_code}")
            return True
        except Exception as e:
            logger.error(f"종목 제거 오류: {str(e)}")
            return False
    
    def process_realtime_data(self, data: Dict) -> bool:
        """
        실시간 데이터 처리
        
        Args:
            data: 실시간 데이터 (키움 API에서 받은 데이터)
            
        Returns:
            bool: 처리 성공 여부
        """
        try:
            # 데이터 형식 확인
            if "trnm" not in data or data["trnm"] != "REAL":
                return False
            
            for item_data in data.get("data", []):
                # 데이터 타입 및 종목코드 확인
                data_type = item_data.get("type")  # 데이터 타입
                item_code = item_data.get("item")  # 종목코드
                values = item_data.get("values", {})  # 데이터 필드
                
                # 주식체결(0B) 데이터만 처리
                if data_type != "0B" or not item_code:
                    continue
                    
                # 모니터링 중인 종목만 처리
                if item_code not in self.monitored_stocks:
                    continue
                
                # 15번 필드 (체결량): 매도(-), 매수(+)
                volume_str = values.get("15", "0")
                
                # 부호 확인
                is_buy = not volume_str.startswith("-")
                
                # 부호 제거 후 정수로 변환
                try:
                    volume = abs(int(volume_str))
                except ValueError:
                    # 숫자 변환 실패 시 기본값 0 사용
                    volume = 0
                
                # 거래량이 0이면 처리하지 않음
                if volume == 0:
                    continue
                
                # 20번 필드 (체결시간) 사용
                trade_time_str = values.get("20", "")
                
                # 체결시간 파싱 (HHMMSS 형식)
                if trade_time_str and len(trade_time_str) == 6:
                    try:
                        # 오늘 날짜 가져오기
                        today = datetime.now().strftime("%Y%m%d")
                        
                        # 체결시간 파싱 (YYYYMMDD HHMMSS 형식)
                        trade_datetime_str = f"{today} {trade_time_str}"
                        trade_datetime = datetime.strptime(trade_datetime_str, "%Y%m%d %H%M%S")
                        
                        # UNIX 타임스탬프로 변환
                        trade_timestamp = int(trade_datetime.timestamp())
                    except Exception as e:
                        # 파싱 실패 시 현재 시간 사용
                        logger.warning(f"체결시간 파싱 실패: {trade_time_str}, 오류: {str(e)}")
                        trade_timestamp = int(time.time())
                else:
                    # 체결시간 없으면 현재 시간 사용
                    trade_timestamp = int(time.time())
                
                # 체결 데이터 저장
                self._store_trade_data(item_code, trade_timestamp, volume, is_buy)
                
                # 체결강도 계산 및 시그널 생성
                intensity_result = self._calculate_intensity(item_code, trade_timestamp)
                
                # 로그 출력
                logger.debug(f"체결강도 계산 결과: {item_code} - 1분: {intensity_result['intensity_1min']}%, 5분: {intensity_result['intensity_5min']}%")
            
            return True
        except Exception as e:
            logger.error(f"실시간 데이터 처리 오류: {str(e)}")
            return False
    
    def _store_trade_data(self, stock_code: str, timestamp: int, volume: int, is_buy: bool) -> None:
        """
        체결 데이터 저장 - Redis에는 5분간의 데이터만 저장
        
        Args:
            stock_code: 종목코드
            timestamp: 체결 시간 (UNIX timestamp)
            volume: 체결량
            is_buy: 매수 여부 (True: 매수, False: 매도)
        """
        try:
            # 체결 데이터 저장
            trade_data = {
                "timestamp": timestamp,
                "volume": volume,
                "is_buy": is_buy
            }
            
            # Redis에 체결 데이터 저장
            trade_key = f"trade:{stock_code}:{timestamp}"
            self.redis.set(trade_key, json.dumps(trade_data))
            self.redis.expire(trade_key,300)  # 10분 후 만료
            
            # 최근 체결 이력에 추가 (시간 기준 정렬)
            trades_key = f"trades:{stock_code}"
            self.redis.zadd(trades_key, {trade_key: timestamp})
            self.redis.expire(trades_key, 300)  # 10분 후 만료
            
            # 5분 이전 데이터 정리
            five_mins_ago = timestamp - 300  # 5분
            self.redis.zremrangebyscore(trades_key, 0, five_mins_ago)
            
        except Exception as e:
            logger.error(f"체결 데이터 저장 오류 ({stock_code}): {str(e)}")
    
    def _cleanup_old_trades(self, stock_code: str, current_time: int) -> None:
        """
        오래된 체결 데이터 정리
        
        Args:
            stock_code: 종목코드
            current_time: 현재 시간 (UNIX timestamp)
        """
        try:
            # 1분 전 시간
            one_min_ago = current_time - 60
            
            # 5분 전 시간
            five_mins_ago = current_time - 300
            
            # 체결 이력 조회
            trades_key = f"trades:{stock_code}"
            
            # 1분 이전 데이터 조회 (1분 체결강도 계산용)
            old_trades_1min = self.redis.zrangebyscore(trades_key, 0, one_min_ago)
            
            # 5분 이전 데이터 조회 (5분 체결강도 계산용)
            old_trades_5min = self.redis.zrangebyscore(trades_key, 0, five_mins_ago)
            
            # 1분 전 데이터에 대한 매수/매도 거래량 감소
            trade_counts_key = f"trade_counts:{stock_code}"
            pipe = self.redis.pipeline()
            
            for trade_key in old_trades_1min:
                trade_data_str = self.redis.get(trade_key)
                if trade_data_str:
                    try:
                        trade_data = json.loads(trade_data_str)
                        volume = trade_data.get("volume", 0)
                        is_buy = trade_data.get("is_buy", False)
                        
                        # 1분 카운트에서 감소
                        if is_buy:
                            pipe.hincrby(trade_counts_key, "buy_volume_1min", -volume)
                        else:
                            pipe.hincrby(trade_counts_key, "sell_volume_1min", -volume)
                    except:
                        pass
            
            # 5분 전 데이터에 대한 매수/매도 거래량 감소
            for trade_key in old_trades_5min:
                trade_data_str = self.redis.get(trade_key)
                if trade_data_str:
                    try:
                        trade_data = json.loads(trade_data_str)
                        volume = trade_data.get("volume", 0)
                        is_buy = trade_data.get("is_buy", False)
                        
                        # 5분 카운트에서 감소
                        if is_buy:
                            pipe.hincrby(trade_counts_key, "buy_volume_5min", -volume)
                        else:
                            pipe.hincrby(trade_counts_key, "sell_volume_5min", -volume)
                            
                        # 필요없는 데이터 삭제
                        pipe.delete(trade_key)
                    except:
                        pass
            
            # 5분 이전 데이터는 체결 이력에서 제거
            if old_trades_5min:
                pipe.zremrangebyscore(trades_key, 0, five_mins_ago)
            
            pipe.execute()
            
        except Exception as e:
            logger.error(f"오래된 체결 데이터 정리 오류 ({stock_code}): {str(e)}")
    
    def _calculate_intensity(self, stock_code: str, trade_timestamp: int) -> Dict:
        """
        체결강도 계산 및 저장 - 1분 단위로 PostgreSQL에 저장
        
        Args:
            stock_code: 종목코드
            trade_timestamp: 체결 시간 (UNIX timestamp)
            
        Returns:
            Dict: 체결강도 및 시그널 정보
        """
        try:
            # 현재 분 계산 (체결시간 기준)
            current_minute = int(trade_timestamp / 60) * 60  # 초 단위 제거하여 분 단위로 반올림
            
            # 1분 전, 5분 전 시간 계산
            one_min_ago = trade_timestamp - 60
            five_mins_ago = trade_timestamp - 300
            
            # 체결 이력 조회 (Redis Sorted Set 사용)
            trades_key = f"trades:{stock_code}"
            
            # 1분 동안의 체결 이력 조회
            one_min_trades = self.redis.zrangebyscore(
                trades_key, 
                one_min_ago, 
                trade_timestamp
            )
            
            # 5분 동안의 체결 이력 조회
            five_min_trades = self.redis.zrangebyscore(
                trades_key, 
                five_mins_ago, 
                trade_timestamp
            )
            
            # 1분 동안의 매수/매도 거래량 계산
            buy_volume_1min = 0
            sell_volume_1min = 0
            
            for trade_key in one_min_trades:
                trade_data_str = self.redis.get(trade_key)
                if trade_data_str:
                    try:
                        trade_data = json.loads(trade_data_str)
                        volume = trade_data.get("volume", 0)
                        is_buy = trade_data.get("is_buy", False)
                        
                        if is_buy:
                            buy_volume_1min += volume
                        else:
                            sell_volume_1min += volume
                    except:
                        pass
            
            # 5분 동안의 매수/매도 거래량 계산
            buy_volume_5min = 0
            sell_volume_5min = 0
            
            for trade_key in five_min_trades:
                trade_data_str = self.redis.get(trade_key)
                if trade_data_str:
                    try:
                        trade_data = json.loads(trade_data_str)
                        volume = trade_data.get("volume", 0)
                        is_buy = trade_data.get("is_buy", False)
                        
                        if is_buy:
                            buy_volume_5min += volume
                        else:
                            sell_volume_5min += volume
                    except:
                        pass
            
            # 1분 체결강도 계산
            intensity_1min = 0
            if sell_volume_1min > 0:
                intensity_1min = round((buy_volume_1min / sell_volume_1min) * 100, 2)
            elif buy_volume_1min > 0:
                intensity_1min = 200  # 매도가 없고 매수만 있는 경우 최대값 설정
            
            # 5분 체결강도 계산
            intensity_5min = 0
            if sell_volume_5min > 0:
                intensity_5min = round((buy_volume_5min / sell_volume_5min) * 100, 2)
            elif buy_volume_5min > 0:
                intensity_5min = 200  # 매도가 없고 매수만 있는 경우 최대값 설정
            
            # 체결강도 결과 저장 (매 체결마다 갱신)
            intensity_data = {
                "1min": intensity_1min,
                "5min": intensity_5min,
                "timestamp": trade_timestamp,
                "buy_volume_1min": buy_volume_1min,
                "sell_volume_1min": sell_volume_1min, 
                "buy_volume_5min": buy_volume_5min,
                "sell_volume_5min": sell_volume_5min
            }
            
            # Redis에 최신 체결강도 저장 (실시간 조회용)
            intensity_key = f"strength:{stock_code}"
            self.redis.set(intensity_key, json.dumps(intensity_data))
            self.redis.expire(intensity_key, 600)  # 10분 후 만료
            
            # 1분 단위로 PostgreSQL에 체결강도 저장
            # 같은 분에 대한 데이터는 마지막 값으로 업데이트
            self._save_intensity_to_postgres(
                stock_code=stock_code,
                minute_timestamp=current_minute,
                intensity_1min=intensity_1min,
                intensity_5min=intensity_5min,
                buy_volume_1min=buy_volume_1min,
                sell_volume_1min=sell_volume_1min,
                buy_volume_5min=buy_volume_5min,
                sell_volume_5min=sell_volume_5min
            )
            
            # 매매 시그널 생성
            signal = self._generate_signal(stock_code, intensity_1min, intensity_5min, trade_timestamp)
            
            # 시그널이 생성된 경우 PostgreSQL에 저장
            if signal:
                self._save_signal_to_postgres(stock_code, signal)
            
            # 결과 반환
            return {
                "stock_code": stock_code,
                "intensity_1min": intensity_1min,
                "intensity_5min": intensity_5min,
                "timestamp": trade_timestamp,
                "signal": signal
            }
        except Exception as e:
            logger.error(f"체결강도 계산 오류 ({stock_code}): {str(e)}")
            return {
                "stock_code": stock_code,
                "intensity_1min": 0,
                "intensity_5min": 0,
                "timestamp": trade_timestamp,
                "signal": None,
                "error": str(e)
            }
    
    def _generate_signal(self, stock_code: str, intensity_1min: float, intensity_5min: float, trade_timestamp: int) -> Optional[Dict]:
        # 이전 체결강도 조회
        prev_key = f"prev_strength:{stock_code}"
        prev_data_str = self.redis.get(prev_key)
        prev_data = json.loads(prev_data_str) if prev_data_str else {'1min': 0, '5min': 0}
        
        # 이전 체결강도
        prev_1min = prev_data.get('1min', 0)
        prev_5min = prev_data.get('5min', 0)
        
        # 변화량 계산
        change_1min = intensity_1min - prev_1min
        change_5min = intensity_5min - prev_5min
        
        # 시그널 조건
        signal = None
        signal_strength = 0
        
        # 매매 시그널 조건 (예시)
        # 1. 1분 체결강도가 150% 이상이고, 5분 체결강도가 상승 중이면 매수
        if intensity_1min >= 150 and change_5min > 0:
            signal = "BUY"
            signal_strength = min(100, (intensity_1min - 150) + abs(change_5min) * 5)
        
        # 2. 1분 체결강도가 60% 이하이고, 5분 체결강도가 하락 중이면 매도
        elif intensity_1min <= 60 and change_5min < 0:
            signal = "SELL"
            signal_strength = min(100, (60 - intensity_1min) + abs(change_5min) * 5)
        
        # 3. 1분 체결강도가 급격히 변화하는 경우 (20% 이상) 추세 전환 시그널
        elif abs(change_1min) >= 20:
            signal = "BUY" if change_1min > 0 else "SELL"
            signal_strength = min(100, abs(change_1min) * 3)
        
        # 시그널이 있으면 저장
        if signal:
            signal_data = {
                "stock_code": stock_code,
                "signal": signal,
                "strength": round(signal_strength, 2),
                "intensity_1min": intensity_1min,
                "intensity_5min": intensity_5min,
                "change_1min": round(change_1min, 2),
                "change_5min": round(change_5min, 2),
                "timestamp": trade_timestamp
            }
            
            # 시그널 저장
            signal_key = f"trade_signal:{stock_code}"
            self.redis.set(signal_key, json.dumps(signal_data))
            self.redis.expire(signal_key, 300)  # 5분 유효
            
            # 시그널 히스토리에 추가
            history_key = f"signal_history:{stock_code}"
            self.redis.lpush(history_key, json.dumps(signal_data))
            self.redis.ltrim(history_key, 0, 99)  # 최근 100개만 유지
            self.redis.expire(history_key, 86400)  # 24시간 유효
            
            logger.info(f"매매 시그널 생성: {stock_code} - {signal} (강도: {signal_strength:.2f}%)")
            
            return signal_data
        
        # 현재 체결강도를 이전 체결강도로 저장
        self.redis.set(prev_key, json.dumps({
            '1min': intensity_1min,
            '5min': intensity_5min,
            'timestamp': trade_timestamp
        }))
        self.redis.expire(prev_key, 3600)  # 1시간 유효
        
        return None
    
    def get_trade_intensity(self, stock_code: str) -> Dict:
        """
        체결강도 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            Dict: 체결강도 정보
        """
        try:
            intensity_key = f"strength:{stock_code}"
            data_str = self.redis.get(intensity_key)
            
            if data_str:
                return json.loads(data_str)
            
            return {
                "1min": 0,
                "5min": 0,
                "timestamp": int(time.time())
            }
        except Exception as e:
            logger.error(f"체결강도 조회 오류 ({stock_code}): {str(e)}")
            return {
                "1min": 0,
                "5min": 0,
                "timestamp": int(time.time()),
                "error": str(e)
            }
    
    def get_trade_signal(self, stock_code: str) -> Optional[Dict]:
        """
        최근 매매 시그널 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            Optional[Dict]: 매매 시그널 (없으면 None)
        """
        try:
            signal_key = f"trade_signal:{stock_code}"
            data_str = self.redis.get(signal_key)
            
            if data_str:
                return json.loads(data_str)
            
            return None
        except Exception as e:
            logger.error(f"매매 시그널 조회 오류 ({stock_code}): {str(e)}")
            return None
    
    def get_all_signals(self) -> List[Dict]:
        """
        모든 모니터링 종목의 최근 매매 시그널 조회
        
        Returns:
            List[Dict]: 매매 시그널 목록
        """
        signals = []
        
        for stock_code in self.monitored_stocks:
            signal = self.get_trade_signal(stock_code)
            if signal:
                signals.append(signal)
        
        return signals

    def _save_intensity_to_postgres(self, stock_code: str, minute_timestamp: int, 
                                intensity_1min: float, intensity_5min: float,
                                buy_volume_1min: int, sell_volume_1min: int,
                                buy_volume_5min: int, sell_volume_5min: int) -> bool:
        """
        체결강도 데이터를 PostgreSQL에 저장
        
        Args:
            stock_code: 종목코드
            minute_timestamp: 분 단위 타임스탬프
            intensity_1min: 1분 체결강도
            intensity_5min: 5분 체결강도
            buy_volume_1min: 1분 매수 거래량
            sell_volume_1min: 1분 매도 거래량
            buy_volume_5min: 5분 매수 거래량
            sell_volume_5min: 5분 매도 거래량
        
        Returns:
            bool: 성공 여부
        """
        try:
            from db.postgres import execute_query
            
            # 날짜/시간 변환
            minute_datetime = datetime.fromtimestamp(minute_timestamp)
            date_str = minute_datetime.strftime("%Y-%m-%d")
            time_str = minute_datetime.strftime("%H:%M:00")
            
            # UPSERT 쿼리 (같은 종목, 같은 분에 대한 데이터가 있으면 업데이트)
            query = """
            INSERT INTO stock_trade_intensity
            (stock_code, trade_date, trade_time, intensity_1min, intensity_5min, 
            buy_volume_1min, sell_volume_1min, buy_volume_5min, sell_volume_5min, created_at)
            VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (stock_code, trade_date, trade_time)
            DO UPDATE SET
            intensity_1min = EXCLUDED.intensity_1min,
            intensity_5min = EXCLUDED.intensity_5min,
            buy_volume_1min = EXCLUDED.buy_volume_1min,
            sell_volume_1min = EXCLUDED.sell_volume_1min,
            buy_volume_5min = EXCLUDED.buy_volume_5min,
            sell_volume_5min = EXCLUDED.sell_volume_5min,
            updated_at = NOW()
            """
            
            params = (
                stock_code, date_str, time_str, intensity_1min, intensity_5min,
                buy_volume_1min, sell_volume_1min, buy_volume_5min, sell_volume_5min
            )
            
            # 쿼리 실행 (결과 불필요)
            execute_query(query, params, fetch=False)
            
            return True
        except Exception as e:
            logger.error(f"체결강도 PostgreSQL 저장 오류 ({stock_code}): {str(e)}")
            return False
                
    def _save_signal_to_postgres(self, stock_code: str, signal: Dict) -> bool:
        """
        매매 시그널 데이터를 PostgreSQL에 저장
        
        Args:
            stock_code: 종목코드
            signal: 시그널 데이터
        
        Returns:
            bool: 성공 여부
        """
        try:
            from db.postgres import execute_query
            
            # 타임스탬프에서 날짜/시간 변환
            signal_timestamp = signal.get('timestamp', 0)
            signal_datetime = datetime.fromtimestamp(signal_timestamp)
            date_str = signal_datetime.strftime("%Y-%m-%d")
            time_str = signal_datetime.strftime("%H:%M:%S")
            
            # 쿼리
            query = """
            INSERT INTO stock_trade_signals
            (stock_code, signal_date, signal_time, signal_type, signal_strength, 
            intensity_1min, intensity_5min, change_1min, change_5min, created_at)
            VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            
            params = (
                stock_code, 
                date_str, 
                time_str, 
                signal.get('signal', ''), 
                signal.get('strength', 0),
                signal.get('intensity_1min', 0), 
                signal.get('intensity_5min', 0), 
                signal.get('change_1min', 0), 
                signal.get('change_5min', 0)
            )
            
            # 쿼리 실행 (결과 불필요)
            execute_query(query, params, fetch=False)
            
            return True
        except Exception as e:
            logger.error(f"매매 시그널 PostgreSQL 저장 오류 ({stock_code}): {str(e)}")
            return False

