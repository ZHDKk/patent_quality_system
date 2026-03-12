import json
from flask import request
from .models import db, OperationLog
from functools import wraps

def log_operation(action):
    """装饰器：记录用户操作日志"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 执行原函数
            resp = f(*args, **kwargs)
            # 记录日志
            from flask_login import current_user
            if current_user.is_authenticated:
                log = OperationLog(
                    user_id=current_user.id,
                    action=action,
                    details=json.dumps(request.get_json() if request.is_json else request.form.to_dict()),
                    ip_address=request.remote_addr
                )
                db.session.add(log)
                db.session.commit()
            return resp
        return decorated_function
    return decorator