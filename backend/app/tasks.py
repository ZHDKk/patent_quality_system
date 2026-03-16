import json
import os
import tempfile
from datetime import datetime

from celery import Celery
from flask import current_app
from cryptography.fernet import Fernet
from .document_parser import DocumentParser
from .ai_service import KimiAIService
from .rule_engine import RuleEngine
from .models import db, PatentDocument, QualityCheckResult, RuleVersion

celery = Celery('tasks')
celery.conf.update(
    broker_url=os.environ.get('REDIS_URL', 'redis://redis:6379/0'),
    result_backend=os.environ.get('REDIS_URL', 'redis://redis:6379/0')
)

@celery.task(bind=True, max_retries=3)
def process_patent_document(self, doc_id, is_recheck=False, parent_result_id=None,
                            parse_mode='local', model='kimi-k2-turbo-preview'):
    """异步处理单个专利文档"""
    from . import create_app
    app = create_app()
    with app.app_context():
        doc = PatentDocument.query.get(doc_id)
        if not doc:
            return

        # 确保状态为 processing（重试时可能已是 processing）
        if doc.status != 'processing':
            doc.status = 'processing'
            db.session.commit()

        try:
            # 获取最新规则版本
            rule_engine = RuleEngine()
            rule_version_id = rule_engine.current_version_id
            rule_version = RuleVersion.query.get(rule_version_id)
            if not rule_version:
                raise Exception("No active rule version found")

            ai = KimiAIService()
            ai_result = None

            if parse_mode == 'local':
                # 本地解析模式
                parser = DocumentParser()
                parsed = parser.parse(doc.original_path)
                doc.parsed_json = json.dumps(parsed)
                db.session.commit()
                doc_text = parsed.get('text', '')

                system_prompt = rule_engine.get_system_prompt()
                ai_result_text = ai.call_with_text(system_prompt, doc_text, model=model)

                try:
                    issues = json.loads(ai_result_text)
                    if not isinstance(issues, list):
                        issues = []
                    ai_result = {'issues': issues, 'raw_output': ai_result_text}
                except json.JSONDecodeError:
                    ai_result = {'issues': [], 'raw_output': ai_result_text}

                report_text = doc_text

            else:  # online 模式
                # 解密规则文件
                key = os.environ.get('RULE_ENCRYPT_KEY')
                cipher = Fernet(key.encode() if isinstance(key, str) else key)
                with open(rule_version.rules_file_path, 'rb') as f:
                    encrypted = f.read()
                decrypted = cipher.decrypt(encrypted)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                    tmp.write(decrypted)
                    rule_temp_path = tmp.name

                result_dict = ai.call_with_files(rule_temp_path, doc.original_path, model=model)
                ai_result_text = result_dict['result']
                doc_content = result_dict['doc_content']
                os.unlink(rule_temp_path)

                try:
                    issues = json.loads(ai_result_text)
                    if not isinstance(issues, list):
                        issues = []
                    ai_result = {'issues': issues, 'raw_output': ai_result_text}
                except json.JSONDecodeError:
                    ai_result = {'issues': [], 'raw_output': ai_result_text}

                parsed = {'text': doc_content, 'tables': [], 'images': []}
                doc.parsed_json = json.dumps(parsed)
                db.session.commit()

            if ai_result is None:
                raise Exception("AI result not set")

            # 确定版本号
            version = 1
            if is_recheck and parent_result_id:
                parent = QualityCheckResult.query.get(parent_result_id)
                if parent:
                    version = parent.version + 1

            # 保存质检结果（此时 revised_doc_path 为 None，等待用户手动生成）
            result = QualityCheckResult(
                document_id=doc_id,
                version=version,
                parent_result_id=parent_result_id if is_recheck else None,
                rule_version_id=rule_version_id,
                result_json=json.dumps(ai_result),
                revised_doc_path=None,  # 初始为 None
                check_time=datetime.utcnow()
            )
            db.session.add(result)
            doc.status = 'completed'
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            if self.request.retries < self.max_retries:
                current_app.logger.warning(
                    f"Processing failed for doc {doc_id}, retrying ({self.request.retries+1}/{self.max_retries}): {e}"
                )
                raise self.retry(exc=e, countdown=60)
            else:
                doc.status = 'failed'
                db.session.commit()
                current_app.logger.error(f"Processing failed for doc {doc_id}, no more retries: {e}")
                raise