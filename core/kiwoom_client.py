import asyncio
import logging
from typing import List
from datetime import datetime
import requests
from fastapi import  Depends
from config import settings
from dependency_injector.wiring import inject, Provide
from container.token_di import TokenContainer
from core.token_client import TokenGenerator

REAL_HOST = 'https://api.kiwoom.com'
MOCK_HOST = 'https://mockapi.kiwoom.com'

logger = logging.getLogger(__name__)

class KiwoomClient() : 
    """키움 API와 통신하는 클라이언트"""
    @inject
    def __init__(self,real=False, 
                token_generator: TokenGenerator = Depends(Provide[TokenContainer.token_generator])):
        # 실전투자, 모의투자 선택
        self.host = REAL_HOST if real else MOCK_HOST
        self.app_key = settings.KIWOOM_APP_KEY
        self.sec_key = settings.KIWOOM_SECRET_KEY
        self.token = token_generator.get_token()
        self.logger = logging.getLogger(__name__)
        
        # 주식 기본 정보 조회 (REST API 예시)
    async def get_stock_info(self, code: str) -> dict:
        """주식 기본 정보 조회"""
        url = f"{self.host}/api/dostk/stkinfo"  # 올바른 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": "N",  # 연속조회여부
            "next-key": "",  # 연속조회키
            "api-id": "ka10001"  # TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code
        }
        
        try:
            loop = asyncio.get_event_loop()
            # GET 대신 POST 사용, params 대신 json 사용
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"응답 내용: {response.text}")
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"주식 정보 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
    
    async def get_tick_chart(self, code: str, tick_scope: str = "1", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 틱차트 조회 (ka10079)
        
        Args:
            code (str): 종목 코드
            tick_scope (str): 틱범위 - 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 틱차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 틱차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10079"  # 틱챠트조회 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "tic_scope": tick_scope,
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"틱차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"틱차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"틱차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_minute_chart(self, code: str, tic_scope: str = "1", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 분봉차트 조회 (ka10080)
        
        Args:
            code (str): 종목 코드
            minute_unit (str): 분단위 - 1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 60:60분
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 분봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 분봉차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10080"  # 분봉챠트조회 TR명
        }
        print("분봉차트 조회 url",url)
        print(self.token)
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "tic_scope": tic_scope,
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"분봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"분봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"분봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_daily_chart(self, code: str, base_dt: str = "", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 일봉차트 조회 (ka10081)
        
        Args:
            code (str): 종목 코드
            period_value (str): 기간 - 1:일봉(default)
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 일봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 일봉차트 조회 엔드포인트
        
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10081"  # 일봉챠트조회 TR명
        }
        
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if base_dt == ''  : 
            base_dt = current_date.strftime("%Y%m%d")
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "base_dt": base_dt,  # 20250421
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"일봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"일봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"일봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_weekly_chart(self, code: str,base_dt: str = "", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 주봉차트 조회 (ka10082)
        
        Args:
            code (str): 종목 코드
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 주봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 주봉차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10082"  # 주봉챠트조회 TR명
        }
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if base_dt == ''  : 
            base_dt = current_date.strftime("%Y%m%d")
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "base_dt": base_dt,  # 20250421
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"주봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_monthly_chart(self, code: str,base_dt: str = "", price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 월봉차트 조회 (ka10083)
        
        Args:
            code (str): 종목 코드
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 월봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 월봉차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10083"  # 월봉챠트조회 TR명
        }
        
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if base_dt == ''  : 
            base_dt = current_date.strftime("%Y%m%d")
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "base_dt": base_dt,  # 20250421
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"월봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"월봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"월봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_yearly_chart(self, code: str, base_dt: str = "",price_type: str = "1", cont_yn: str = "N", next_key: str = "") -> dict:
        """
        주식 년봉차트 조회 (ka10094)
        
        Args:
            code (str): 종목 코드
            price_type (str): 종가시세구분 - 1:최근가(default), 2:매수가, 3:매도가
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 조회한 응답값(output)의 next_key를 요청값(input)에 지정
        
        Returns:
            dict: 년봉차트 데이터
        """
        url = f"{self.host}/api/dostk/chart"  # 년봉차트 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10094"  # 년봉챠트조회 TR명
        }
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if base_dt == ''  : 
            base_dt = current_date.strftime("%Y%m%d")
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": code,
            "base_dt": base_dt,  # 20250421
            "upd_stkpc_tp": price_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"년봉차트 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"년봉차트 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"년봉차트 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise    

    async def get_deposit_detail(self, 
                                query_type: str = "2", 
                                cont_yn: str = "N",
                                next_key: str = "") -> dict:
        """
        예수금상세현황요청 (kt00001)
        
        Args:
            account_no (str): 계좌번호
            query_type (str): 조회구분 (3:추정조회, 2:일반조회)
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회(default)
            next_key (str): 연속조회키 - 연속조회시 이전 응답의 next-key값
            
        Returns:
            dict: 예수금 상세현황 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "kt00001"  # 예수금상세현황요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "qry_tp": query_type,
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"예수금상세현황 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"예수금상세현황 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"예수금상세현황 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_order_detail(self, 
                                order_date: str,
                                query_type: str = "1", 
                                stock_bond_type: str = "1", 
                                sell_buy_type: str = "0", 
                                stock_code: str = "", 
                                from_order_no: str = "", 
                                market_type: str = "KRX",
                                cont_yn: str = "N", 
                                next_key: str = "") -> dict:
        """
        계좌별주문체결내역상세요청 (kt00007)
        
        Args:
            order_date (str): 주문일자 (YYYYMMDD)
            query_type (str): 조회구분 - 1:주문순, 2:역순, 3:미체결, 4:체결내역만
            stock_bond_type (str): 주식채권구분 - 0:전체, 1:주식, 2:채권
            sell_buy_type (str): 매도수구분 - 0:전체, 1:매도, 2:매수
            stock_code (str): 종목코드 (공백허용, 공백일때 전체종목)
            from_order_no (str): 시작주문번호 (공백허용, 공백일때 전체주문)
            market_type (str): 국내거래소구분 - %:(전체), KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문체결내역 상세 데이터
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "kt00007"  # 계좌별주문체결내역상세요청 TR명
        }
        # YYYYMMDD 형식으로 포맷팅
        current_date = datetime.now()
        if order_date == ''  : 
            order_date = current_date.strftime("%Y%m%d")
        
        # JSON 형식으로 전달할 데이터
        data = {
            "ord_dt": order_date,
            "qry_tp": query_type,
            "stk_bond_tp": stock_bond_type,
            "sell_tp": sell_buy_type,
            "stk_cd": stock_code,
            "fr_ord_no": from_order_no,
            "dmst_stex_tp": market_type
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주문체결내역 상세 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주문체결내역 상세 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"주문체결내역 상세 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
    async def get_daily_trading_log(self, 
                                base_date: str = "", 
                                ottks_tp: str = "1", 
                                ch_crd_tp : str = "0",
                                cont_yn: str = "N", 
                                next_key: str = "") -> dict:
        """
        당일매매일지요청 (ka10170)
        
        Args:
            base_date (str): 기준일자 (YYYYMMDD) - 공백일 경우 당일
            ottks_tp (str): 단주구분 - 1:당일매수에 대한 당일매도, 2:당일매도 전체
            ch_crd_tp(str) : 0:전체, 1:현금매매만, 2:신용매매만
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 당일 매매일지 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10170"  # 당일매매일지요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "base_dt": base_date,
            "ottks_tp": ottks_tp,
            "ch_crd_tp": ch_crd_tp
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"당일매매일지 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"당일매매일지 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"당일매매일지 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise       
        
    async def get_outstanding_orders(self, 
                                all_stk_tp: str = "0", 
                                trde_tp: str = "0", 
                                stk_cd: str = "", 
                                stex_tp: str = "0",
                                cont_yn: str = "N", 
                                next_key: str = "") -> dict:
        """
        미체결요청 (ka10075)
        
        Args:
            all_stk_tp (str): 전체종목구분 - 0:전체, 1:종목
            trde_tp (str): 매매구분 - 0:전체, 1:매도, 2:매수
            stk_cd (str): 종목코드 (all_stk_tp가 1일 경우 필수)
            stex_tp (str): 거래소구분 - 0:통합, 1:KRX, 2:NXT
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 미체결 주문 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10075"  # 미체결요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터 - stk_cd를 항상 포함
        data = {
            "all_stk_tp": all_stk_tp,
            "trde_tp": trde_tp,
            "stk_cd": stk_cd,
            "stex_tp": stex_tp
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"미체결 주문 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"미체결 주문 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"미체결 주문 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
    
    async def get_executed_orders(self, 
                                stk_cd: str = "", 
                                qry_tp: str = "0", 
                                sell_tp: str = "0", 
                                ord_no: str = "", 
                                stex_tp: str = "0",
                                cont_yn: str = "N", 
                                next_key: str = "") -> dict:
        """
        체결요청 (ka10076)
        
        Args:
            stk_cd (str): 종목코드
            qry_tp (str): 조회구분 - 0:전체, 1:종목
            sell_tp (str): 매도수구분 - 0:전체, 1:매도, 2:매수
            ord_no (str): 주문번호 (입력한 주문번호보다 과거에 체결된 내역 조회)
            stex_tp (str): 거래소구분 - 0:통합, 1:KRX, 2:NXT
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 체결 주문 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10076"  # 체결요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": stk_cd,
            "qry_tp": qry_tp,
            "sell_tp": sell_tp,
            "ord_no": ord_no,
            "stex_tp": stex_tp
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"체결 주문 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"체결 주문 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"체결 주문 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
    async def get_daily_item_realized_profit(self, 
                                        stk_cd: str, 
                                        strt_dt: str,
                                        cont_yn: str = "N", 
                                        next_key: str = "") -> dict:
        """
        일자별종목별실현손익요청_일자 (ka10072)
        
        Args:
            stk_cd (str): 종목코드
            strt_dt (str): 시작일자 (YYYYMMDD)
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 일자별 종목별 실현손익 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10072"  # 일자별종목별실현손익요청_일자 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "stk_cd": stk_cd,
            "strt_dt": strt_dt
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"일자별종목별실현손익 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"일자별종목별실현손익 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"일자별종목별실현손익 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise    
        
    async def get_daily_realized_profit(self, 
                                    strt_dt: str, 
                                    end_dt: str,
                                    cont_yn: str = "N", 
                                    next_key: str = "") -> dict:
        """
        일자별실현손익요청 (ka10074)
        
        Args:
            strt_dt (str): 시작일자 (YYYYMMDD)
            end_dt (str): 종료일자 (YYYYMMDD)
            cont_yn (str): 연속조회여부 - Y:연속조회, N:일반조회
            next_key (str): 연속조회키
            
        Returns:
            dict: 일자별 실현손익 정보
        """
        url = f"{self.host}/api/dostk/acnt"  # 계좌 조회 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka10074"  # 일자별실현손익요청 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "strt_dt": strt_dt,
            "end_dt": end_dt
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"일자별 실현손익 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"일자별 실현손익 조회 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            
            # 연속조회 여부 및 다음 키 처리
            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')
            
            return result
        except Exception as e:
            logger.error(f"일자별 실현손익 조회 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
    async def order_stock_buy(self, 
                            dmst_stex_tp: str, 
                            stk_cd: str, 
                            ord_qty: str, 
                            ord_uv: str = "", 
                            trde_tp: str = "0", 
                            cond_uv: str = "",
                            cont_yn: str = "N",
                            next_key: str = "") -> dict:
        """
        주식 매수주문 (kt10000)
        
        Args:
            dmst_stex_tp (str): 국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            stk_cd (str): 종목코드
            ord_qty (str): 주문수량
            ord_uv (str): 주문단가 (시장가 주문 시 비워둠)
            trde_tp (str): 매매구분 - 0:보통, 3:시장가, 5:조건부지정가, 6:최유리지정가, 7:최우선지정가 등
            cond_uv (str): 조건단가 (조건부 주문 시 사용)
            cont_yn (str): 연속조회여부
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문 결과 정보
        """
        url = f"{self.host}/api/dostk/ordr"  # 주문 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn, 
            "next-key": next_key,
            "api-id": "kt10000"  # 주식 매수주문 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "dmst_stex_tp": dmst_stex_tp,
            "stk_cd": stk_cd,
            "ord_qty": ord_qty,
            "ord_uv": ord_uv,
            "trde_tp": trde_tp,
            "cond_uv": cond_uv
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주식 매수주문 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주식 매수주문 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            logger.info(f"주식 매수주문 성공: {stk_cd}, {ord_qty}주, 주문번호: {result.get('ord_no', '알 수 없음')}")
            
            return result
        except Exception as e:
            logger.error(f"주식 매수주문 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def order_stock_sell(self, 
                            dmst_stex_tp: str, 
                            stk_cd: str, 
                            ord_qty: str, 
                            ord_uv: str = "", 
                            trde_tp: str = "0", 
                            cond_uv: str = "",
                            cont_yn: str = "N",
                            next_key: str = "") -> dict:
        """
        주식 매도주문 (kt10001)
        
        Args:
            dmst_stex_tp (str): 국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            stk_cd (str): 종목코드
            ord_qty (str): 주문수량
            ord_uv (str): 주문단가 (시장가 주문 시 비워둠)
            trde_tp (str): 매매구분 - 0:보통, 3:시장가, 5:조건부지정가, 6:최유리지정가, 7:최우선지정가 등
            cond_uv (str): 조건단가 (조건부 주문 시 사용)
            cont_yn (str): 연속조회여부
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문 결과 정보
        """
        url = f"{self.host}/api/dostk/ordr"  # 주문 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn, 
            "next-key": next_key,
            "api-id": "kt10001"  # 주식 매도주문 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "dmst_stex_tp": dmst_stex_tp,
            "stk_cd": stk_cd,
            "ord_qty": ord_qty,
            "ord_uv": ord_uv,
            "trde_tp": trde_tp,
            "cond_uv": cond_uv
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주식 매도주문 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주식 매도주문 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            logger.info(f"주식 매도주문 성공: {stk_cd}, {ord_qty}주, 주문번호: {result.get('ord_no', '알 수 없음')}")
            
            return result
        except Exception as e:
            logger.error(f"주식 매도주문 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise


    async def order_stock_modify(self, 
                            dmst_stex_tp: str, 
                            orig_ord_no: str, 
                            stk_cd: str, 
                            mdfy_qty: str, 
                            mdfy_uv: str, 
                            mdfy_cond_uv: str = "",
                            cont_yn: str = "N",
                            next_key: str = "") -> dict:
        """
        주식 정정주문 (kt10002)
        
        Args:
            dmst_stex_tp (str): 국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            orig_ord_no (str): 원주문번호
            stk_cd (str): 종목코드
            mdfy_qty (str): 정정수량
            mdfy_uv (str): 정정단가
            mdfy_cond_uv (str): 정정조건단가
            cont_yn (str): 연속조회여부
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문 결과 정보
        """
        url = f"{self.host}/api/dostk/ordr"  # 주문 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn, 
            "next-key": next_key,
            "api-id": "kt10002"  # 주식 정정주문 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "dmst_stex_tp": dmst_stex_tp,
            "orig_ord_no": orig_ord_no,
            "stk_cd": stk_cd,
            "mdfy_qty": mdfy_qty,
            "mdfy_uv": mdfy_uv,
            "mdfy_cond_uv": mdfy_cond_uv
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주식 정정주문 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주식 정정주문 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            logger.info(f"주식 정정주문 성공: {stk_cd}, 원주문번호: {orig_ord_no}, 정정수량: {mdfy_qty}, 정정단가: {mdfy_uv}")
            
            return result
        except Exception as e:
            logger.error(f"주식 정정주문 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise
        
    async def order_stock_cancel(self, 
                            dmst_stex_tp: str, 
                            orig_ord_no: str, 
                            stk_cd: str, 
                            cncl_qty: str,
                            cont_yn: str = "N",
                            next_key: str = "") -> dict:
        """
        주식 취소주문 (kt10003)
        
        Args:
            dmst_stex_tp (str): 국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행
            orig_ord_no (str): 원주문번호
            stk_cd (str): 종목코드
            cncl_qty (str): 취소수량 ('0' 입력시 잔량 전부 취소)
            cont_yn (str): 연속조회여부
            next_key (str): 연속조회키
            
        Returns:
            dict: 주문 결과 정보
        """
        url = f"{self.host}/api/dostk/ordr"  # 주문 엔드포인트
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn, 
            "next-key": next_key,
            "api-id": "kt10003"  # 주식 취소주문 TR명
        }
        
        # JSON 형식으로 전달할 데이터
        data = {
            "dmst_stex_tp": dmst_stex_tp,
            "orig_ord_no": orig_ord_no,
            "stk_cd": stk_cd,
            "cncl_qty": cncl_qty
        }
        
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=data)
            )
            
            # 응답 로깅
            logger.debug(f"주식 취소주문 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"주식 취소주문 응답 내용: {response.text}")
            
            response.raise_for_status()
            
            # 응답 데이터
            result = response.json()
            logger.info(f"주식 취소주문 성공: {stk_cd}, 원주문번호: {orig_ord_no}, 취소수량: {cncl_qty}")
            
            return result
        except Exception as e:
            logger.error(f"주식 취소주문 오류: {str(e)}")
            # 응답 내용 확인 시도
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise        
            
    async def get_theme_group(self,
                                qry_tp: str = "0",
                                stk_cd: str = "",
                                date_tp: str = "10",
                                thema_nm: str = "",
                                flu_pl_amt_tp: str = "1",
                                stex_tp: str = "1",
                                cont_yn: str = "N", next_key: str = "") -> dict:
        """
        테마그룹별 종목조회 (ka90001)

        Args:
            qry_tp (str): 검색구분 (0:전체, 1:테마, 2:종목)
            stk_cd (str): 종목코드
            date_tp (str): 날짜구분 (1~99일)
            thema_nm (str): 테마명
            flu_pl_amt_tp (str): 수익률 구분 (1~4)
            stex_tp (str): 거래소 구분 (1:KRX, 2:NXT, 3:통합)
            cont_yn (str): 연속조회 여부
            next_key (str): 연속조회 키

        Returns:
            dict: 테마그룹 조회 결과
        """
        url = f"{self.host}/api/dostk/thme"

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka90001"
        }

        data = {
            "qry_tp": qry_tp,
            "stk_cd": stk_cd,
            "date_tp": date_tp,
            "thema_nm": thema_nm,
            "flu_pl_amt_tp": flu_pl_amt_tp,
            "stex_tp": stex_tp
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"테마그룹 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"테마그룹 조회 응답 내용: {response.text}")
            response.raise_for_status()

            result = response.json()
            headers_dict = dict(response.headers)
            result["has_next"] = headers_dict.get("has-next", "N") == "Y"
            result["next_key"] = headers_dict.get("next-key", "")
            return result

        except Exception as e:
            logger.error(f"테마그룹 조회 오류: {str(e)}")
            try:
                if hasattr(e, "response") and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_theme_components(
        self, 
        date_tp: str = "2", 
        thema_grp_cd: str = "100", 
        stex_tp: str = "1",
        cont_yn: str = "N", 
        next_key: str = ""
    ) -> dict:
        """
        테마구성종목 조회 (ka90002)

        Args:
            date_tp (str): 날짜구분 (1~99일)
            thema_grp_cd (str): 테마 그룹 코드
            stex_tp (str): 거래소구분 1:KRX, 2:NXT, 3:통합
            cont_yn (str): 연속조회 여부 (Y/N)
            next_key (str): 연속조회 키

        Returns:
            dict: 테마구성종목 데이터
        """
        url = f"{self.host}/api/dostk/thme"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka90002"
        }

        data = {
            "date_tp": date_tp,
            "thema_grp_cd": thema_grp_cd,
            "stex_tp": stex_tp
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"테마구성종목 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"테마구성종목 조회 응답 내용: {response.text}")

            response.raise_for_status()
            result = response.json()

            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')

            return result
        except Exception as e:
            logger.error(f"테마구성종목 조회 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_sector_prices(self,
                                mrkt_tp: str = "0",
                                inds_cd: str = "001",
                                stex_tp: str = "1",
                                cont_yn: str = "N",
                                next_key: str = ""
                            ) -> dict:
        """
        업종별 주가 조회 (ka20002)

        Args:
            mrkt_tp (str): 시장 구분 (0:코스피, 1:코스닥, 2:코스피200)
            inds_cd (str): 업종 코드 (001:KOSPI 종합 등)
            stex_tp (str): 거래소 구분 (1:KRX, 2:NXT, 3:통합)
            cont_yn (str): 연속조회 여부 (Y/N)
            next_key (str): 연속조회 키

        Returns:
            dict: 업종별 주가 데이터
        """
        url = f"{self.host}/api/dostk/sect"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka20002"
        }

        data = {
            "mrkt_tp": mrkt_tp,
            "inds_cd": inds_cd,
            "stex_tp": stex_tp
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"업종별주가 조회 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"업종별주가 조회 응답 내용: {response.text}")

            response.raise_for_status()
            result = response.json()

            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')

            return result
        except Exception as e:
            logger.error(f"업종별주가 조회 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_all_sector_index(
        self,
        inds_cd: str = "001",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> dict:
        """
        전업종지수 요청 (ka20003)

        Args:
            inds_cd (str): 업종코드 (예: 001:종합(KOSPI), 002:대형주 등)
            cont_yn (str): 연속조회 여부
            next_key (str): 연속조회 키

        Returns:
            dict: 전업종지수 데이터
        """
        url = f"{self.host}/api/dostk/sect"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka20003"
        }

        data = {
            "inds_cd": inds_cd
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"전업종지수 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"전업종지수 응답 내용: {response.text}")

            response.raise_for_status()
            result = response.json()

            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')

            return result
        except Exception as e:
            logger.error(f"전업종지수 조회 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise

    async def get_sector_daily_price(
        self,
        mrkt_tp: str = "0",
        inds_cd: str = "001",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> dict:
        """
        업종현재가일별요청 (ka20009)

        Args:
            mrkt_tp (str): 시장구분 (0:코스피, 1:코스닥, 2:코스피200)
            inds_cd (str): 업종코드 (001:종합(KOSPI) 등)
            cont_yn (str): 연속조회 여부
            next_key (str): 연속조회 키

        Returns:
            dict: 업종 현재가 일별 데이터
        """
        url = f"{self.host}/api/dostk/sect"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": "ka20009"
        }

        data = {
            "mrkt_tp": mrkt_tp,
            "inds_cd": inds_cd
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, json=data)
            )

            logger.debug(f"업종현재가일별 응답 코드: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"업종현재가일별 응답 내용: {response.text}")

            response.raise_for_status()
            result = response.json()

            headers_dict = dict(response.headers)
            result['has_next'] = headers_dict.get('has-next', 'N') == 'Y'
            result['next_key'] = headers_dict.get('next-key', '')

            return result
        except Exception as e:
            logger.error(f"업종현재가일별 요청 오류: {str(e)}")
            try:
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"에러 응답 내용: {e.response.text}")
            except:
                pass
            raise



