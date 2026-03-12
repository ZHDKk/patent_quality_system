import os
import json
from docx import Document
from docx.shared import RGBColor, Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from datetime import datetime

def generate_report(original_path, result_json):
    """
    生成带有批注或修订的 Word 质检报告
    返回报告文件路径
    """
    # 仅支持 .docx，如果是 .doc 需转换，这里简化
    if not original_path.endswith('.docx'):
        # 可以调用工具转换，但这里简单复制原文件并加批注
        # 实际可调用 unoconv 或 pandoc
        # 这里假设输入为 docx
        pass

    doc = Document(original_path)

    # 开启修订模式
    try:
        part = doc.part
        settings_part = part.part_related_by_reltype(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings")
        settings_el = settings_part.element
        tracking_el = OxmlElement('w:trackRevisions')
        tracking_el.set(qn('w:val'), 'true')
        settings_el.append(tracking_el)
    except:
        pass  # 如果设置失败，忽略

    # 解析 result_json 中的问题列表
    issues = result_json.get('issues', [])
    if not issues:
        # 如果没有结构化问题，尝试从 raw_output 解析
        raw = result_json.get('raw_output', '')
        # 这里简化：将整个 AI 输出作为一个批注添加到文档末尾
        para = doc.add_paragraph()
        run = para.add_run("质检报告：")
        run.bold = True
        para.add_run(raw)
    else:
        for issue in issues:
            # 在每个段落添加批注（需要定位具体位置，简化：在文档末尾添加）
            para = doc.add_paragraph()
            comment_text = f"【{issue.get('severity','提示')}】{issue.get('description','')}\n建议：{issue.get('suggestion','')}"
            comment = para.add_comment(comment_text, author='质检系统', initials='QC')
            comment.text = comment_text

    # 保存报告
    base, ext = os.path.splitext(original_path)
    report_path = base + f"_质检报告_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"
    doc.save(report_path)
    return report_path