import os
import json
import uuid

from flask import Blueprint, request, jsonify, render_template, current_app, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from .models import db, PatentDocument, QualityCheckResult, OperationLog, RuleVersion, User
from .tasks import process_patent_document
from .rule_engine import RuleEngine
from .decorators import admin_required
from .utils import log_operation
from deepdiff import DeepDiff

main_bp = Blueprint('main', __name__)

ALLOWED_EXTENSIONS = {'doc', 'docx', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@main_bp.route('/')
@login_required
def index():
    return redirect(url_for('main.upload'))

@main_bp.route('/upload', methods=['GET', 'POST'])
@login_required
@log_operation('upload')
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        if file and allowed_file(file.filename):
            original_filename = file.filename
            # 生成安全的存储文件名
            safe_filename = secure_filename(original_filename)
            if not safe_filename:
                ext = os.path.splitext(original_filename)[1]
                safe_filename = str(uuid.uuid4()) + ext
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)
            file.save(file_path)

            doc = PatentDocument(
                filename=original_filename,  # 保存原始文件名用于显示
                original_path=file_path,
                uploader_id=current_user.id
            )
            db.session.add(doc)
            db.session.commit()

            is_recheck = request.form.get('is_recheck') == 'yes'
            parent_id = request.form.get('parent_result_id')
            parse_mode = request.form.get('parse_mode', 'local')
            model = request.form.get('model', 'kimi-k2-turbo-preview')

            process_patent_document.delay(doc.id, is_recheck, parent_id, parse_mode, model)

            return jsonify({'status': 'success', 'doc_id': doc.id})
        else:
            return jsonify({'error': 'File type not allowed'}), 400

    recent_docs = PatentDocument.query.filter_by(uploader_id=current_user.id).order_by(PatentDocument.upload_time.desc()).limit(10).all()
    return render_template('upload.html', recent_docs=recent_docs)

@main_bp.route('/batch_upload', methods=['POST'])
@login_required
@log_operation('batch_upload')
def batch_upload():
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files'}), 400

    parse_mode = request.form.get('parse_mode', 'local')
    model = request.form.get('model', 'kimi-k2-turbo-preview')

    doc_ids = []
    for file in files:
        if file and allowed_file(file.filename):
            original_filename = file.filename
            safe_filename = secure_filename(original_filename)
            if not safe_filename:
                ext = os.path.splitext(original_filename)[1]
                safe_filename = str(uuid.uuid4()) + ext
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)
            file.save(file_path)

            doc = PatentDocument(
                filename=original_filename,
                original_path=file_path,
                uploader_id=current_user.id
            )
            db.session.add(doc)
            db.session.flush()
            doc_ids.append(doc.id)
    db.session.commit()

    for doc_id in doc_ids:
        process_patent_document.delay(doc_id, parse_mode=parse_mode, model=model)

    return jsonify({'status': 'success', 'doc_ids': doc_ids, 'count': len(doc_ids)})

