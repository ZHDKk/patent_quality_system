import os
import concurrent.futures
from typing import List, BinaryIO

from docling.document_converter import DocumentConverter

class DocumentParser:
    """
    文档解析器，基于 Docling 实现。
    支持单文件解析、多文件并发解析、流式解析。
    """

    def __init__(self, max_workers: int = None):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)

    def parse(self, file_path: str) -> dict:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        converter = DocumentConverter()
        result = converter.convert(file_path)

        return self._extract_content(result)

    def parse_async(self, file_path: str):
        return self.executor.submit(self.parse, file_path)

    def parse_many(self, file_paths: List[str]) -> List[dict]:
        futures = [self.parse_async(fp) for fp in file_paths]
        return [f.result() for f in futures]

    def parse_stream(self, file_stream: BinaryIO, file_name: str = None) -> dict:
        converter = DocumentConverter()
        result = converter.convert(file_stream)
        return self._extract_content(result)

    def _extract_content(self, docling_result) -> dict:
        """从 Docling 结果中提取核心内容，确保返回的字典可 JSON 序列化"""
        doc = docling_result.document

        # 提取文本（兼容多种获取方式）
        try:
            text = doc.text
        except AttributeError:
            try:
                text = doc.export_to_text()
            except AttributeError:
                if hasattr(doc, 'texts'):
                    text = "\n".join([item.text for item in doc.texts])
                else:
                    text = str(doc)

        # 提取表格（转为 Markdown 格式文本）
        tables = []
        for table in doc.tables:
            try:
                tables.append(table.export_to_markdown())
            except AttributeError:
                try:
                    tables.append(table.text)
                except AttributeError:
                    tables.append(str(table))

        # 提取图片信息（仅记录数量）
        images = [f"image_{i}" for i, _ in enumerate(doc.pictures)]

        # 可选：保留 Docling 原始输出（便于调试），确保可 JSON 序列化
        try:
            # 如果 model_dump 存在且支持 mode='json'，则使用它生成 JSON 兼容字典
            if hasattr(doc, 'model_dump'):
                docling_output = doc.model_dump(mode='json')
            else:
                # 旧版 Pydantic 或没有 model_dump，则转为字符串
                docling_output = str(doc)
        except Exception:
            # 任何意外情况，使用字符串表示
            docling_output = str(doc)

        parsed_data = {
            "text": text,
            "tables": tables,
            "images": images,
            "docling_output": docling_output
        }
        return parsed_data

    def __del__(self):
        self.executor.shutdown(wait=False)