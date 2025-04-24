from pydantic import BaseModel
from typing import List, Optional, Union


class RealtimePriceRequest(BaseModel):
    group_no: str = "1"
    items: List[str]
    data_types: List[str] = ["0D"]
    refresh: bool = True
    
    class Config:
        schema_extra = {
            "example": {
                "group_no": "1",
                "items": ["005930", "000660"],
                "data_types": ["0D"],
                "refresh": True
            }
        }
class RealtimePriceUnsubscribeRequest(BaseModel):
    group_no: str = "1"
    items: Optional[List[str]] = None
    data_types: Optional[List[str]] = None
    
    class Config:
        schema_extra = {
            "example": {
                "group_no": "1",
                "items": ["005930", "000660"],
                "data_types": ["0D"]
            }
        }
        
# 기존 ConditionalSearch 모델 (다른 엔드포인트에서 사용 중이므로 유지)
class ConditionalSearch(BaseModel):
    seq: str
    search_type: str = "1"
    market_type: str = "K"

# 수정된 요구사항에 맞는 새 모델
class ConditionalSearchRequest(BaseModel):
    seq: str = "4"
    search_type: str = "0"
    market_type: str = "K"
    cont_yn: str = "N"
    next_key: str = ""
    
    class Config:
        schema_extra = {
            "example": {
                "seq": "4",
                "search_type": "0",
                "market_type": "K",
                "cont_yn": "N",
                "next_key": ""
            }
        }

# 기타 기존 모델들
class StockInfo(BaseModel):
    code: str
    name: str
    market: str
    price: float
    change: float
    change_ratio: float
    volume: int

class StockRegistration(BaseModel):
    items: List[str]
    types: List[str]
    refresh: bool = False

class GroupRegistration(BaseModel):
    group_no: str
    registration: StockRegistration