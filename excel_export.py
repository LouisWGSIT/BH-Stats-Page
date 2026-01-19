"""Excel export utilities for multi-sheet KPI reports"""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from typing import List, Dict, Tuple
from io import BytesIO

def create_excel_report(sheets_data: Dict[str, List[List]]) -> BytesIO:
    """
    Create a multi-sheet Excel workbook from sheets_data dict.
    
    Args:
        sheets_data: Dict where keys are sheet names and values are 2D lists of data
        
    Returns:
        BytesIO object containing the Excel file
    """
    wb = Workbook()
    wb.remove(wb.active)  # Remove default sheet
    
    # Style definitions
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    subheader_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    subheader_font = Font(bold=True, color="FFFFFF", size=10)
    section_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    section_font = Font(bold=True, size=10)
    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Create sheets
    for sheet_idx, (sheet_name, data) in enumerate(sheets_data.items()):
        ws = wb.create_sheet(title=sheet_name)
        
        # Write data
        start_row = 1
        for row_idx, row_data in enumerate(data, start_row):
            for col_idx, cell_value in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=cell_value)
                cell.alignment = Alignment(wrap_text=True, vertical='top', horizontal='left')
                cell.border = border
                
                # Style first row (title row) specially if it contains report title
                if row_idx == 1 and isinstance(cell_value, str) and 'REPORT' in cell_value.upper():
                    cell.font = Font(bold=True, size=16, color="1F4E78")
                    cell.alignment = Alignment(wrap_text=True, vertical='center', horizontal='left')
                # Style headers
                elif row_idx > 1 and any(isinstance(cell_value, str) and cell_value in ['Key Metric', 'Metric', 'Rank', 'Engineer'] for cell_value in row_data):
                    cell.fill = header_fill
                    cell.font = header_font
                # Style section headers (rows with single merged cell or key column)
                elif isinstance(cell_value, str) and cell_value.isupper() and len(str(cell_value)) > 3:
                    # Check if it's a section header (all caps, longer than 3 chars)
                    if col_idx == 1 and any(cell_value.startswith(x) for x in ['EXECUTIVE', 'PERFORMANCE', 'TARGET', 'TOP', 'ALL', 'BREAKDOWN', 'ENGINEER', 'HISTORICAL', 'WEEKLY', 'SPEED', 'CATEGORY', 'CONSISTENCY', 'REPORT', 'GLOSSARY']):
                        cell.fill = section_fill
                        cell.font = section_font
        
        # Auto-adjust column widths
        for column in ws.columns:
            max_length = 0
            col_letter = get_column_letter(column[0].column)
            for cell in column:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)  # Cap at 50
            ws.column_dimensions[col_letter].width = adjusted_width
    
    # Save to BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
