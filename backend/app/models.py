from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='employee')  # admin, employee
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username}>'

class OperationLog(db.Model):
    __tablename__ = 'operation_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(200))
    details = db.Column(db.Text)          # JSON格式
    ip_address = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='logs')

class PatentDocument(db.Model):
    __tablename__ = 'patent_documents'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255))
    original_path = db.Column(db.String(500))
    parsed_json = db.Column(db.Text().with_variant(db.Text(length=2**32-1), 'mysql'), nullable=True)      # 解析后的结构化内容（JSON）
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, failed

    uploader = db.relationship('User', backref='documents')
    results = db.relationship('QualityCheckResult', backref='document', cascade='all, delete-orphan')

class QualityCheckResult(db.Model):
    __tablename__ = 'quality_check_results'
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('patent_documents.id'))
    version = db.Column(db.Integer, default=1)
    parent_result_id = db.Column(db.Integer, db.ForeignKey('quality_check_results.id'), nullable=True)  # 添加外键
    rule_version_id = db.Column(db.Integer, db.ForeignKey('rule_versions.id'))
    result_json = db.Column(db.Text)
    report_path = db.Column(db.String(500))
    check_time = db.Column(db.DateTime, default=datetime.utcnow)

    # 自关联关系（remote_side 指明哪一端是“父”）
    parent = db.relationship('QualityCheckResult', remote_side=[id], backref='children')

class RuleVersion(db.Model):
    __tablename__ = 'rule_versions'
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.String(50), unique=True)
    description = db.Column(db.String(200))
    rules_file_path = db.Column(db.String(500))   # 加密文件存储路径
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    creator = db.relationship('User', backref='rule_versions')