@main_bp.route('/results')
@login_required
def results():
    page = request.args.get('page', 1, type=int)
    per_page = 30
    query = PatentDocument.query.filter_by(uploader_id=current_user.id).order_by(PatentDocument.upload_time.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    docs = pagination.items
    return render_template('results.html', docs=docs, pagination=pagination)

@main_bp.route('/result/<int:doc_id>')
@login_required
def view_result(doc_id):
    doc = PatentDocument.query.get_or_404(doc_id)
    if doc.uploader_id != current_user.id and current_user.role != 'admin':
        flash('Access denied')
        return redirect(url_for('main.results'))
    results = QualityCheckResult.query.filter_by(document_id=doc_id).order_by(QualityCheckResult.version).all()
    return render_template('result_detail.html', doc=doc, results=results)

@main_bp.route('/compare')
@login_required
def compare():
    doc_id = request.args.get('doc_id')
    if not doc_id:
        flash('Missing document ID')
        return redirect(url_for('main.results'))
    doc = PatentDocument.query.get_or_404(doc_id)
    if doc.uploader_id != current_user.id and current_user.role != 'admin':
        flash('Access denied')
        return redirect(url_for('main.results'))
    versions = QualityCheckResult.query.filter_by(document_id=doc_id).order_by(QualityCheckResult.version).all()
    return render_template('compare.html', doc=doc, versions=versions)

@main_bp.route('/api/compare/<int:version1>/<int:version2>')
@login_required
def api_compare(version1, version2):
    v1 = QualityCheckResult.query.get_or_404(version1)
    v2 = QualityCheckResult.query.get_or_404(version2)
    # 权限检查
    if v1.document.uploader_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    if v2.document.uploader_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403

    data1 = json.loads(v1.result_json)
    data2 = json.loads(v2.result_json)
    diff = DeepDiff(data1, data2, ignore_order=True)
    return jsonify(diff.to_dict())

@main_bp.route('/admin/rules', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_rules():
    if request.method == 'POST':
        if 'rule_file' not in request.files:
            flash('No file')
            return redirect(request.url)
        file = request.files['rule_file']
        if file.filename == '':
            flash('No file selected')
            return redirect(request.url)
        if file and file.filename.endswith('.xlsx'):
            filename = secure_filename(file.filename)
            temp_path = os.path.join('/tmp', filename)
            file.save(temp_path)

            description = request.form.get('description', '')
            engine = RuleEngine()
            try:
                engine.update_rules(temp_path, description, current_user.id)
                flash('规则已更新')
            except Exception as e:
                flash(f'更新失败: {str(e)}')
            return redirect(url_for('main.manage_rules'))
        else:
            flash('请上传 .xlsx 文件')

    versions = RuleVersion.query.order_by(RuleVersion.created_at.desc()).all()
    return render_template('manage_rules.html', versions=versions)

@main_bp.route('/admin/users')
@login_required
@admin_required
def manage_users():
    users = User.query.all()
    return render_template('manage_users.html', users=users)

@main_bp.route('/api/document/<int:doc_id>/details')
@login_required
def document_details(doc_id):
    doc = PatentDocument.query.get_or_404(doc_id)
    if doc.uploader_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403
    results = QualityCheckResult.query.filter_by(document_id=doc_id).order_by(QualityCheckResult.version.desc()).all()
    results_data = []
    for res in results:
        try:
            result_content = json.loads(res.result_json)
        except:
            result_content = {"raw_output": res.result_json, "issues": []}
        results_data.append({
            'id': res.id,
            'version': res.version,
            'check_time': res.check_time.isoformat(),
            'result': result_content
        })
    return jsonify({
        'id': doc.id,
        'filename': doc.filename,
        'status': doc.status,
        'upload_time': doc.upload_time.isoformat(),
        'results': results_data
    })

@main_bp.route('/api/document/<int:doc_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_document(doc_id):
    doc = PatentDocument.query.get_or_404(doc_id)
    try:
        if os.path.exists(doc.original_path):
            os.remove(doc.original_path)
        for result in doc.results:
            if result.report_path and os.path.exists(result.report_path):
                os.remove(result.report_path)
    except Exception as e:
        current_app.logger.error(f"Error deleting files for doc {doc_id}: {e}")
    db.session.delete(doc)
    db.session.commit()
    return jsonify({'status': 'success'})

@main_bp.route('/api/documents/batch_delete', methods=['POST'])
@login_required
@admin_required
def batch_delete_documents():
    data = request.get_json()
    if not data or 'doc_ids' not in data:
        return jsonify({'error': 'Missing doc_ids'}), 400
    doc_ids = data['doc_ids']
    if not isinstance(doc_ids, list):
        return jsonify({'error': 'doc_ids must be a list'}), 400

    deleted_count = 0
    for doc_id in doc_ids:
        doc = PatentDocument.query.get(doc_id)
        if doc:
            try:
                # 删除物理文件
                if os.path.exists(doc.original_path):
                    os.remove(doc.original_path)
                for result in doc.results:
                    if result.report_path and os.path.exists(result.report_path):
                        os.remove(result.report_path)
                db.session.delete(doc)
                deleted_count += 1
            except Exception as e:
                current_app.logger.error(f"Error deleting doc {doc_id}: {e}")
    db.session.commit()
    return jsonify({'status': 'success', 'deleted_count': deleted_count})