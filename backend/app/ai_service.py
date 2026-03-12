import requests
import time
from flask import current_app

class KimiAIService:
    def __init__(self, api_key=None):
        self.api_key = api_key or current_app.config['KIMI_API_KEY']
        self.api_url = "https://api.moonshot.cn/v1"
        self.last_call = 0

    def call(self, system_prompt, user_content):
        # 限流
        now = time.time()
        if now - self.last_call < 1:
            time.sleep(1 - (now - self.last_call))
        self.last_call = time.time()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "moonshot-v1-8k",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content[:30000]}  # 截断避免超长
            ],
            "temperature": 0.1
        }
        response = requests.post(f"{self.api_url}/chat/completions", json=payload, headers=headers)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            current_app.logger.error(f"Kimi API error: {response.text}")
            raise Exception(f"AI service error: {response.status_code}")