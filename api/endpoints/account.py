import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.kiwoom_client import KiwoomClient
from dependencies import get_kiwoom_client

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/")
async def get_account_info():
    return {"message": "Account info"}

@router.get("/deposit-detail")
async def get_deposit_detail(
    query_type: str = Query("2", description="조회구분 (3:추정조회, 2:일반조회)"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """예수금상세현황요청 (kt00001)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_deposit_detail(
            query_type=query_type,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"예수금상세현황 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/order-detail")
async def get_order_detail(
    order_date: str = Query(..., description="주문일자 (YYYYMMDD)"),
    query_type: str = Query("1", description="조회구분 - 1:주문순, 2:역순, 3:미체결, 4:체결내역만"),
    stock_bond_type: str = Query("1", description="주식채권구분 - 0:전체, 1:주식, 2:채권"),
    sell_buy_type: str = Query("0", description="매도수구분 - 0:전체, 1:매도, 2:매수"),
    stock_code: Optional[str] = Query("", description="종목코드 (공백허용, 공백일때 전체종목)"),
    from_order_no: Optional[str] = Query("", description="시작주문번호 (공백허용, 공백일때 전체주문)"),
    market_type: str = Query("KRX", description="국내거래소구분 - %:(전체), KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """계좌별주문체결내역상세요청 (kt00007)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_order_detail(
            order_date=order_date,
            query_type=query_type,
            stock_bond_type=stock_bond_type,
            sell_buy_type=sell_buy_type,
            stock_code=stock_code,
            from_order_no=from_order_no,
            market_type=market_type,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"주문체결내역 상세 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/daily-trading-log")
async def get_daily_trading_log(
    base_date: Optional[str] = Query("", description="기준일자 (YYYYMMDD) - 공백일 경우 당일"),
    ottks_tp: str = Query("1", description="단주구분 - 1:당일매수에 대한 당일매도, 2:당일매도 전체"),
    ch_crd_tp: str = Query("0", description="현금신용구분 - 0:전체, 1:현금매매만, 2:신용매매만"),  # 추가된 매개변수
    cont_yn: Optional[str] = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """당일매매일지요청 (ka10170)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        response = await kiwoom_client.get_daily_trading_log(
            base_date=base_date,
            ottks_tp=ottks_tp,
            ch_crd_tp=ch_crd_tp,  # 추가된 필드
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"당일매매일지 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/outstanding-orders")
async def get_outstanding_orders(
    all_stk_tp: str = Query("0", description="전체종목구분 - 0:전체, 1:종목"),
    trde_tp: str = Query("0", description="매매구분 - 0:전체, 1:매도, 2:매수"),
    stk_cd: Optional[str] = Query("", description="종목코드 (all_stk_tp가 1일 경우 필수)"),
    stex_tp: str = Query("0", description="거래소구분 - 0:통합, 1:KRX, 2:NXT"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """미체결요청 (ka10075)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # all_stk_tp가 1이고 stk_cd가 비어있으면 에러
        if all_stk_tp == "1" and not stk_cd:
            raise HTTPException(status_code=400, detail="종목 지정 시 종목코드(stk_cd)가 필요합니다.")
        
        response = await kiwoom_client.get_outstanding_orders(
            all_stk_tp=all_stk_tp,
            trde_tp=trde_tp,
            stk_cd=stk_cd,
            stex_tp=stex_tp,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"미체결 주문 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/executed-orders")
async def get_executed_orders(
    stk_cd: Optional[str] = Query("", description="종목코드"),
    qry_tp: str = Query("0", description="조회구분 - 0:전체, 1:종목"),
    sell_tp: str = Query("0", description="매도수구분 - 0:전체, 1:매도, 2:매수"),
    ord_no: Optional[str] = Query("", description="주문번호 (입력한 주문번호보다 과거에 체결된 내역 조회)"),
    stex_tp: str = Query("0", description="거래소구분 - 0:통합, 1:KRX, 2:NXT"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """체결요청 (ka10076)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # qry_tp가 1이고 stk_cd가 비어있으면 에러
        if qry_tp == "1" and not stk_cd:
            raise HTTPException(status_code=400, detail="종목 지정 조회(qry_tp=1) 시 종목코드(stk_cd)가 필요합니다.")
        
        response = await kiwoom_client.get_executed_orders(
            stk_cd=stk_cd,
            qry_tp=qry_tp,
            sell_tp=sell_tp,
            ord_no=ord_no,
            stex_tp=stex_tp,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"체결 주문 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/daily-item-profit")
async def get_daily_item_realized_profit(
    stk_cd: str = Query(..., description="종목코드"),
    strt_dt: str = Query(..., description="시작일자 (YYYYMMDD)"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """일자별종목별실현손익요청_일자 (ka10072)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # 날짜 형식 유효성 검사
        if not strt_dt.isdigit() or len(strt_dt) != 8:
            raise HTTPException(status_code=400, detail="시작일자(strt_dt)는 YYYYMMDD 형식이어야 합니다.")
        
        response = await kiwoom_client.get_daily_item_realized_profit(
            stk_cd=stk_cd,
            strt_dt=strt_dt,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"일자별종목별실현손익 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/daily-profit")
async def get_daily_realized_profit(
    strt_dt: str = Query(..., description="시작일자 (YYYYMMDD)"),
    end_dt: str = Query(..., description="종료일자 (YYYYMMDD)"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부 - Y:연속조회, N:일반조회"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """일자별실현손익요청 (ka10074)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # 날짜 형식 유효성 검사
        if not strt_dt.isdigit() or len(strt_dt) != 8:
            raise HTTPException(status_code=400, detail="시작일자(strt_dt)는 YYYYMMDD 형식이어야 합니다.")
        
        if not end_dt.isdigit() or len(end_dt) != 8:
            raise HTTPException(status_code=400, detail="종료일자(end_dt)는 YYYYMMDD 형식이어야 합니다.")
            
        # 날짜 논리성 검사
        if strt_dt > end_dt:
            raise HTTPException(status_code=400, detail="시작일자는 종료일자보다 이전이어야 합니다.")
        
        response = await kiwoom_client.get_daily_realized_profit(
            strt_dt=strt_dt,
            end_dt=end_dt,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"일자별 실현손익 조회 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))