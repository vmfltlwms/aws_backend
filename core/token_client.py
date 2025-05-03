# core/token_client.py
import requests
import time
from config import settings

REAL_HOST = 'https://api.kiwoom.com'
MOCK_HOST = 'https://mockapi.kiwoom.com'

class TokenGenerator:
    def __init__(self, real=settings.KIWOOM_REAL_SERVER):
        # 실전투자 또는 모의투자 호스트 선택
        self.host = REAL_HOST if real else MOCK_HOST
        self.app_key = settings.KIWOOM_APP_KEY
        self.sec_key = settings.KIWOOM_SECRET_KEY
        self.token = None
        self._issued_at = None
    
    def get_token(self):
        now = time.time()  # 현재 시간 (타임스탬프)
        if self.token and self._issued_at and (now - self._issued_at) < 6 * 3600:
            return self.token  # 6시간 내면 기존 토큰 반환
        
        self.token = self.token_gen()
        self._issued_at = now
        return self.token
    
    def token_gen(self):
        # 요청할 API URL
        endpoint = '/oauth2/token'
        url = self.host + endpoint
        
        # header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
        }
        
        # 요청 데이터
        data = {
            'grant_type': 'client_credentials',
            'appkey': self.app_key,
            'secretkey': self.sec_key,
        }
        
        # HTTP POST 요청
        response = requests.post(url, headers=headers, json=data)

        response_data = response.json()
        
        return response_data["token"]

    def delete_token(self):
        # 요청할 API URL
        endpoint = '/oauth2/revoke'
        url = self.host + endpoint
        
        # header 데이터
        headers = {
            'Content-Type': 'application/json;charset=UTF-8',
        }
        
        # 요청 데이터
        data = {
            'grant_type': 'client_credentials',
            'appkey': self.app_key,
            'secretkey': self.sec_key,
        }
        
        # HTTP POST 요청
        response = requests.post(url, headers=headers, json=data)

        response_data = response.json()
        
        return response_data["return_msg"]



