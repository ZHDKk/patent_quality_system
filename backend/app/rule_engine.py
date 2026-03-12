import os
import pandas as pd
from cryptography.fernet import Fernet
from datetime import datetime
from .models import db, RuleVersion
from flask import current_app

class RuleEngine:
    def __init__(self, key=None):
        self.key = key or os.environ.get('RULE_ENCRYPT_KEY')
        self.cipher = Fernet(self.key.encode() if isinstance(self.key, str) else self.key)
        self.current_rules = []
        self.current_version_id = None
        self.load_latest_rules()

    def load_latest_rules(self):
        """从数据库加载最新激活的规则版本"""
        latest = RuleVersion.query.filter_by(is_active=True).order_by(RuleVersion.created_at.desc()).first()
        if latest:
            try:
                with open(latest.rules_file_path, 'rb') as f:
                    encrypted = f.read()
                decrypted = self.cipher.decrypt(encrypted)
                temp_path = '/tmp/rules_temp.xlsx'
                with open(temp_path, 'wb') as f:
                    f.write(decrypted)
                df = pd.read_excel(temp_path)
                os.remove(temp_path)

                self.current_rules = df.to_dict('records')
                self.current_version_id = latest.id
            except Exception as e:
                current_app.logger.error(f"Failed to load rules: {e}")
                self.current_rules = []
                self.current_version_id = None
        else:
            self.current_rules = []
            self.current_version_id = None

    def get_system_prompt(self):
        """合并所有规则为 system prompt"""
        prompts = [r.get('prompt_template', '') for r in self.current_rules if r.get('prompt_template')]
        return "\n\n".join(prompts)

    def get_rules_metadata(self):
        """返回规则元数据（不含 prompt_template）"""
        return [{'id': r.get('rule_id'), 'name': r.get('rule_name'), 'severity': r.get('severity')} for r in self.current_rules]

    def update_rules(self, excel_file_path, description, user_id):
        """更新规则：加密并保存为新版本，同时将之前版本设为非激活"""
        # 读取原始 Excel 验证格式
        df = pd.read_excel(excel_file_path)
        required_cols = {'rule_id', 'rule_name', 'description', 'prompt_template', 'severity'}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"Excel must contain columns: {required_cols}")

        # 加密
        with open(excel_file_path, 'rb') as f:
            data = f.read()
        encrypted = self.cipher.encrypt(data)

        # 存储加密文件
        version = f"v{datetime.now().strftime('%Y%m%d%H%M%S')}"
        store_path = os.path.join(current_app.config['RULES_FOLDER'], f"{version}.xlsx.enc")
        with open(store_path, 'wb') as f:
            f.write(encrypted)

        # 创建新规则版本
        new_version = RuleVersion(
            version=version,
            description=description,
            rules_file_path=store_path,
            created_by=user_id,
            is_active=True
        )
        # 将之前的激活版本设为非激活
        RuleVersion.query.filter_by(is_active=True).update({'is_active': False})
        db.session.add(new_version)
        db.session.commit()

        # 重新加载规则
        self.load_latest_rules()
        return new_version