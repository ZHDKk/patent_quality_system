import os
import json
import pandas as pd
import tempfile
from pathlib import Path

# 确保 Python 能找到 backend 模块
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.document_parser import DocumentParser
from backend.app.ai_service import KimiAIService


def load_rules_from_excel(rule_file_path: str, key: str = None) -> str:
    """
    从规则 Excel 文件加载规则和案例，生成 system prompt。
    如果文件是加密的（.enc），则先解密；否则直接读取。
    """
    is_temp = False

    # 解密（如果需要）
    if rule_file_path.endswith('.enc'):
        if not key:
            raise ValueError("加密文件需要提供解密密钥")
        from cryptography.fernet import Fernet
        cipher = Fernet(key.encode())
        with open(rule_file_path, 'rb') as f:
            encrypted = f.read()
        decrypted = cipher.decrypt(encrypted)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            tmp.write(decrypted)
            rule_file_path = tmp.name
        is_temp = True

    # 读取 Excel
    excel_file = pd.ExcelFile(rule_file_path)
    prompt_parts = ["你是一个专利质检专家，请根据以下规则检查用户提供的专利文档，并指出不符合规则的具体问题。"]

    # 规则库
    if '规则库' in excel_file.sheet_names:
        df_rules = pd.read_excel(rule_file_path, sheet_name='规则库')
        prompt_parts.append("\n【质检规则】")
        for idx, row in df_rules.iterrows():
            rule_id = row.get('规则ID', f'规则{idx+1}')
            category = row.get('规则类别', '')
            target = row.get('检查对象', '')
            error_pattern = row.get('错误模式（关键词）', '')
            correct_pattern = row.get('正确模式', '')
            rule_text = (
                f"规则 {rule_id}（{category}，检查对象：{target}）：\n"
                f"  错误模式：{error_pattern}\n"
                f"  正确模式：{correct_pattern}\n"
            )
            prompt_parts.append(rule_text)

    # 案例库
    if '案例库' in excel_file.sheet_names:
        df_cases = pd.read_excel(rule_file_path, sheet_name='案例库')
        prompt_parts.append("\n【参考示例】")
        for _, row in df_cases.iterrows():
            case_id = row.get('案例ID', '')
            case_type = row.get('类型', '')
            title = row.get('标题', '')
            content = row.get('内容摘要', '')
            involved_rules = row.get('涉及规则ID', '')
            case_text = (
                f"示例 {case_id}（{case_type}）：{title}\n"
                f"内容：{content}\n"
                f"涉及规则：{involved_rules}\n"
            )
            prompt_parts.append(case_text)

    # 输出格式要求
    prompt_parts.append(
        "\n请以JSON格式输出结果，包含字段：\n"
        "- rule_id: 违反的规则ID\n"
        "- issue: 问题描述\n"
        "- suggestion: 修改建议\n"
        "- severity: 严重程度（可选项：错误/警告/提示）\n"
        "如果没有发现问题，返回空数组 []。"
    )

    # 清理临时文件
    if is_temp:
        os.unlink(rule_file_path)

    return "\n".join(prompt_parts)


def test_text_interface():
    """测试纯文本接口（本地解析 + AI 纯文本对话）"""
    print("\n========== 测试纯文本接口 ==========")

    # 配置
    KIMI_API_KEY = "sk-AZAyCMr4v499vZplgG9xR8xv0Llebp6XoVeT8LG8D6lJiWWo"
    RULE_FILE = "D:\\pro\\pro\\other_pro\\python\\patent_quality_system\\backend\\app\\rules_temp.xlsx"  # 如果加密则用 ".enc" 文件
    RULE_ENCRYPT_KEY = "YfPqwB4m6T6tt9n6Xoi1WfI25AJJPB5ZYiqXb4HrtmU="
    PATENT_FILE = "D:\\pro\\pro\\other_pro\\python\\patent_quality_system\\zhuanli.docx"
    MODEL = "kimi-k2-turbo-preview"

    # 1. 加载规则
    print("加载规则文件...")
    system_prompt = load_rules_from_excel(RULE_FILE, RULE_ENCRYPT_KEY if RULE_FILE.endswith('.enc') else None)
    print("规则加载完成。")

    # 2. 解析专利文档
    print("解析专利文档...")
    parser = DocumentParser()
    parsed = parser.parse(PATENT_FILE)
    doc_text = parsed.get('text', '')
    print(f"文档解析完成，文本长度: {len(doc_text)} 字符")
    print(f"表格数量: {len(parsed.get('tables', []))}")
    print(f"图片数量: {len(parsed.get('images', []))}")

    # 3. 调用 AI
    print("调用 Kimi 纯文本接口...")
    ai = KimiAIService(KIMI_API_KEY)
    ai_result_text = ai.call_with_text(system_prompt, doc_text, model=MODEL)

    # 4. 输出结果
    try:
        issues = json.loads(ai_result_text)
        if not isinstance(issues, list):
            issues = []
        ai_result = {'issues': issues, 'raw_output': ai_result_text}
        print("\n===== 质检结果 =====")
        print(json.dumps(ai_result, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("\n===== 原始返回（非 JSON）=====")
        print(ai_result_text)


def test_file_interface():
    """测试文件接口（上传规则和专利文档，由 Kimi 直接解析）"""
    print("\n========== 测试文件接口 ==========")

    # 配置
    KIMI_API_KEY = "sk-AZAyCMr4v499vZplgG9xR8xv0Llebp6XoVeT8LG8D6lJiWWo"
    RULE_FILE = "D:\\pro\\pro\\other_pro\\python\\patent_quality_system\\backend\\app\\rules_temp.xlsx"  # 如果加密则用 ".enc" 文件
    RULE_ENCRYPT_KEY = "YfPqwB4m6T6tt9n6Xoi1WfI25AJJPB5ZYiqXb4HrtmU="
    PATENT_FILE = "D:\\pro\\pro\\other_pro\\python\\patent_quality_system\\zhuanli.docx"
    MODEL = "kimi-k2-turbo-preview"

    # 如果规则文件是加密的，先解密为临时文件
    rule_file_to_upload = RULE_FILE
    is_temp = False
    if RULE_FILE.endswith('.enc'):
        from cryptography.fernet import Fernet
        cipher = Fernet(RULE_ENCRYPT_KEY.encode())
        with open(RULE_FILE, 'rb') as f:
            encrypted = f.read()
        decrypted = cipher.decrypt(encrypted)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            tmp.write(decrypted)
            rule_file_to_upload = tmp.name
        is_temp = True
        print("规则文件已解密为临时文件。")

    # 调用文件接口
    print("上传文件并调用 Kimi 文件接口...")
    ai = KimiAIService(KIMI_API_KEY)
    result_dict = ai.call_with_files(rule_file_to_upload, PATENT_FILE, model=MODEL)

    # 清理临时规则文件
    if is_temp:
        os.unlink(rule_file_to_upload)
        print("临时规则文件已清理。")

    # 输出结果
    ai_result_text = result_dict['result']
    doc_content = result_dict['doc_content']
    print(f"Kimi 返回的文档内容长度: {len(doc_content)} 字符")

    try:
        issues = json.loads(ai_result_text)
        if not isinstance(issues, list):
            issues = []
        ai_result = {'issues': issues, 'raw_output': ai_result_text}
        print("\n===== 质检结果 =====")
        print(json.dumps(ai_result, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("\n===== 原始返回（非 JSON）=====")
        print(ai_result_text)


if __name__ == "__main__":
    # 可以选择执行其中一个测试
    test_text_interface()   # 测试纯文本接口
    # test_file_interface()   # 测试文件接口