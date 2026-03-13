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
        self.cases = []  # 存储案例库
        self.load_latest_rules()

    def load_latest_rules(self):
        """从数据库加载最新激活的规则版本（包含规则库和案例库）"""
        latest = RuleVersion.query.filter_by(is_active=True).order_by(RuleVersion.created_at.desc()).first()
        if latest:
            try:
                with open(latest.rules_file_path, 'rb') as f:
                    encrypted = f.read()
                decrypted = self.cipher.decrypt(encrypted)
                temp_path = './rules_temp.xlsx'
                with open(temp_path, 'wb') as f:
                    f.write(decrypted)

                # 读取所有 sheet
                excel_file = pd.ExcelFile(temp_path)
                # 规则库 sheet（假设名称为“规则库”）
                if '规则库' in excel_file.sheet_names:
                    df_rules = pd.read_excel(temp_path, sheet_name='规则库')
                    # 转换为字典列表，保留原始列名
                    self.current_rules = df_rules.to_dict('records')
                else:
                    self.current_rules = []

                # 案例库 sheet（假设名称为“案例库”）
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
        """
        将规则库和案例库合并为 system prompt
        格式：
        你是一个专利质检专家，请根据以下规则检查专利文档，并指出不符合规则的具体问题。
        每条规则包含：规则ID、类别、检查对象、错误模式、正确模式。
        同时提供一些示例供参考。
        """
        prompt_parts = ["你是一个专利质检专家，请根据以下规则检查用户提供的专利文档，并指出不符合规则的具体问题。"]

        # 添加规则列表
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

        # 添加案例库（作为 few-shot 示例）
        if self.cases:
            prompt_parts.append("\n【参考示例】")
            for case in self.cases:
                case_id = case.get('案例ID', '')
                case_type = case.get('类型', '')  # 正面/负面
                title = case.get('标题', '')
                content = case.get('内容摘要', '')
                involved_rules = case.get('涉及规则ID', '')
                case_text = (
                    f"示例 {case_id}（{case_type}）：{title}\n"
                    f"内容：{content}\n"
                    f"涉及规则：{involved_rules}\n"
                )
                prompt_parts.append(case_text)

        # 要求输出格式
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
        """返回规则元数据，用于前端展示（不包含完整prompt）"""
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

    def update_rules(self, excel_file_path, description, user_id):
        """更新规则：加密并保存为新版本，同时将之前版本设为非激活"""
        # 读取原始 Excel 验证格式（至少要有“规则库”sheet）
        excel_file = pd.ExcelFile(excel_file_path)
        if '规则库' not in excel_file.sheet_names:
            raise ValueError("Excel 文件中必须包含名为“规则库”的 sheet")

        df_rules = pd.read_excel(excel_file_path, sheet_name='规则库')
        required_cols = {'规则ID', '规则类别', '检查对象', '错误模式（关键词）', '正确模式'}
        if not required_cols.issubset(df_rules.columns):
            raise ValueError(f"规则库 sheet 必须包含列: {required_cols}")

        # 案例库 sheet 可选，不验证列
        # 加密整个文件
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