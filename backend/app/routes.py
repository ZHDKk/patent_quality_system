import os
import json
import subprocess
import tempfile
import uuid

from flask import Blueprint, request, jsonify, render_template, current_app, flash, redirect, url_for, make_response, \
    send_file
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
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
AVAILABLE_MODELS = [  # 可用模型列表
    ('kimi-k2.5', 'Kimi k2.5'),
    ('kimi-k2-0905-preview', 'Kimi k2 0905 Preview'),
    ('kimi-k2-turbo-preview', 'Kimi k2 Turbo Preview'),
    ('kimi-k2-thinking', 'Kimi k2 Thinking'),
    ('kimi-k2-thinking-turbo', 'Kimi k2 Thinking Turbo'),
]

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
        try:
            if 'file' not in request.files:
                return jsonify({'error': 'No file part'}), 400
            file = request.files['file']
            if file.filename == '':
                return jsonify({'error': 'No selected file'}), 400
            if file and allowed_file(file.filename):
                original_filename = file.filename
                ext = os.path.splitext(original_filename)[1].lower()
                safe_filename = str(uuid.uuid4()) + ext
                file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)
                file.save(file_path)

                doc = PatentDocument(
                    filename=original_filename,
                    original_path=file_path,
                    uploader_id=current_user.id
                )
                db.session.add(doc)
                db.session.commit()

                is_recheck = request.form.get('is_recheck') == 'yes'
                parent_id = request.form.get('parent_result_id')
                parse_mode = request.form.get('parse_mode', 'local')
                rule_version_id = request.form.get('rule_version_id')
                user_selected_model = request.form.get('model')
                text_only = request.form.get('text_only', 'no') == 'yes'  # 新增：纯文本模式标志

                # 确定使用的模型
                if rule_version_id:
                    rule_version = RuleVersion.query.get(rule_version_id)
                    if not rule_version:
                        return jsonify({'error': '无效的规则版本'}), 400
                    if current_user.has_permission('choose_model') and user_selected_model:
                        model = user_selected_model
                    else:
                        model = rule_version.model
                else:
                    rule_version = RuleVersion.query.filter_by(is_active=True).order_by(RuleVersion.created_at.desc()).first()
                    if rule_version:
                        rule_version_id = rule_version.id
                        if current_user.has_permission('choose_model') and user_selected_model:
                            model = user_selected_model
                        else:
                            model = rule_version.model
                    else:
                        model = user_selected_model if (current_user.has_permission('choose_model') and user_selected_model) else 'kimi-k2-turbo-preview'

                process_patent_document.delay(
                    doc.id, is_recheck, parent_id, parse_mode, model, rule_version_id, text_only  # 传递 text_only
                )

                return jsonify({'status': 'success', 'doc_id': doc.id})
            else:
                return jsonify({'error': 'File type not allowed'}), 400
        except Exception as e:
            current_app.logger.error(f"Upload error for user {current_user.id}: {e}", exc_info=True)
            db.session.rollback()
            return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

    recent_docs = PatentDocument.query.filter_by(uploader_id=current_user.id).order_by(PatentDocument.upload_time.desc()).limit(10).all()
    return render_template('upload.html', recent_docs=recent_docs, available_models=AVAILABLE_MODELS)


