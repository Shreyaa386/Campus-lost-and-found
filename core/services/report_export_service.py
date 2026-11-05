"""
Report Generation and Export Service for CampusCare.
Generates privacy-compliant Excel (.xlsx) and PDF (.pdf) reports
with flexible filtering by date range, category, location, and status.
Separated strictly from HTTP views. Masks sensitive personal numbers.
"""

import io
from datetime import datetime
from django.utils import timezone

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class ReportExportService:
    """
    Transforms filtered lost/found datasets into sanitized Excel and PDF documents.
    """

    @classmethod
    def mask_personal_data(cls, user) -> str:
        """Returns privacy-safe attribution without raw personal phone/email."""
        if not user:
            return "Anonymous"
        role_label = user.get_role_display() if hasattr(user, 'get_role_display') else "User"
        first = user.first_name or user.username[:3]
        return f"{first} ({role_label})"

    @classmethod
    def export_items_excel(cls, items_qs, filters_summary: dict = None) -> io.BytesIO:
        """
        Builds a styled Excel spreadsheet (.xlsx) using openpyxl.
        """
        output = io.BytesIO()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "CampusCare Items"

        # Styles
        title_font = Font(name="Calibri", size=16, bold=True, color="1E3A8A")
        sub_font = Font(name="Calibri", size=10, italic=True, color="475569")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        border_thin = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        # Title Rows
        ws.append(["CampusCare Lost & Found — Official Activity Report"])
        ws.cell(row=1, column=1).font = title_font

        gen_time = timezone.now().strftime("%B %d, %Y %H:%M")
        filter_str = f"Generated on {gen_time} | Filter criteria: {filters_summary or 'All Active Records'}"
        ws.append([filter_str])
        ws.cell(row=2, column=1).font = sub_font
        ws.append([])  # blank row

        # Table Headers
        headers = [
            "Item Code",
            "Report Type",
            "Title",
            "Category",
            "Location",
            "Specific Spot",
            "Date Lost/Found",
            "Status",
            "Reporter Attribution",
            "Logged Date"
        ]
        ws.append(headers)

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=4, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Data Rows
        for item in items_qs.select_related('category', 'location', 'user'):
            code = item.item_code or f"CC-{item.pk:04d}"
            rep_type = item.get_report_type_display()
            cat = item.category.name if item.category else "Uncategorized"
            loc = item.location.name if item.location else "Campus"
            spot = item.location_details or "—"
            item_date = item.date_lost_or_found.strftime("%Y-%m-%d") if item.date_lost_or_found else "—"
            status = item.get_status_display()
            reporter = cls.mask_personal_data(item.user)
            logged = item.created_at.strftime("%Y-%m-%d %H:%M")

            row_data = [code, rep_type, item.title, cat, loc, spot, item_date, status, reporter, logged]
            ws.append(row_data)

            # Row border
            curr_row = ws.max_row
            for col_num in range(1, len(headers) + 1):
                c = ws.cell(row=curr_row, column=col_num)
                c.border = border_thin
                if col_num in [1, 2, 7, 8, 10]:
                    c.alignment = Alignment(horizontal="center")

        # Auto-adjust column width
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        wb.save(output)
        output.seek(0)
        return output

    @classmethod
    def export_items_pdf(cls, items_qs, filters_summary: dict = None) -> io.BytesIO:
        """
        Builds a landscape PDF summary document using reportlab.
        """
        output = io.BytesIO()
        doc = SimpleDocTemplate(
            output,
            pagesize=landscape(letter),
            rightMargin=30,
            leftMargin=30,
            topMargin=30,
            bottomMargin=30
        )
        story = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#1E3A8A'),
            spaceAfter=4
        )
        sub_style = ParagraphStyle(
            'ReportSub',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#64748B'),
            spaceAfter=12
        )
        cell_style = ParagraphStyle(
            'CellText',
            parent=styles['Normal'],
            fontSize=7,
            leading=9
        )
        header_cell_style = ParagraphStyle(
            'HeaderCellText',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
            textColor=colors.white,
            fontName='Helvetica-Bold'
        )

        story.append(Paragraph("CampusCare Lost & Found — Official Activity Report", title_style))
        gen_time = timezone.now().strftime("%B %d, %Y %H:%M")
        story.append(Paragraph(f"Generated at {gen_time} | Privacy Filter Active: Student identities masked.", sub_style))

        # Build table data
        table_data = [[
            Paragraph("Item Ref", header_cell_style),
            Paragraph("Type", header_cell_style),
            Paragraph("Item Title", header_cell_style),
            Paragraph("Category", header_cell_style),
            Paragraph("Location", header_cell_style),
            Paragraph("Date", header_cell_style),
            Paragraph("Status", header_cell_style),
            Paragraph("Reporter", header_cell_style),
        ]]

        for item in items_qs.select_related('category', 'location', 'user')[:200]:
            code = item.item_code or f"CC-{item.pk:04d}"
            rep_type = "Lost" if item.report_type == 'lost' else "Found"
            cat = item.category.name if item.category else "Other"
            loc = item.location.name if item.location else "Campus"
            dt = item.date_lost_or_found.strftime("%Y-%m-%d") if item.date_lost_or_found else ""
            status = item.get_status_display()
            reporter = cls.mask_personal_data(item.user)

            table_data.append([
                Paragraph(code, cell_style),
                Paragraph(rep_type, cell_style),
                Paragraph(item.title[:35], cell_style),
                Paragraph(cat[:20], cell_style),
                Paragraph(loc[:25], cell_style),
                Paragraph(dt, cell_style),
                Paragraph(status, cell_style),
                Paragraph(reporter, cell_style),
            ])

        col_widths = [65, 45, 160, 95, 120, 60, 90, 85]
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ]))
        story.append(t)

        doc.build(story)
        output.seek(0)
        return output

