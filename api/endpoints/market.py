import logging
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from core.kiwoom_client import KiwoomClient
from models.stock import StockInfo
from dependencies import get_kiwoom_client
from utils.transformers import transform_numeric_data

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stocks/{code}", response_model=StockInfo,
            summary="계좌 기본 정보 조회",
            description="현재 로그인된 사용자의 계좌 기본 정보를 반환합니다.")


async def get_stock_info(code: str, kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)):
    """주식 기본 정보 조회"""
    try:
        response = await kiwoom_client.get_stock_info(code)
        
        # 디버깅을 위한 전체 응답 로깅
        logger.debug(f"API 응답: {json.dumps(response, indent=2)}")
        
        # 응답이 바로 필요한 데이터를 포함하는 구조라면
        # 가이드에 나온 구조에 맞게 처리
        
        # 시장 구분 (API 응답에 직접적인 시장 정보가 없어 보임)
        # 종목코드 앞자리로 추정 가능 (일반적으로 0으로 시작하면 코스피, 1로 시작하면 코스닥)
        if code.startswith('0'):
            market = "KOSPI"
        elif code.startswith('1'):
            market = "KOSDAQ"
        else:
            market = "KOSPI"  # 기본값
        
        # 문자열을 숫자로 변환할 때 안전하게 처리
        def safe_float(value, default=0.0):
            try:
                # +, - 기호 제거 및 콤마 제거
                cleaned = str(value).replace('+', '').replace('-', '').replace(',', '')
                return float(cleaned) if cleaned else default
            except (ValueError, TypeError):
                return default
                
        def safe_int(value, default=0):
            try:
                cleaned = str(value).replace(',', '')
                return int(cleaned) if cleaned else default
            except (ValueError, TypeError):
                return default
        
        return StockInfo(
            code=code,
            name=response.get("stk_nm", "알 수 없음"),
            market=market,
            price=safe_float(response.get("cur_prc", 0)),
            change=safe_float(response.get("pred_pre", 0)),
            change_ratio=safe_float(response.get("flu_rt", 0)),
            volume=safe_int(response.get("trde_qty", 0))
        )
    except Exception as e:
        logger.error(f"주식 정보 조회 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chart/tick/{code}")
