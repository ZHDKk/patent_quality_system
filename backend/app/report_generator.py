import os
from docx import Document
from docx.shared import Pt, Inches
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from datetime import datetime

def set_table_borders(table):
    """为表格手动添加所有边框（备用方案）"""
    tbl = table._tbl
    for cell in table._cells:
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        for border in ['top', 'left', 'bottom', 'right']:
            tag = f'w:{border}'
            border_elm = OxmlElement(tag)
            border_elm.set(qn('w:val'), 'single')
            border_elm.set(qn('w:sz'), '4')
            border_elm.set(qn('w:space'), '0')
            border_elm.set(qn('w:color'), 'auto')
            tcPr.append(border_elm)

def generate_revised_document(original_path, issues, output_dir):
    """
    在原文档末尾追加质检建议，以表格形式展示
    """
    base = os.path.basename(original_path)
    name, ext = os.path.splitext(base)
    revised_filename = f"{name}_质检结果_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"
    revised_path = os.path.join(output_dir, revised_filename)

    doc = Document(original_path)

    doc.add_page_break()

    p = doc.add_paragraph()
    run = p.add_run('质检修订建议')
    run.bold = True
    run.font.size = Pt(14)

    if issues and len(issues) > 0:
        # 创建表格，先不设置样式
        table = doc.add_table(rows=1, cols=4)
        table.autofit = False

        # 尝试应用内置样式，如果失败则手动添加边框
        try:
            table.style = 'Table Grid'
        except Exception:
            set_table_borders(table)

        # 表头
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = '规则ID'
        hdr_cells[1].text = '问题描述'
        hdr_cells[2].text = '建议'
        hdr_cells[3].text = '严重程度'

        # 表头加粗
        for cell in hdr_cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True

        # 填充数据
        for issue in issues:
            row_cells = table.add_row().cells
            row_cells[0].text = issue.get('rule_id', '')
            row_cells[1].text = issue.get('issue', '')
            row_cells[2].text = issue.get('suggestion', '')
            row_cells[3].text = issue.get('severity', '提示')

        # 可选：调整列宽（取消注释并修改数值）
        # table.columns[0].width = Inches(1.0)
        # table.columns[1].width = Inches(3.0)
        # table.columns[2].width = Inches(3.0)
        # table.columns[3].width = Inches(1.0)
    else:
        doc.add_paragraph('未发现质检问题。')

    doc.save(revised_path)
    return revised_path