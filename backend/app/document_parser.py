import requests
import json

class DocumentParser:
    def __init__(self, dedoc_url='http://dedoc:1231'):
        self.dedoc_url = dedoc_url

    def parse(self, file_path):
        """
        调用 Dedoc 解析文档，返回结构化 JSON
        """
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(f'{self.dedoc_url}/upload', files=files)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Dedoc parsing failed: {response.text}")