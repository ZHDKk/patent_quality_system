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
                            parse_mode='local', model='kimi-k2-turbo-preview', rule_version_id=None,
                            text_only=False):  # 新增参数
    """异步处理单个专利文档，支持指定规则版本和模型，支持纯文本模式"""
    from . import create_app
    app = create_app()
    with app.app_context():
        doc = PatentDocument.query.get(doc_id)
        if not doc:
            return

        if doc.status != 'processing':
            doc.status = 'processing'
            db.session.commit()

        try:
            # 加载规则引擎
            if rule_version_id:
                rule_engine = RuleEngine(version_id=rule_version_id)
            else:
                rule_engine = RuleEngine()
            rule_version_id = rule_engine.current_version_id
            if not rule_version_id:
                raise Exception("未找到可用的规则版本")
            rule_version = RuleVersion.query.get(rule_version_id)
            if not rule_version:
                raise Exception("No active rule version found")

            ai = KimiAIService()
            ai_result = None

            if parse_mode == 'local':
                parser = DocumentParser()
                parsed = parser.parse(doc.original_path)
                doc.parsed_json = json.dumps(parsed)
                db.session.commit()

                doc_text = parsed.get('text', '')
                tables_text = "\n".join(parsed.get('tables', []))
                full_text = f"{doc_text}\n\n表格内容：\n{tables_text}" if tables_text else doc_text
                images = parsed.get('images', [])

                system_prompt = rule_engine.get_system_prompt()

                # 判断是否使用多模态：模型为k2.5系列、有图片、且未启用纯文本模式
                use_multimodal = (("k2.5" in model or model == "kimi-k2.5") and images and not text_only)

                if use_multimodal:
                    multimodal_prompt = f"{system_prompt}\n\n文档文本内容如下：\n{full_text}\n\n请结合文档中的图片进行质检。"
                    ai_result_text = ai.call_multimodal(
                        system_prompt=system_prompt,
                        text_content=multimodal_prompt,
                        images=images,
                        model=model
                    )
                else:
                    ai_result_text = ai.call_with_text(system_prompt, full_text, model=model)

                try:
                    issues = json.loads(ai_result_text)
                    if not isinstance(issues, list):
                        issues = []
                    ai_result = {'issues': issues, 'raw_output': ai_result_text}
                except json.JSONDecodeError:
                    ai_result = {'issues': [], 'raw_output': ai_result_text}

            else:  # online 模式
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

            version = 1
            if is_recheck and parent_result_id:
                parent = QualityCheckResult.query.get(parent_result_id)
                if parent:
                    version = parent.version + 1

            result = QualityCheckResult(
                document_id=doc_id,
                version=version,
                parent_result_id=parent_result_id if is_recheck else None,
                rule_version_id=rule_version_id,
                result_json=json.dumps(ai_result),
                revised_doc_path=None,
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