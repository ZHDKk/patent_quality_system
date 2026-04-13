from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .models import db, User, OperationLog
from datetime import datetime

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            log = OperationLog(
                user_id=user.id,
                action='login',
                details='User logged in',
                ip_address=request.remote_addr
            )
            db.session.add(log)
            db.session.commit()
            return redirect(url_for('main.index'))
        else:
            flash('Invalid username or password')
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if current_user.role != 'admin':
        flash('Access denied')
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form.get('role', 'employee')
        permissions = request.form.getlist('permissions')
        if not permissions:
            permissions = ['upload', 'view_results']
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('auth.register'))
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            permissions=permissions
        )
        db.session.add(user)
        db.session.commit()
        flash('User created successfully')
        return redirect(url_for('main.manage_users'))
    available_permissions = [
        {'id': 'upload', 'name': '上传文档'},
        {'id': 'view_results', 'name': '查看结果'},
        {'id': 'manage_rules', 'name': '管理规则'},
        {'id': 'manage_users', 'name': '管理用户'},
        {'id': 'choose_model', 'name': '选择AI模型'}  # 新增权限
    ]
    return render_template('register.html', permissions=available_permissions)