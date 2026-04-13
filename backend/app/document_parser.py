import hashlib
import logging
import os
import subprocess
import tempfile
import concurrent.futures
from typing import List, BinaryIO
from pathlib import Path
from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)

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
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        return os.path.join(self.cache_dir, f"{file_hash}.docx") if self.cache_dir else None

    def _convert_with_cache(self, doc_path: str) -> str:
        if self.cache_dir:
            cache_path = self._get_cache_path(doc_path)
            if os.path.exists(cache_path):
                logger.info(f"Using cached converted file: {cache_path}")
                return cache_path

        converted = self._convert_doc_to_docx(doc_path)

        if self.cache_dir and cache_path:
            import shutil
            shutil.copy2(converted, cache_path)
            os.unlink(converted)
            return cache_path

        return converted

    def _is_doc_format(self, file_path: str) -> bool:
        return file_path.lower().endswith('.doc')

    def _convert_doc_to_docx(self, doc_path: str) -> str:
        """
        使用 LibreOffice 将 .doc 转换为 .docx
        返回转换后的临时文件路径
        """
        logger.info(f"Starting conversion of .doc file: {doc_path}")
        if not os.path.exists(doc_path):
            raise FileNotFoundError(f"Source .doc file not found: {doc_path}")

        # 创建临时输出目录
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                'soffice',
                '--headless',
                '--convert-to', 'docx',
                '--outdir', tmpdir,
                doc_path
            ]
            logger.info(f"Running command: {' '.join(cmd)}")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                logger.info(f"LibreOffice stdout: {result.stdout}")
                # 查找生成的 .docx 文件
                base_name = os.path.splitext(os.path.basename(doc_path))[0]
                converted_file = os.path.join(tmpdir, base_name + '.docx')
                if os.path.exists(converted_file):
                    # 将文件移动到持久临时位置（避免 tmpdir 自动清理）
                    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp_out:
                        final_path = tmp_out.name
                    import shutil
                    shutil.copy2(converted_file, final_path)
                    logger.info(f"Conversion successful: {final_path}")
                    return final_path
                else:
                    raise Exception(f"Conversion output not found: {result.stderr}")
            except subprocess.CalledProcessError as e:
                logger.error(f"LibreOffice conversion error: {e.stderr}")
                raise Exception(f"LibreOffice conversion error: {e.stderr}")
            except FileNotFoundError:
                logger.error("LibreOffice 'soffice' command not found. Please ensure LibreOffice is installed.")
                raise Exception("LibreOffice is not installed or not in PATH")

    def parse(self, file_path: str) -> dict:
        """解析单个文档，自动处理 .doc 格式"""
        logger.info(f"Parsing document: {file_path}")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        need_cleanup = False
        actual_file_path = file_path

        if self._is_doc_format(file_path):
            logger.info("File is .doc format, attempting LibreOffice conversion...")
            try:
                actual_file_path = self._convert_doc_to_docx(file_path)
                need_cleanup = True
                logger.info(f"Converted to: {actual_file_path}")
            except Exception as e:
                logger.error(f".doc conversion failed: {e}")
                raise Exception(f"Failed to convert .doc to .docx: {e}")
        else:
            logger.info("File is not .doc, proceeding directly with Docling.")

        try:
            converter = DocumentConverter()
            logger.info("Starting Docling conversion...")
            result = converter.convert(actual_file_path)
            logger.info("Docling conversion completed.")
            return self._extract_content(result)
        finally:
            if need_cleanup and os.path.exists(actual_file_path):
                os.unlink(actual_file_path)
                logger.info(f"Cleaned up temporary file: {actual_file_path}")

    def parse_async(self, file_path: str):
        """异步解析，返回 Future 对象"""
        return self.executor.submit(self.parse, file_path)

    def parse_many(self, file_paths: List[str]) -> List[dict]:
        """并发解析多个文档"""
        futures = [self.parse_async(fp) for fp in file_paths]
        return [f.result() for f in futures]

    def _extract_content(self, docling_result) -> dict:
        """从 Docling 结果中提取文本、表格和图片（base64）"""
        doc = docling_result.document

        # 提取文本
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

        # 提取图片信息（base64 数据）
        images = []
        for idx, picture in enumerate(doc.pictures):
            try:
                # 从 picture.image.uri 获取 data URL
                if hasattr(picture, 'image') and hasattr(picture.image, 'uri'):
                    uri = str(picture.image.uri)
                    if uri.startswith('data:image/'):
                        # 提取 base64 部分（逗号之后）
                        base64_part = uri.split(',', 1)[-1]
                        mime_part = uri.split(';')[0].replace('data:', '')
                        images.append({
                            'index': idx,
                            'mime_type': mime_part,
                            'base64': base64_part,
                            'data_url': uri  # 保留完整 URL 以便直接使用
                        })
                        continue
            except Exception as e:
                logger.warning(f"Failed to extract picture {idx}: {e}")

            # 备用方案：尝试从其他属性获取
            try:
                if hasattr(picture, 'get_data'):
                    img_data = picture.get_data()
                    import base64
                    b64 = base64.b64encode(img_data).decode('utf-8')
                    images.append({
                        'index': idx,
                        'mime_type': 'image/png',  # 默认
                        'base64': b64,
                        'data_url': f"data:image/png;base64,{b64}"
                    })
                else:
                    logger.warning(f"Picture {idx} has no accessible data")
            except Exception as e:
                logger.warning(f"Picture {idx} extraction failed: {e}")

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
            "images": images,                # 新增：图片 base64 列表
            "docling_output": docling_output
        }

    def __del__(self):
        self.executor.shutdown(wait=False)