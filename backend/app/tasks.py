import json
import os
from celery import Celery
from flask import current_app
from .document_parser import DocumentParser
from .ai_service import KimiAIService
from .rule_engine import RuleEngine
from .report_generator import generate_report
from .models import db, PatentDocument, QualityCheckResult

celery = Celery('tasks')
celery.conf.update(
    broker_url=os.environ.get('REDIS_URL', 'redis://redis:6379/0'),
    result_backend=os.environ.get('REDIS_URL', 'redis://redis:6379/0')
)

@celery.task(bind=True)
def process_patent_document(self, doc_id, is_recheck=False, parent_result_id=None):
    """异步处理单个专利文档"""
    # 需要应用上下文来使用 Flask 的配置和数据库
    from . import create_app
    app = create_app()
    with app.app_context():
        doc = PatentDocument.query.get(doc_id)
        if not doc:
            return

        doc.status = 'processing'
        db.session.commit()

        try:
            # 1. 解析文档
            parser = DocumentParser()
            parsed = parser.parse(doc.original_path)
            doc.parsed_json = json.dumps(parsed)
            db.session.commit()

            # 2. 获取最新规则
            rule_engine = RuleEngine()
            system_prompt = rule_engine.get_system_prompt()
            rule_version_id = rule_engine.current_version_id

            # 3. 调用 AI
            ai = KimiAIService()
            # 将解析出的文本内容传给 AI
            text_content = parsed.get('text', '')
            user_content = f"请根据以下专利文档内容进行质检：\n\n{text_content[:20000]}"  # 截断
            ai_result = ai.call(system_prompt, user_content)

            # 4. 解析 AI 结果（假设返回 JSON 格式，需处理）
            # 这里简单包装
            result_json = {
                'raw_output': ai_result,
                'issues': []  # 可以从 AI 结果中解析
            }

            # 5. 生成报告
            report_path = generate_report(doc.original_path, result_json)

            # 6. 确定版本号
            version = 1
            if is_recheck and parent_result_id:
                parent = QualityCheckResult.query.get(parent_result_id)
                if parent:
                    version = parent.version + 1

            # 7. 保存质检结果
            result = QualityCheckResult(
                document_id=doc_id,
                version=version,
                parent_result_id=parent_result_id if is_recheck else None,
                rule_version_id=rule_version_id,
                result_json=json.dumps(result_json),
                report_path=report_path,
                check_time=datetime.utcnow()
            )
            db.session.add(result)
            doc.status = 'completed'
            db.session.commit()

        except Exception as e:
            doc.status = 'failed'
            db.session.commit()
            current_app.logger.error(f"Processing failed for doc {doc_id}: {e}")
            # 可重试，这里简单抛出异常让 Celery 重试
            raise self.retry(exc=e, countdown=60, max_retries=3)