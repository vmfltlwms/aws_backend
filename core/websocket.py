
import logging
from typing import List, Dict, Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    """웹소켓 연결 관리자"""
    
    def __init__(self):
        self.active_connections: List[Dict[str, Any]] = []
        self.client_groups: Dict[str, List[WebSocket]] = {}
        
    async def connect(self, websocket: WebSocket, client_id: str = None, groups: List[str] = None):
        """클라이언트 연결 및 그룹 등록"""
        try:
            await websocket.accept()
            
            # 클라이언트 정보 저장
            connection_info = {
                "websocket": websocket,
                "client_id": client_id or id(websocket),
                "groups": groups or []
            }
            
            self.active_connections.append(connection_info)
            
            # 그룹에 등록
            if groups:
                for group in groups:
                    if group not in self.client_groups:
                        self.client_groups[group] = []
                    self.client_groups[group].append(websocket)
            
            logger.info(f"새 클라이언트 연결: {connection_info['client_id']}. 현재 {len(self.active_connections)}개 연결")
            return connection_info
        except Exception as e:
            logger.error(f"클라이언트 연결 중 오류 발생: {str(e)}")
            raise
    
    def disconnect(self, websocket: WebSocket):
        """클라이언트 연결 해제"""
        # 연결 정보 찾기
        connection = next((conn for conn in self.active_connections if conn["websocket"] == websocket), None)
        
        if connection:
            # 그룹에서 제거
            for group in connection["groups"]:
                if group in self.client_groups and websocket in self.client_groups[group]:
                    self.client_groups[group].remove(websocket)
                    # 빈 그룹 정리
                    if not self.client_groups[group]:
                        del self.client_groups[group]
            
            # 연결 목록에서 제거
            self.active_connections.remove(connection)
            logger.info(f"클라이언트 연결 종료: {connection['client_id']}. 현재 {len(self.active_connections)}개 연결")
    
    async def send_personal_message(self, message: Any, websocket: WebSocket):
        """특정 클라이언트에게 메시지 전송"""
        if isinstance(message, dict):
            await websocket.send_json(message)
        else:
            await websocket.send_text(str(message))
    
    async def broadcast(self, message: Any):
        """모든 클라이언트에게 메시지 전송"""
        disconnected = []
        
        for connection in self.active_connections:
            websocket = connection["websocket"]
            try:
                if isinstance(message, dict):
                    await websocket.send_json(message)
                else:
                    await websocket.send_text(str(message))
            except Exception as e:
                logger.error(f"메시지 전송 오류: {str(e)}")
                disconnected.append(websocket)
        
        # 연결이 끊긴 클라이언트 정리
        for websocket in disconnected:
            self.disconnect(websocket)
    
    async def broadcast_to_group(self, group: str, message: Any):
        """특정 그룹의 클라이언트에게 메시지 전송"""
        if group not in self.client_groups:
            return
        
        disconnected = []
        
        for websocket in self.client_groups[group]:
            try:
                if isinstance(message, dict):
                    await websocket.send_json(message)
                else:
                    await websocket.send_text(str(message))
            except Exception as e:
                logger.error(f"그룹 메시지 전송 오류: {str(e)}")
                disconnected.append(websocket)
        
        # 연결이 끊긴 클라이언트 정리
        for websocket in disconnected:
            self.disconnect(websocket)