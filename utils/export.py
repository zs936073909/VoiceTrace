import csv
import json
from pathlib import Path
from typing import List, Dict, Any


def export_csv(data: List[Dict[str, Any]], output_path: Path) -> bool:
    """Export list of dicts to CSV file."""
    if not data:
        return False
    try:
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return True
    except (IOError, OSError) as e:
        print(f"Export CSV error: {e}")
        return False


def export_json(data: Any, output_path: Path) -> bool:
    """Export data to JSON file."""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, OSError, TypeError) as e:
        print(f"Export JSON error: {e}")
        return False


def export_pdf(data: List[Dict[str, Any]], output_path: Path, title: str = "VoiceTrace 报告") -> bool:
    """Export data to a simple PDF report."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os

        # 注册中文字体
        font_name = "Helvetica"
        font_paths = [
            ("SimSun", "C:/Windows/Fonts/simsun.ttc"),
            ("MSYH", "C:/Windows/Fonts/msyh.ttc"),
            ("SimHei", "C:/Windows/Fonts/simhei.ttf"),
        ]
        for fname, fpath in font_paths:
            if os.path.exists(fpath):
                try:
                    pdfmetrics.registerFont(TTFont(fname, fpath))
                    font_name = fname
                    break
                except Exception:
                    continue

        doc = SimpleDocTemplate(str(output_path), pagesize=A4,
                                topMargin=20*mm, bottomMargin=20*mm,
                                leftMargin=20*mm, rightMargin=20*mm)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('CustomTitle', parent=styles['Title'],
                                     fontName=font_name, fontSize=20, spaceAfter=20)
        normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'],
                                      fontName=font_name, fontSize=10)
        header_style = ParagraphStyle('CustomHeader', parent=styles['Normal'],
                                      fontName=font_name, fontSize=12, spaceAfter=10,
                                      textColor=colors.HexColor('#c0392b'))

        story = []
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 10*mm))

        if not data:
            story.append(Paragraph("没有数据", normal_style))
        else:
            # 表格
            headers = list(data[0].keys())
            table_data = [headers]
            for row in data:
                table_data.append([str(row.get(h, "")) for h in headers])

            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f6f1')]),
            ]))
            story.append(table)

        story.append(Spacer(1, 15*mm))
        story.append(Paragraph(f"生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
                              normal_style))
        story.append(Paragraph("VoiceTrace 声迹 — 语音档案智能追踪系统", normal_style))

        doc.build(story)
        return True

    except ImportError:
        print("reportlab not installed, cannot export PDF")
        return False
    except Exception as e:
        print(f"Export PDF error: {e}")
        return False
