import asyncio
import logging
from datetime import datetime
import requests


logger = logging.getLogger(__name__)

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