@main_bp.route('/batch_upload', methods=['POST'])
@login_required
@log_operation('batch_upload')
def batch_upload():
    try:
        files = request.files.getlist('files')
        if not files:
            return jsonify({'error': 'No files'}), 400

        parse_mode = request.form.get('parse_mode', 'local')
        user_selected_model = request.form.get('model')
        rule_version_id = request.form.get('rule_version_id')
        text_only = request.form.get('text_only', 'no') == 'yes'  # 新增

        if rule_version_id:
            rule_version = RuleVersion.query.get(rule_version_id)
            if not rule_version:
                return jsonify({'error': '无效的规则版本'}), 400
            if current_user.has_permission('choose_model') and user_selected_model:
                model = user_selected_model
            else:
                model = rule_version.model
        else:
            rule_version = RuleVersion.query.filter_by(is_active=True).order_by(RuleVersion.created_at.desc()).first()
            if rule_version:
                rule_version_id = rule_version.id
                if current_user.has_permission('choose_model') and user_selected_model:
                    model = user_selected_model
                else:
                    model = rule_version.model
            else:
                model = user_selected_model if (current_user.has_permission('choose_model') and user_selected_model) else 'kimi-k2-turbo-preview'

        doc_ids = []
        failed_files = []

        for file in files:
            if not file or not allowed_file(file.filename):
                failed_files.append({'name': file.filename, 'reason': '文件类型不允许'})
                continue

            original_filename = file.filename
            ext = os.path.splitext(original_filename)[1].lower()
            safe_filename = str(uuid.uuid4()) + ext
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)

            try:
                file.save(file_path)
            except Exception as e:
                failed_files.append({'name': original_filename, 'reason': f'保存失败: {str(e)}'})
                continue

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
            process_patent_document.delay(doc_id, False, None, parse_mode, model, rule_version_id, text_only)

        return jsonify({
            'status': 'success',
            'doc_ids': doc_ids,
            'count': len(doc_ids),
            'failed': failed_files
        })
    except Exception as e:
        current_app.logger.error(f"Batch upload error for user {current_user.id}: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

@main_bp.route('/results')
@login_required
def results():
    page = request.args.get('page', 1, type=int)
    per_page = 30
    query = PatentDocument.query.filter_by(uploader_id=current_user.id).order_by(PatentDocument.upload_time.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    docs = pagination.items
    for doc in docs:
        if doc.results:
            doc.latest_result = doc.results[-1]
        else:
            doc.latest_result = None
    return render_template('results.html', docs=docs, pagination=pagination)

@main_bp.route('/result/<int:doc_id>')
@login_required
def view_result(doc_id):
    doc = PatentDocument.query.get_or_404(doc_id)
    if doc.uploader_id != current_user.id and current_user.role != 'admin':
        flash('Access denied')
        return redirect(url_for('main.results'))

    results_objs = QualityCheckResult.query.filter_by(document_id=doc_id).order_by(QualityCheckResult.version).all()
    results_data = []
    for res in results_objs:
        try:
            result_content = json.loads(res.result_json) if res.result_json else {}
        except:
            result_content = {"raw_output": res.result_json}
        results_data.append({
            'id': res.id,
            'version': res.version,
            'check_time': res.check_time.isoformat(),
            'result_json': result_content,
            'revised_doc_path': res.revised_doc_path,
            'rule_name': res.rule_version.name if res.rule_version else ''
        })

    view_user = None
    if current_user.role == 'admin' and doc.uploader_id != current_user.id:
        view_user = doc.uploader

    return render_template('result_detail.html', doc=doc, results=results_data, view_user=view_user)

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
            rule_name = request.form.get('rule_name', '')
            model = request.form.get('model', 'kimi-k2-turbo-preview')  # 获取选择的模型
            engine = RuleEngine()
            try:
                engine.update_rules(temp_path, description, current_user.id, rule_name, model)
                flash('规则已更新')
            except Exception as e:
                flash(f'更新失败: {str(e)}')
            return redirect(url_for('main.manage_rules'))
        else:
            flash('请上传 .xlsx 文件')

    versions = RuleVersion.query.order_by(RuleVersion.created_at.desc()).all()
    return render_template('manage_rules.html', versions=versions, available_models=AVAILABLE_MODELS)

@main_bp.route('/admin/rules/update_model/<int:version_id>', methods=['POST'])
@login_required
@admin_required
def update_rule_model(version_id):
    """更新规则版本的模型"""
    rule = RuleVersion.query.get_or_404(version_id)
    data = request.get_json()
    new_model = data.get('model')
    if not new_model:
        return jsonify({'error': '缺少 model 参数'}), 400
    # 可选的模型校验
    valid_models = [m[0] for m in AVAILABLE_MODELS]
    if new_model not in valid_models:
        return jsonify({'error': '无效的模型'}), 400
    rule.model = new_model
    db.session.commit()
    return jsonify({'status': 'success'})

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

@main_bp.route('/api/documents/status', methods=['POST'])
@login_required
def documents_status():
    data = request.get_json()
    doc_ids = data.get('doc_ids', [])
    if not doc_ids:
        return jsonify({})
    docs = PatentDocument.query.filter(
        PatentDocument.id.in_(doc_ids),
        PatentDocument.uploader_id == current_user.id
    ).all()
    return jsonify({doc.id: doc.status for doc in docs})

@main_bp.route('/admin/rules/download/<int:version_id>')
@login_required
@admin_required
def download_rule(version_id):
    from cryptography.fernet import Fernet
    rule = RuleVersion.query.get_or_404(version_id)
    key = os.environ.get('RULE_ENCRYPT_KEY')
    cipher = Fernet(key.encode() if isinstance(key, str) else key)
    with open(rule.rules_file_path, 'rb') as f:
        encrypted = f.read()
    decrypted = cipher.decrypt(encrypted)
    response = make_response(decrypted)
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename={rule.version}.xlsx'
    return response

@main_bp.route('/admin/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        permissions = request.form.getlist('permissions')
        user.permissions = permissions
        db.session.commit()
        flash('用户权限更新成功')
        return redirect(url_for('main.manage_users'))
    available_permissions = [
        {'id': 'upload', 'name': '上传文档'},
        {'id': 'view_results', 'name': '查看结果'},
        {'id': 'manage_rules', 'name': '管理规则'},
        {'id': 'manage_users', 'name': '管理用户'},
        {'id': 'choose_model', 'name': '选择AI模型'}
    ]
    return render_template('edit_user.html', user=user, permissions=available_permissions)

@main_bp.route('/admin/user/<int:user_id>/results')
@login_required
@admin_required
def user_results(user_id):
    user = User.query.get_or_404(user_id)
    page = request.args.get('page', 1, type=int)
    per_page = 30
    query = PatentDocument.query.filter_by(uploader_id=user.id).order_by(PatentDocument.upload_time.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    docs = pagination.items
    return render_template('results.html', docs=docs, pagination=pagination, view_user=user)

@main_bp.route('/api/user/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': '不能删除自己'}), 400
    db.session.delete(user)
    db.session.commit()
    return jsonify({'status': 'success'})

from .report_generator import generate_revised_document

def convert_doc_to_docx(doc_path):
    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
        output_path = tmp.name
    cmd = [
        'soffice',
        '--headless',
        '--convert-to', 'docx',
        '--outdir', os.path.dirname(output_path),
        doc_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        base_name = os.path.splitext(os.path.basename(doc_path))[0]
        converted = os.path.join(os.path.dirname(output_path), base_name + '.docx')
        if os.path.exists(converted):
            return converted
        else:
            raise Exception("转换后文件未找到")
    except Exception as e:
        if os.path.exists(output_path):
            os.unlink(output_path)
        raise

@main_bp.route('/api/result/<int:result_id>/generate_revised', methods=['POST'])
@login_required
def generate_revised(result_id):
    result = QualityCheckResult.query.get_or_404(result_id)
    doc = result.document
    if doc.uploader_id != current_user.id and current_user.role != 'admin':
        return jsonify({'error': 'Forbidden'}), 403

    if result.revised_doc_path and os.path.exists(result.revised_doc_path):
        return jsonify({'status': 'success', 'message': '已存在'})

    original_path = doc.original_path
    ext = os.path.splitext(original_path)[1].lower()
    need_cleanup = False
    if ext == '.doc':
        try:
            original_path = convert_doc_to_docx(original_path)
            need_cleanup = True
        except Exception as e:
            return jsonify({'error': f'转换 .doc 文件失败: {e}'}), 500

    try:
        result_json = json.loads(result.result_json)
        issues = result_json.get('issues', [])
        revised_path = generate_revised_document(
            original_path,
            issues,
            current_app.config['REPORTS_FOLDER']
        )
        result.revised_doc_path = revised_path
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        current_app.logger.error(f"生成修订版文档失败: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if need_cleanup and os.path.exists(original_path):
            os.unlink(original_path)

@main_bp.route('/download/revised/<int:result_id>')
@login_required
def download_revised(result_id):
    result = QualityCheckResult.query.get_or_404(result_id)
    doc = result.document
    if doc.uploader_id != current_user.id and current_user.role != 'admin':
        flash('Access denied')
        return redirect(url_for('main.results'))
    if not result.revised_doc_path or not os.path.exists(result.revised_doc_path):
        flash('修订版文档不存在')
        return redirect(url_for('main.view_result', doc_id=doc.id))
    return send_file(result.revised_doc_path, as_attachment=True, download_name=f'report_{doc.filename}')

@main_bp.route('/admin/rules/delete/<int:version_id>', methods=['POST'])
@login_required
@admin_required
def delete_rule_version(version_id):
    rule = RuleVersion.query.get_or_404(version_id)

    count = RuleVersion.query.count()
    if count <= 1:
        flash('至少保留一个规则版本，无法删除', 'error')
        return redirect(url_for('main.manage_rules'))

    if QualityCheckResult.query.filter_by(rule_version_id=version_id).first():
        flash('该规则版本已被质检结果引用，无法删除', 'error')
        return redirect(url_for('main.manage_rules'))

    try:
        if os.path.exists(rule.rules_file_path):
            os.remove(rule.rules_file_path)
        db.session.delete(rule)
        db.session.commit()
        flash('规则版本已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'error')

    return redirect(url_for('main.manage_rules'))

@main_bp.route('/api/rule_versions')
@login_required
def api_rule_versions():
    versions = RuleVersion.query.order_by(RuleVersion.created_at.desc()).all()
    data = [{
        'id': v.id,
        'version': v.version,
        'description': v.description,
        'created_at': v.created_at.isoformat(),
        'is_active': v.is_active,
        'model': v.model
    } for v in versions]
    return jsonify(data)

@main_bp.route('/api/user/<int:user_id>/reset_password', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    new_password = data.get('password')
    if not new_password:
        return jsonify({'error': '密码不能为空'}), 400
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    return jsonify({'status': 'success'})