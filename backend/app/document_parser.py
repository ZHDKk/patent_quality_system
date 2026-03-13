import hashlib
import os
import subprocess
import tempfile
import concurrent.futures
from typing import List, BinaryIO
from pathlib import Path
from docling.document_converter import DocumentConverter

class DocumentParser:
    """
    文档解析器，基于 Docling 实现，支持通过 LibreOffice 转换 .doc 格式
    """

    def __init__(self, max_workers: int = None, cache_dir: str = None):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.cache_dir = cache_dir
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _get_cache_path(self, file_path: str) -> str:
        """根据原文件内容生成缓存路径"""
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        return os.path.join(self.cache_dir, f"{file_hash}.docx") if self.cache_dir else None

    def _convert_with_cache(self, doc_path: str) -> str:
        """带缓存的转换"""
        if self.cache_dir:
            cache_path = self._get_cache_path(doc_path)
            if os.path.exists(cache_path):
                return cache_path

        # 执行转换
        converted = self._convert_doc_to_docx(doc_path)

        # 如果启用缓存，复制到缓存目录
        if self.cache_dir and cache_path:
            import shutil
            shutil.copy2(converted, cache_path)
            os.unlink(converted)  # 删除临时文件
            return cache_path

        return converted

    def _is_doc_format(self, file_path: str) -> bool:
        """判断是否为旧的 .doc 格式"""
        ext = os.path.splitext(file_path)[1].lower()
        return ext == '.doc'

    def _convert_doc_to_docx(self, doc_path: str) -> str:
        """
        使用 LibreOffice 将 .doc 转换为 .docx
        返回转换后的临时文件路径
        """
        # 创建临时目录存放转换后的文件
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp_file:
            output_path = tmp_file.name

        # 构建 LibreOffice 命令
        cmd = [
            'soffice',
            '--headless',           # 无界面模式
            '--convert-to', 'docx',  # 转换为 docx
            '--outdir', os.path.dirname(output_path),  # 输出目录
            doc_path                 # 输入文件
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            # LibreOffice 会生成与输入同名的文件，只是扩展名改为 .docx
            # 我们需要找到这个文件
            base_name = os.path.splitext(os.path.basename(doc_path))[0]
            converted_file = os.path.join(os.path.dirname(output_path), base_name + '.docx')

            if os.path.exists(converted_file):
                return converted_file
            else:
                raise Exception(f"Conversion failed: {result.stderr}")
        except subprocess.CalledProcessError as e:
            raise Exception(f"LibreOffice conversion error: {e.stderr}")

    def parse(self, file_path: str) -> dict:
        """解析单个文档，自动处理 .doc 格式"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        need_cleanup = False
        actual_file_path = file_path

        # 如果是 .doc 格式，先转换为 .docx
        if self._is_doc_format(file_path):
            try:
                actual_file_path = self._convert_doc_to_docx(file_path)
                need_cleanup = True  # 标记需要清理临时文件
            except Exception as e:
                raise Exception(f"Failed to convert .doc to .docx: {e}")

        try:
            converter = DocumentConverter()
            result = converter.convert(actual_file_path)
            return self._extract_content(result)
        finally:
            # 如果创建了临时文件，删除它
            if need_cleanup and os.path.exists(actual_file_path):
                os.unlink(actual_file_path)

    def parse_async(self, file_path: str):
        """异步解析，返回 Future 对象"""
        return self.executor.submit(self.parse, file_path)

    def parse_many(self, file_paths: List[str]) -> List[dict]:
        """并发解析多个文档"""
        futures = [self.parse_async(fp) for fp in file_paths]
        return [f.result() for f in futures]

    def _extract_content(self, docling_result) -> dict:
        """从 Docling 结果中提取核心内容（复用之前兼容性代码）"""
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

        # 保留 Docling 原始输出（确保可 JSON 序列化）
        try:
            if hasattr(doc, 'model_dump'):
                docling_output = doc.model_dump(mode='json')
            else:
                docling_output = str(doc)
        except Exception:
            docling_output = str(doc)

        return {
            "text": text,
            "tables": tables,
            "images": images,
            "docling_output": docling_output
        }

    def __del__(self):
        self.executor.shutdown(wait=False)