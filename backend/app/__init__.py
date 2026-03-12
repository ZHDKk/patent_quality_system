import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from celery import Celery
from .models import db
from .auth import auth_bp
from .routes import main_bp

# 初始化扩展
login_manager = LoginManager()
migrate = Migrate()
celery = Celery(__name__, broker=os.environ.get('REDIS_URL', 'redis://redis:6379/0'))

import os
print("DB_PASSWORD from env:", os.environ.get('DB_PASSWORD'))
print("All env keys:", list(os.environ.keys()))

def create_app(config_object=None):
    # 初始化 Flask 应用，指定模板和静态文件路径
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    TEMPLATE_DIR = os.path.join(BASE_DIR, 'frontend/templates')
    STATIC_DIR = os.path.join(BASE_DIR, 'frontend/static')

    # 调试：打印最终模板路径（可选，确认路径正确）
    print(f"模板文件夹路径：{TEMPLATE_DIR}")
    print(f"模板文件夹是否存在：{os.path.exists(TEMPLATE_DIR)}")
    print(f"login.html 是否存在：{os.path.exists(os.path.join(TEMPLATE_DIR, 'login.html'))}")

    # 初始化 Flask 应用（使用正确的模板路径）
    app = Flask(
        __name__,
        template_folder=TEMPLATE_DIR,  # 修正后的绝对路径
        static_folder=STATIC_DIR  # 静态文件路径同步修正
    )

    # 加载配置
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    # 如果环境变量 DB_HOST 不存在，则使用 SQLite
    if os.environ.get('DB_HOST'):
        app.config[
            'SQLALCHEMY_DATABASE_URI'] = f"mysql+pymysql://root:{os.environ.get('DB_PASSWORD')}@{os.environ.get('DB_HOST', 'mysql')}/patent_quality"
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///patent_quality.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', '/app/uploads')
    app.config['RULES_FOLDER'] = os.environ.get('RULES_FOLDER', '/app/rules')
    app.config['REPORTS_FOLDER'] = os.environ.get('REPORTS_FOLDER', '/app/reports')
    app.config['KIMI_API_KEY'] = os.environ.get('KIMI_API_KEY')
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

    # 初始化扩展
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    migrate.init_app(app, db)

    # 注册蓝图
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp, url_prefix='/')

    # 配置 Celery
    celery.conf.update(app.config)

    # 创建上传等目录
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['RULES_FOLDER'], exist_ok=True)
    os.makedirs(app.config['REPORTS_FOLDER'], exist_ok=True)

    return app


@login_manager.user_loader
def load_user(user_id):
    from .models import User
    return User.query.get(int(user_id))