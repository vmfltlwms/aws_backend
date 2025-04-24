import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.kiwoom_client import KiwoomClient
from dependencies import get_kiwoom_client


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
async def get_orders():
    return {"message": "Orders list"}

@router.post("/order/buy")
async def order_stock_buy(
    dmst_stex_tp: str = Query("KRX", description="국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행"),
    stk_cd: str = Query(..., description="종목코드"),
    ord_qty: str = Query(..., description="주문수량"),
    ord_uv: Optional[str] = Query("", description="주문단가 (시장가 주문 시 비워둠)"),
    trde_tp: str = Query("3", description="매매구분 - 0:보통, 3:시장가, 5:조건부지정가, 6:최유리지정가 등"),
    cond_uv: Optional[str] = Query("", description="조건단가 (조건부 주문 시 사용)"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 매수주문 (kt10000)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # 기본 유효성 검사
        if not stk_cd:
            raise HTTPException(status_code=400, detail="종목코드(stk_cd)는 필수 항목입니다.")
            
        if not ord_qty:
            raise HTTPException(status_code=400, detail="주문수량(ord_qty)은 필수 항목입니다.")
            
        # 시장가 주문이 아닌 경우 주문가격 검사
        if trde_tp not in ["3", "13", "23"] and not ord_uv:
            raise HTTPException(status_code=400, detail="지정가 주문시 주문단가(ord_uv)는 필수 항목입니다.")
            
        # 조건부 주문시 조건가격 검사
        if trde_tp == "28" and not cond_uv:  # 스톱지정가
            raise HTTPException(status_code=400, detail="스톱지정가 주문시 조건단가(cond_uv)는 필수 항목입니다.")
        
        response = await kiwoom_client.order_stock_buy(
            dmst_stex_tp=dmst_stex_tp,
            stk_cd=stk_cd,
            ord_qty=ord_qty,
            ord_uv=ord_uv,
            trde_tp=trde_tp,
            cond_uv=cond_uv,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"주식 매수주문 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/order/sell")
async def order_stock_sell(
    dmst_stex_tp: str = Query("KRX", description="국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행"),
    stk_cd: str = Query(..., description="종목코드"),
    ord_qty: str = Query(..., description="주문수량"),
    ord_uv: Optional[str] = Query("", description="주문단가 (시장가 주문 시 비워둠)"),
    trde_tp: str = Query("3", description="매매구분 - 0:보통, 3:시장가, 5:조건부지정가, 6:최유리지정가 등"),
    cond_uv: Optional[str] = Query("", description="조건단가 (조건부 주문 시 사용)"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 매도주문 (kt10001)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # 기본 유효성 검사
        if not stk_cd:
            raise HTTPException(status_code=400, detail="종목코드(stk_cd)는 필수 항목입니다.")
            
        if not ord_qty:
            raise HTTPException(status_code=400, detail="주문수량(ord_qty)은 필수 항목입니다.")
            
        # 시장가 주문이 아닌 경우 주문가격 검사
        if trde_tp not in ["3", "13", "23"] and not ord_uv:
            raise HTTPException(status_code=400, detail="지정가 주문시 주문단가(ord_uv)는 필수 항목입니다.")
            
        # 조건부 주문시 조건가격 검사
        if trde_tp == "28" and not cond_uv:  # 스톱지정가
            raise HTTPException(status_code=400, detail="스톱지정가 주문시 조건단가(cond_uv)는 필수 항목입니다.")
        
        response = await kiwoom_client.order_stock_sell(
            dmst_stex_tp=dmst_stex_tp,
            stk_cd=stk_cd,
            ord_qty=ord_qty,
            ord_uv=ord_uv,
            trde_tp=trde_tp,
            cond_uv=cond_uv,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"주식 매도주문 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/order/modify")
async def order_stock_modify(
    dmst_stex_tp: str = Query("KRX", description="국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행"),
    orig_ord_no: str = Query(..., description="원주문번호"),
    stk_cd: str = Query(..., description="종목코드"),
    mdfy_qty: str = Query(..., description="정정수량"),
    mdfy_uv: str = Query(..., description="정정단가"),
    mdfy_cond_uv: Optional[str] = Query("", description="정정조건단가"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 정정주문 (kt10002)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # 기본 유효성 검사
        if not orig_ord_no:
            raise HTTPException(status_code=400, detail="원주문번호(orig_ord_no)는 필수 항목입니다.")
            
        if not stk_cd:
            raise HTTPException(status_code=400, detail="종목코드(stk_cd)는 필수 항목입니다.")
            
        if not mdfy_qty:
            raise HTTPException(status_code=400, detail="정정수량(mdfy_qty)은 필수 항목입니다.")
            
        if not mdfy_uv:
            raise HTTPException(status_code=400, detail="정정단가(mdfy_uv)는 필수 항목입니다.")
        
        response = await kiwoom_client.order_stock_modify(
            dmst_stex_tp=dmst_stex_tp,
            orig_ord_no=orig_ord_no,
            stk_cd=stk_cd,
            mdfy_qty=mdfy_qty,
            mdfy_uv=mdfy_uv,
            mdfy_cond_uv=mdfy_cond_uv,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"주식 정정주문 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/order/cancel")
async def order_stock_cancel(
    dmst_stex_tp: str = Query("KRX", description="국내거래소구분 - KRX:한국거래소, NXT:넥스트트레이드, SOR:최선주문집행"),
    orig_ord_no: str = Query(..., description="원주문번호"),
    stk_cd: str = Query(..., description="종목코드"),
    cncl_qty: str = Query(..., description="취소수량 ('0' 입력시 잔량 전부 취소)"),
    cont_yn: Optional[str] = Query("N", description="연속조회여부"),
    next_key: Optional[str] = Query("", description="연속조회키"),
    kiwoom_client: KiwoomClient = Depends(get_kiwoom_client)
):
    """주식 취소주문 (kt10003)"""
    try:
        if not kiwoom_client.connected:
            raise HTTPException(status_code=503, detail="키움 API에 연결되어 있지 않습니다.")
        
        # 기본 유효성 검사
        if not orig_ord_no:
            raise HTTPException(status_code=400, detail="원주문번호(orig_ord_no)는 필수 항목입니다.")
            
        if not stk_cd:
            raise HTTPException(status_code=400, detail="종목코드(stk_cd)는 필수 항목입니다.")
            
        if not cncl_qty:
            raise HTTPException(status_code=400, detail="취소수량(cncl_qty)은 필수 항목입니다.")
        
        response = await kiwoom_client.order_stock_cancel(
            dmst_stex_tp=dmst_stex_tp,
            orig_ord_no=orig_ord_no,
            stk_cd=stk_cd,
            cncl_qty=cncl_qty,
            cont_yn=cont_yn,
            next_key=next_key
        )
        
        return response
    except Exception as e:
        logger.error(f"주식 취소주문 엔드포인트 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))    