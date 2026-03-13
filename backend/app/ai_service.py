import os
import time
from pathlib import Path
from openai import OpenAI
from flask import current_app

class KimiAIService:
    def __init__(self, api_key=None):
        self.api_key = api_key or current_app.config['KIMI_API_KEY']
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.moonshot.cn/v1"
        )
        self.last_call = 0

    def _rate_limit(self):
        now = time.time()
        if now - self.last_call < 1:
            time.sleep(1 - (now - self.last_call))
        self.last_call = time.time()

    def call_with_text(self, system_prompt, user_content, model="kimi-k2-turbo-preview"):
        """纯文本对话方式：system_prompt 包含规则文本，user_content 包含文档文本"""
        self._rate_limit()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        completion = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1
        )
        return completion.choices[0].message.content

    def call_with_files(self, rule_file_path, patent_file_path, model="kimi-k2-turbo-preview"):
        """
        文件接口方式：上传规则文件和专利文档，让 AI 质检，同时返回文档文本内容。
        :return: dict with keys 'result' (AI 回答) and 'doc_content' (文档提取的文本)
        """
        self._rate_limit()
        # 上传规则文件
        rule_file = self.client.files.create(file=Path(rule_file_path), purpose="file-extract")
        # 上传专利文档
        patent_file = self.client.files.create(file=Path(patent_file_path), purpose="file-extract")
        # 获取文档内容
        doc_content = self.client.files.content(file_id=patent_file.id).text
        # 获取规则文件内容
        rule_content = self.client.files.content(file_id=rule_file.id).text

        # 构造消息
        messages = [
            {"role": "system", "content": rule_content},
            {"role": "system", "content": doc_content},
            {"role": "system", "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，准确的回答。同时，你会拒绝一切涉及恐怖主义，种族歧视，黄色暴力等问题的回答。Moonshot AI 为专有名词，不可翻译成其他语言。"},
            {"role": "user", "content": "你是一名专业的专利质检人员，请根据提供的质检规则库对专利文档进行质检，返回结果要保证准确度以及全面性。以 JSON 格式输出，包含字段：rule_id, issue, suggestion, severity。如果没有发现问题，返回空数组 []。"}
        ]
        completion = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1
        )
        result = completion.choices[0].message.content
        return {"result": result, "doc_content": doc_content}