async def get_tick_chart(
    code: str, 
    tick_scope: str = Query("1", description="틱범위 - 1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱"),
    price_type: str = Query("1", description="종가시세구분 - 1:최근가, 2:매수가, 3:매도가"),
    cont_yn: str = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: str = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 틱차트 조회 (ka10079)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_tick_chart(
            code=code,
            tick_scope=tick_scope,
            price_type=price_type,
            cont_yn=cont_yn,
            next_key=next_key
        )
        response = transform_numeric_data(response)
        
        return response
    except Exception as e:
        logger.error(f"틱차트 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 분봉차트 엔드포인트
@router.get("/chart/minute/{code}")
async def get_minute_chart(
    code: str, 
    tic_scope: str = Query("1", description="분단위 - 1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 60:60분"),
    price_type: str = Query("1", description="종가시세구분 - 1:최근가, 2:매수가, 3:매도가"),
    cont_yn: str = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: str = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 분봉차트 조회 (ka10080)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_minute_chart(
            code=code,
            tic_scope=tic_scope,
            price_type=price_type,
            cont_yn=cont_yn,
            next_key=next_key
        )
        response = transform_numeric_data(response)

        return response
        
    except Exception as e:
        logger.error(f"분봉차트 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 일봉차트 엔드포인트
@router.get("/chart/daily/{code}")
async def get_daily_chart(
    code: str, 
    base_dt: str = Query("20250421", description="기준날짜"),
    price_type: str = Query("1", description="종가시세구분 - 1:최근가, 2:매수가, 3:매도가"),
    cont_yn: str = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: str = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 일봉차트 조회 (ka10081)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_daily_chart(
            code=code,
            base_dt=base_dt,
            price_type=price_type,
            cont_yn=cont_yn,
            next_key=next_key
        )
        response = transform_numeric_data(response)
        return response
    except Exception as e:
        logger.error(f"일봉차트 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 주봉차트 엔드포인트
@router.get("/chart/weekly/{code}")
async def get_weekly_chart(
    code: str, 
    base_dt: str = Query("20250421", description="기준날짜"),
    price_type: str = Query("1", description="종가시세구분 - 1:최근가, 2:매수가, 3:매도가"),
    cont_yn: str = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: str = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 주봉차트 조회 (ka10082)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_weekly_chart(
            code=code,
            base_dt=base_dt,
            price_type=price_type,
            cont_yn=cont_yn,
            next_key=next_key
        )
        response = transform_numeric_data(response)
        return response
    except Exception as e:
        logger.error(f"주봉차트 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 월봉차트 엔드포인트
@router.get("/chart/monthly/{code}")
async def get_monthly_chart(
    code: str, 
    base_dt: str = Query("20250421", description="기준날짜"),
    price_type: str = Query("1", description="종가시세구분 - 1:최근가, 2:매수가, 3:매도가"),
    cont_yn: str = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: str = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 월봉차트 조회 (ka10083)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_monthly_chart(
            code=code,
            base_dt=base_dt,
            price_type=price_type,
            cont_yn=cont_yn,
            next_key=next_key
        )
        response = transform_numeric_data(response)

        return response
    except Exception as e:
        logger.error(f"월봉차트 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 년봉차트 엔드포인트
@router.get("/chart/yearly/{code}")
async def get_yearly_chart(
    code: str,
    base_dt: str = Query("20250421", description="기준날짜"),
    price_type: str = Query("1", description="종가시세구분 - 1:최근가, 2:매수가, 3:매도가"),
    cont_yn: str = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: str = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 년봉차트 조회 (ka10084)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_yearly_chart(
            code=code,
            base_dt=base_dt,
            price_type=price_type,
            cont_yn=cont_yn,
            next_key=next_key
        )
        response = transform_numeric_data(response)
        return response
    except Exception as e:
        logger.error(f"년봉차트 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/theme/group")
async def get_theme_group(
    qry_tp: str = Query("0", description="검색구분: 0-전체, 1-테마, 2-종목"),
    stk_cd: str = Query("", description="종목코드 (선택)"),
    date_tp: str = Query("10", description="날짜구분: 1~99 (n일 전)"),
    thema_nm: str = Query("", description="테마명 (선택)"),
    flu_pl_amt_tp: str = Query("1", description="등락수익구분: 1~4"),
    stex_tp: str = Query("1", description="거래소구분: 1-KRX, 2-NXT, 3-통합"),
    cont_yn: str = Query("N", description="연속조회 여부: Y/N"),
    next_key: str = Query("", description="연속조회 키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """테마그룹별 종목 조회 (ka90001)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_theme_group(
            qry_tp=qry_tp,
            stk_cd=stk_cd,
            date_tp=date_tp,
            thema_nm=thema_nm,
            flu_pl_amt_tp=flu_pl_amt_tp,
            stex_tp=stex_tp,
            cont_yn=cont_yn,
            next_key=next_key
        )
        return response
    except Exception as e:
        logger.error(f"테마그룹 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/theme/components")
async def get_theme_components_endpoint(
    date_tp: str = Query("2", description="날짜구분 (1~99일)"),
    thema_grp_cd: str = Query(..., description="테마 그룹 코드 (필수)"),
    stex_tp: str = Query("1", description="거래소 구분: 1-KRX, 2-NXT, 3-통합"),
    cont_yn: str = Query("N", description="연속조회 여부 (Y/N)"),
    next_key: str = Query("", description="연속조회 키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """테마구성종목 조회 (ka90002)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")

        response = await kiwoom_client.get_theme_components(
            date_tp=date_tp,
            thema_grp_cd=thema_grp_cd,
            stex_tp=stex_tp,
            cont_yn=cont_yn,
            next_key=next_key
        )
        return response
    except Exception as e:
        logger.error(f"테마구성종목 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sector/prices")
async def get_sector_prices_endpoint(
    mrkt_tp: str = Query("0", description="시장 구분: 0-코스피, 1-코스닥, 2-코스피200"),
    inds_cd: str = Query("001", description="업종 코드 (예: 001-종합(KOSPI), 002-대형주 등)"),
    stex_tp: str = Query("1", description="거래소 구분: 1-KRX, 2-NXT, 3-통합"),
    cont_yn: str = Query("N", description="연속조회 여부 (Y/N)"),
    next_key: str = Query("", description="연속조회 키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """업종별 주가 조회 (ka20002)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")

        response = await kiwoom_client.get_sector_prices(
            mrkt_tp=mrkt_tp,
            inds_cd=inds_cd,
            stex_tp=stex_tp,
            cont_yn=cont_yn,
            next_key=next_key
        )

        return response
    except Exception as e:
        logger.error(f"업종별주가 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector/index/all")
async def get_all_sector_index_endpoint(
    inds_cd: str = Query("001", description="업종 코드 (예: 001-종합(KOSPI), 002-대형주 등)"),
    cont_yn: str = Query("N", description="연속조회 여부 (Y/N)"),
    next_key: str = Query("", description="연속조회 키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """전업종지수 조회 (ka20003)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")

        response = await kiwoom_client.get_all_sector_index(
            inds_cd=inds_cd,
            cont_yn=cont_yn,
            next_key=next_key
        )
        return response
    except Exception as e:
        logger.error(f"전업종지수 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector/daily-price")
async def get_sector_daily_price_endpoint(
    mrkt_tp: str = Query("0", description="시장구분 (0:코스피, 1:코스닥, 2:코스피200)"),
    inds_cd: str = Query("001", description="업종코드 (예: 001-종합(KOSPI))"),
    cont_yn: str = Query("N", description="연속조회 여부"),
    next_key: str = Query("", description="연속조회 키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """업종 현재가 일별 조회 (ka20009)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")

        response = await kiwoom_client.get_sector_daily_price(
            mrkt_tp=mrkt_tp,
            inds_cd=inds_cd,
            cont_yn=cont_yn,
            next_key=next_key
        )

        return response
    except Exception as e:
        logger.error(f"업종현재가일별 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


