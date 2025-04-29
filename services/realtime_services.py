import logging
from typing import Dict, List, Set, Any

logger = logging.getLogger(__name__)

class RealtimeStateManager:
    """실시간 상태 관리 클래스"""
    
    def __init__(self):
        """
        요청데이타 형식
        {
            "trnm" : "REG",
            "grp_no" : "1",
            "refresh" : "1",  # 1: 기존 등록 유지(추가), 0: 기존 등록 유지 안함(초기화)
            "data" : [{
                " item" : [ "" ],
                " type" : [ "00" ]
            }]
        }
        """
        # 그룹별 구독 정보
        self.subscriptions: Dict[str, Dict[str, Any]] = {}
        # 조건검색 구독 정보
        self.condition_subscriptions: Set[str] = set()
        
    def add_subscription(self, group_no: str, items: List[str], data_types: List[str], refresh: bool = True) -> None:
        """
        그룹에 구독 정보 추가
        
        Args:
            group_no: 그룹 번호
            items: 종목 코드 리스트
            data_types: 데이터 타입 리스트
            refresh: True(1)이면 기존 등록 유지(추가), False(0)이면 기존 등록 유지 안함(초기화)
        """
        if not refresh or group_no not in self.subscriptions:
            # refresh=False(0) 또는 새 그룹이면 초기화
            self.subscriptions[group_no] = {
                "items": set(items),
                "data_types": set(data_types)
            }
        else:
            # refresh=True(1)이면 기존에 추가
            self.subscriptions[group_no]["items"].update(items)
            self.subscriptions[group_no]["data_types"].update(data_types)
        
        logger.debug(f"그룹 {group_no} 구독 추가: {items}, {data_types}, refresh: {refresh}")
    
    def remove_subscription(self, group_no: str, items: List[str] = None, data_types: List[str] = None) -> None:
        """그룹에서 구독 정보 제거"""
        if group_no not in self.subscriptions:
            return
            
        if items is None and data_types is None:
            # 그룹 전체 삭제
            del self.subscriptions[group_no]
            logger.debug(f"그룹 {group_no} 구독 전체 삭제")
            return
            
        # 특정 종목 또는 데이터 타입만 삭제
        if items:
            self.subscriptions[group_no]["items"] -= set(items)
            
        if data_types:
            self.subscriptions[group_no]["data_types"] -= set(data_types)
            
        # 종목이나 데이터 타입이 비어있으면 그룹 삭제
        if not self.subscriptions[group_no]["items"] or not self.subscriptions[group_no]["data_types"]:
            del self.subscriptions[group_no]
            
        logger.debug(f"그룹 {group_no} 구독 일부 삭제: {items}, {data_types}")
    
    def get_subscription(self, group_no: str) -> Dict[str, Any]:
        """그룹의 구독 정보 조회"""
        if group_no in self.subscriptions:
            return {
                "items": list(self.subscriptions[group_no]["items"]),
                "data_types": list(self.subscriptions[group_no]["data_types"])
            }
        return {"items": [], "data_types": []}
    
    def get_all_subscriptions(self) -> Dict[str, Dict[str, Any]]:
        """모든 구독 정보 조회"""
        result = {}
        for group_no, data in self.subscriptions.items():
            result[group_no] = {
                "items": list(data["items"]),
                "data_types": list(data["data_types"])
            }
        return result
    
    def add_condition_subscription(self, condition_seq: str) -> None:
        """조건검색 구독 추가"""
        self.condition_subscriptions.add(condition_seq)
        logger.debug(f"조건검색 {condition_seq} 구독 추가")
    
    def remove_condition_subscription(self, condition_seq: str) -> None:
        """조건검색 구독 제거"""
        if condition_seq in self.condition_subscriptions:
            self.condition_subscriptions.remove(condition_seq)
            logger.debug(f"조건검색 {condition_seq} 구독 삭제")
    
    def get_condition_subscriptions(self) -> List[str]:
        """구독 중인 조건검색 목록 조회"""
        return list(self.condition_subscriptions)