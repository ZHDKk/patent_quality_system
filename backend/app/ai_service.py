import os
import time
import base64
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

    def _get_temperature(self, model):
        """根据模型返回合适的 temperature 值"""
        if "k2.5" in model or model == "kimi-k2.5":
            return 1
        else:
            return 0.1

    def call_with_text(self, system_prompt, user_content, model="kimi-k2-turbo-preview"):
        """
        纯文本对话方式，兼容所有 Kimi 模型。
        对于 k2.5 系列模型，temperature 只能为 1。
        """
        self._rate_limit()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        temperature = self._get_temperature(model)
        completion = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature
        )
        results_str = completion.choices[0].message.content
        json_content = results_str.strip().replace("```json", "").replace("```", "").strip()
        return json_content

    def call_with_files(self, rule_file_path, patent_file_path, model="kimi-k2-turbo-preview"):
        """
        文件接口方式：上传规则文件和专利文档，让 AI 质检，同时返回文档文本内容。
        """
        self._rate_limit()
        rule_file = self.client.files.create(file=Path(rule_file_path), purpose="file-extract")
        patent_file = self.client.files.create(file=Path(patent_file_path), purpose="file-extract")
        doc_content = self.client.files.content(file_id=patent_file.id).text
        rule_content = self.client.files.content(file_id=rule_file.id).text

        messages = [
            {"role": "system", "content": rule_content},
            {"role": "system", "content": doc_content},
            {"role": "system", "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手..."},
            {"role": "user", "content": "你是一名专业的专利质检人员，请根据提供的质检规则库对专利文档进行详细质检，返回结果要保证准确度以及全面性。以 JSON 格式输出，包含字段：rule_id, issue, suggestion, severity。如果没有发现问题，返回空数组 []。"}
        ]
        temperature = self._get_temperature(model)
        completion = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature
        )
        result = completion.choices[0].message.content
        return {
            "result": result.strip().replace("```json", "").replace("```", "").strip(),
            "doc_content": doc_content
        }

    def call_multimodal(self, system_prompt, text_content, images, model="kimi-k2.5"):
        """
        多模态调用，适用于 k2.5 等支持图片的模型。
        :param system_prompt: 系统提示词
        :param text_content: 文档文本内容
        :param images: 图片信息列表，每项包含 'base64' 和 'mime_type' 或 'data_url'
        :param model: 模型名称
        :return: AI 返回的文本结果
        """
        self._rate_limit()
        user_content = []
        if text_content:
            user_content.append({"type": "text", "text": text_content})
        for img in images:
            # 优先使用 data_url，否则从 base64 构造
            if 'data_url' in img:
                data_url = img['data_url']
            else:
                mime = img.get('mime_type', 'image/png')
                b64 = img['base64']
                data_url = f"data:{mime};base64,{b64}"
            user_content.append({"type": "image_url", "image_url": {"url": data_url}})

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        temperature = self._get_temperature(model)
        completion = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature
        )
        result = completion.choices[0].message.content
        return result.strip().replace("```json", "").replace("```", "").strip()