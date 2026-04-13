import os
import pandas as pd
from cryptography.fernet import Fernet
from datetime import datetime
from .models import db, RuleVersion
from flask import current_app

class RuleEngine:
    def __init__(self, key=None, version_id=None):
        self.key = key or os.environ.get('RULE_ENCRYPT_KEY')
        self.cipher = Fernet(self.key.encode() if isinstance(self.key, str) else self.key)
        self.current_rules = []
        self.current_version_id = None
        self.cases = []
        if version_id:
            self.load_rules_by_version(version_id)
        else:
            self.load_latest_rules()

    def load_rules_by_version(self, version_id):
        from .models import RuleVersion
        rule_version = RuleVersion.query.get(version_id)
        if not rule_version:
            raise ValueError(f"规则版本 {version_id} 不存在")

        try:
            with open(rule_version.rules_file_path, 'rb') as f:
                encrypted = f.read()
            decrypted = self.cipher.decrypt(encrypted)
            temp_path = './rules_temp.xlsx'
            with open(temp_path, 'wb') as f:
                f.write(decrypted)

            excel_file = pd.ExcelFile(temp_path)
            if '规则库' in excel_file.sheet_names:
                df_rules = pd.read_excel(temp_path, sheet_name='规则库')
                self.current_rules = df_rules.to_dict('records')
            else:
                self.current_rules = []

            if '案例库' in excel_file.sheet_names:
                df_cases = pd.read_excel(temp_path, sheet_name='案例库')
                self.cases = df_cases.to_dict('records')
            else:
                self.cases = []

            os.remove(temp_path)
            self.current_version_id = rule_version.id
        except Exception as e:
            current_app.logger.error(f"加载规则版本 {version_id} 失败: {e}")
            self.current_rules = []
            self.cases = []
            self.current_version_id = None

    def load_latest_rules(self):
        latest = RuleVersion.query.filter_by(is_active=True).order_by(RuleVersion.created_at.desc()).first()
        if latest:
            try:
                with open(latest.rules_file_path, 'rb') as f:
                    encrypted = f.read()
                decrypted = self.cipher.decrypt(encrypted)
                temp_path = './rules_temp.xlsx'
                with open(temp_path, 'wb') as f:
                    f.write(decrypted)

                excel_file = pd.ExcelFile(temp_path)
                if '规则库' in excel_file.sheet_names:
                    df_rules = pd.read_excel(temp_path, sheet_name='规则库')
                    self.current_rules = df_rules.to_dict('records')
                else:
                    self.current_rules = []

                if '案例库' in excel_file.sheet_names:
                    df_cases = pd.read_excel(temp_path, sheet_name='案例库')
                    self.cases = df_cases.to_dict('records')
                else:
                    self.cases = []

                os.remove(temp_path)
                self.current_version_id = latest.id

            except Exception as e:
                current_app.logger.error(f"Failed to load rules: {e}")
                self.current_rules = []
                self.cases = []
                self.current_version_id = None
        else:
            self.current_rules = []
            self.cases = []
            self.current_version_id = None

    def get_system_prompt(self):
        prompt_parts = ["你是一个专利质检专家，请根据以下规则检查用户提供的专利文档，并指出不符合规则的具体问题。"]

        if self.current_rules:
            prompt_parts.append("\n【质检规则】")
            for idx, rule in enumerate(self.current_rules, 1):
                rule_id = rule.get('规则ID', f'规则{idx}')
                category = rule.get('规则类别', '')
                target = rule.get('检查对象', '')
                error_pattern = rule.get('错误模式（关键词）', '')
                correct_pattern = rule.get('正确模式', '')
                rule_text = (
                    f"规则 {rule_id}（{category}，检查对象：{target}）：\n"
                    f"  错误模式：{error_pattern}\n"
                    f"  正确模式：{correct_pattern}\n"
                )
                prompt_parts.append(rule_text)
        else:
            prompt_parts.append("当前没有加载任何质检规则。")

        if self.cases:
            prompt_parts.append("\n【参考示例】")
            for case in self.cases:
                case_id = case.get('案例ID', '')
                case_type = case.get('类型', '')
                title = case.get('标题', '')
                content = case.get('内容摘要', '')
                involved_rules = case.get('涉及规则ID', '')
                case_text = (
                    f"示例 {case_id}（{case_type}）：{title}\n"
                    f"内容：{content}\n"
                    f"涉及规则：{involved_rules}\n"
                )
                prompt_parts.append(case_text)

        prompt_parts.append(
            "\n请以JSON格式输出结果，包含字段：\n"
            "- rule_id: 违反的规则ID\n"
            "- issue: 问题描述\n"
            "- suggestion: 修改建议\n"
            "- severity: 严重程度（可选项：错误/警告/提示）\n"
            "如果没有发现问题，返回空数组 []。"
        )

        return "\n".join(prompt_parts)

    def get_rules_metadata(self):
        meta = []
        for rule in self.current_rules:
            meta.append({
                'id': rule.get('规则ID', ''),
                'category': rule.get('规则类别', ''),
                'target': rule.get('检查对象', ''),
                'error_pattern': rule.get('错误模式（关键词）', ''),
                'correct_pattern': rule.get('正确模式', '')
            })
        return meta

    def update_rules(self, excel_file_path, description, user_id, rule_name='', model='kimi-k2-turbo-preview'):
        excel_file = pd.ExcelFile(excel_file_path)
        if '规则库' not in excel_file.sheet_names:
            raise ValueError("Excel 文件中必须包含名为“规则库”的 sheet")

        df_rules = pd.read_excel(excel_file_path, sheet_name='规则库')
        required_cols = {'规则ID', '规则类别', '检查对象', '错误模式（关键词）', '正确模式'}
        if not required_cols.issubset(df_rules.columns):
            raise ValueError(f"规则库 sheet 必须包含列: {required_cols}")

        with open(excel_file_path, 'rb') as f:
            data = f.read()
        encrypted = self.cipher.encrypt(data)

        version = f"v{datetime.now().strftime('%Y%m%d%H%M%S')}"
        store_path = os.path.join(current_app.config['RULES_FOLDER'], f"{version}.xlsx.enc")
        with open(store_path, 'wb') as f:
            f.write(encrypted)

        new_version = RuleVersion(
            version=version,
            name=rule_name,
            description=description,
            rules_file_path=store_path,
            created_by=user_id,
            is_active=True,
            model=model
        )
        RuleVersion.query.filter_by(is_active=True).update({'is_active': False})
        db.session.add(new_version)
        db.session.commit()

        self.load_latest_rules()
        return new_version