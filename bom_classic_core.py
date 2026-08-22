"""
منطق مرکزی برنامهٔ کلاسیک BOM Validator (بدون هیچ وابستگی به رابط کاربری)
==========================================================================

این توابع عیناً از «نسخهٔ اولیهٔ 342 خطی» برنامه (کامیت «first items») استخراج
و تکامل یافته‌اند تا هم در رابط گرافیکی («excel scraper.py») و هم در تست‌ها
و محیط‌های بدون GUI قابل استفاده باشند:

* یافتن شیت BOM و ستون‌های Part/Qty/Stock (قواعد فازی نسخهٔ اولیه)
* استخراج ردیف‌های قطعه
* خواندن و تخت‌کردن مقادیر top/bot (از داخل فایل BOM یا فایل‌های مجزا)
* تطبیق و شمارش PASS/FAIL
* ساخت اکسل خروجیِ حالت سه‌فایل: کلون ۱۰۰٪ BOM + مقادیر تازهٔ top/bot با مختصات PCB
"""

from __future__ import annotations

import collections
import datetime
import os

import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, PatternFill
from openpyxl.styles import Font as XlFont

HEADER_KEYWORDS = [
    'stock no', 'stock id', 'stockid', 'part name', 'partname',
    'part description', 'description', 'qty', 'quantity',
    'total required', 'verification', 'ref', 'designator', 'item',
]


# ---------------------------------------------------------------------------
# نرمال‌سازی سلول‌ها
# ---------------------------------------------------------------------------
def _cell_to_str(value) -> str:
    """تبدیل امن مقدار سلول به رشتهٔ تمیز؛ NaN حذف و اعداد صحیح بدون «.0»."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0"):
        # اصلاح مصنوع رایج اکسل: «1110101.0» → «1110101»
        head = text[:-2]
        if head.isdigit():
            return head
    return text


def _count_key(text: str) -> str:
    """کلید یکدست برای شمارش؛ هر دو طرفِ تطبیق (BOM و top/bot) با همین قاعده."""
    return text.strip().casefold()


def _flatten_values(df: pd.DataFrame) -> list[str]:
    """تخت‌سازی همهٔ سلول‌های یک شیت به فهرست رشته‌های تمیز (معنای نسخهٔ اولیه)."""
    values: list[str] = []
    for val in df.values.flatten().tolist():
        text = _cell_to_str(val)
        if text:
            values.append(text)
    return values


# ---------------------------------------------------------------------------
# یافتن شیت‌ها و سربرگ‌ها (قواعد اصلی نسخهٔ اولیه)
# ---------------------------------------------------------------------------
def _pick_sheet_name(sheet_names: list[str], needle: str) -> str | None:
    for name in sheet_names:
        if needle in str(name).strip().lower():
            return name
    return None


def find_bom_sheet_name(sheet_names: list[str]) -> str | None:
    """قاعدهٔ نسخهٔ اولیه: شیتی که «مونتاژ» یا «ماشین» در نامش باشد."""
    for sheet in sheet_names:
        if "مونتاژ" in sheet or "ماشین" in sheet:
            return sheet
    return None


def find_first_matching_headers(df: pd.DataFrame):
    """
    یافتن ردیف عنوان و ستون‌های Part/Qty/Stock — منطق اصلی نسخهٔ اولیه.
    خروجی: (header_row, col_part, col_qty, col_stock) — در صورت شکست همه -1.
    """
    header_row = -1
    col_part = -1
    col_qty = -1
    col_stock = -1

    for r_idx in range(min(15, len(df))):
        row = df.iloc[r_idx]
        p_found, q_found = -1, -1

        for c_idx, val in row.items():
            if pd.notna(val):
                val_str = str(val).strip().lower().replace(" ", "").replace("_", "")
                if p_found == -1 and ('partname' in val_str or val_str == 'part'):
                    p_found = c_idx
                elif q_found == -1 and ('qty' in val_str or 'quantity' in val_str):
                    q_found = c_idx

        if p_found != -1 and q_found != -1:
            header_row = r_idx
            col_part = p_found
            col_qty = q_found
            break

    if header_row != -1:
        for check_r in [header_row, header_row + 1]:
            if check_r < len(df):
                row_chk = df.iloc[check_r]
                for c_idx, val in row_chk.items():
                    if pd.notna(val):
                        val_str = str(val).strip().lower().replace(" ", "").replace("_", "")
                        if 'stock' in val_str:
                            col_stock = c_idx
                            break
            if col_stock != -1:
                break

    return header_row, col_part, col_qty, col_stock


def extract_data(df: pd.DataFrame, header_row: int, col_part: int,
                 col_qty: int, col_stock: int) -> list[dict]:
    """
    استخراج سطرهای قطعه از شیت BOM — منطق اصلی نسخهٔ اولیه
    (به‌علاوهٔ مدیریت امن‌تر سلول‌های عددیِ اکسل).
    """
    data: list[dict] = []
    for r_idx in range(header_row + 1, len(df)):
        part_val = df.iat[r_idx, col_part]
        qty_val = df.iat[r_idx, col_qty]
        stock_val = df.iat[r_idx, col_stock]

        is_part_empty = pd.isna(part_val) or str(part_val).strip() == ""
        is_qty_empty = pd.isna(qty_val) or str(qty_val).strip() == ""
        is_stock_empty = pd.isna(stock_val) or str(stock_val).strip() == ""

        if is_part_empty and is_qty_empty and is_stock_empty:
            continue

        part_str = "" if is_part_empty else str(part_val).strip()
        stock_str = "" if is_stock_empty else _cell_to_str(stock_val)
        qty_str = "" if is_qty_empty else _cell_to_str(qty_val)

        # فیلتر پیشرفته برای حذف کامل سرتیترها و مقادیر تکراری عناوین
        stock_lower = stock_str.lower()
        part_lower = part_str.lower()

        is_header_row = any(
            kw in stock_lower or kw in part_lower for kw in HEADER_KEYWORDS
        )

        try:
            qty_num = int(float(qty_str))
        except (ValueError, TypeError):
            is_header_row = True
            qty_num = 0

        if is_header_row:
            continue

        data.append({'Stock': stock_str, 'Part Name': part_str, 'Qty': qty_num})

    return data


def extract_bom_rows(bom_path: str) -> list[dict]:
    """بازکردن فایل BOM و استخراج ردیف‌ها با همان قواعد نسخهٔ اولیه."""
    xls = pd.ExcelFile(bom_path, engine='openpyxl')
    target_sheet = find_bom_sheet_name(xls.sheet_names)
    if not target_sheet:
        raise ValueError("شیت مرجع 'مونتاژ ماشینی' یافت نشد.")
    df_main = pd.read_excel(xls, sheet_name=target_sheet, header=None)
    header_row, col_part, col_qty, col_stock = find_first_matching_headers(df_main)
    if header_row == -1 or col_part == -1 or col_qty == -1 or col_stock == -1:
        raise ValueError("عناوین اصلی Part Name، Qty و Stock طبق قانون یافت نشدند.")
    return extract_data(df_main, header_row, col_part, col_qty, col_stock)


# ---------------------------------------------------------------------------
# خواندن مقادیر top/bot
# ---------------------------------------------------------------------------
def load_placement_values(path: str, preferred: str) -> tuple[list[str], str]:
    """
    خواندن فایل مجزای TOP/BOT و بازگرداندن فهرست تختِ مقادیر + نام شیت استفاده‌شده.
    اگر شیتی با نام top/bot وجود داشته باشد همان، در غیر این صورت اولین شیت.
    """
    xls = pd.ExcelFile(path, engine='openpyxl')
    sheet = _pick_sheet_name(list(xls.sheet_names), preferred) or xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=sheet, header=None)
    return _flatten_values(df), str(sheet)


def load_single_file_values(xls: pd.ExcelFile, sheet_name: str) -> list[str]:
    """معادل اصلاح‌شدهٔ همان خواندن top/bot در نسخهٔ اولیه (از داخل همان فایل BOM)."""
    df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    return _flatten_values(df)


def evaluate_rows(data: list[dict], top_values: list[str],
                  bot_values: list[str]) -> list[dict]:
    """
    محاسبهٔ شمارش TOP/BOT و وضعیت PASS/FAIL برای هر قطعه.
    قاعدهٔ نسخهٔ اولیه: (تعداد TOP + تعداد BOT) == Qty  →  PASS
    """
    top_counter = collections.Counter(_count_key(v) for v in top_values if v)
    bot_counter = collections.Counter(_count_key(v) for v in bot_values if v)

    results = []
    for item in data:
        stock = item['Stock']
        part_name = item['Part Name']
        qty = item['Qty']
        search_key = _count_key(stock if stock else part_name)
        num_top = top_counter.get(search_key, 0) if search_key else 0
        num_bot = bot_counter.get(search_key, 0) if search_key else 0
        is_valid = (num_top + num_bot) == qty
        results.append({
            'Stock': stock, 'Part Name': part_name, 'Qty': qty,
            'Top': num_top, 'Bot': num_bot, 'Status': "PASS" if is_valid else "FAIL",
            'Valid': is_valid,
        })
    return results


# ---------------------------------------------------------------------------
# ساخت اکسل خروجیِ حالت سه‌فایل: کلونِ ۱۰۰٪ BOM + مقادیر تازهٔ top/bot
# ---------------------------------------------------------------------------

_DARK_FILL = PatternFill("solid", start_color="FF34495E", end_color="FF34495E")
_PASS_FILL = PatternFill("solid", start_color="FFC6EFCE", end_color="FFC6EFCE")
_FAIL_FILL = PatternFill("solid", start_color="FFFFC7CE", end_color="FFFFC7CE")
_HEAD_FONT = XlFont(bold=True, color="FFFFFFFF")
_TITLE_FONT = XlFont(bold=True, size=13, color="FF2C3E50")


def _copy_sheet_values(src_ws, dst_ws, header_bold: bool = True) -> None:
    """کپیِ سلول‌به‌سلولِ مقادیر (با حفظ نوع داده) از شیت مبدأ به مقصد."""
    for row in src_ws.iter_rows(values_only=True):
        dst_ws.append(list(row))
    if header_bold and dst_ws.max_row >= 1:
        for cell in dst_ws[1]:
            cell.font = _HEAD_FONT
            cell.fill = _DARK_FILL
            cell.alignment = Alignment(horizontal="center")
    dst_ws.freeze_panes = "A2"
    for col_cells in dst_ws.columns:
        try:
            letter = col_cells[0].column_letter
        except Exception:
            continue
        width = 10
        for cell in col_cells[:200]:
            if cell.value is not None:
                width = max(width, min(42, len(str(cell.value)) + 3))
        dst_ws.column_dimensions[letter].width = width


def build_combined_workbook(bom_path: str, top_path: str, bot_path: str,
                            results: list[dict], out_path: str,
                            top_sheet_name: str = "top",
                            bot_sheet_name: str = "bot") -> str:
    """
    خروجی حالت سه‌فایل: یک کاربرگ جدید که **دقیقاً مثل فایل BOM** است
    (همهٔ شیت‌ها، عنوان‌ها و قالب‌بندی حفظ می‌شود) و فقط:

    * شیت «top» با مقادیر فایل TOP (Designator، مختصات PCB، Rotation، …) جایگذاری می‌شود
    * شیت «bot» با مقادیر فایل BOT جایگذاری می‌شود
    * شیت «Validation Report» با نتیجهٔ PASS/FAIL اضافه می‌شود
    """
    if bom_path.lower().endswith(".xls"):
        raise ValueError("خروجی‌گرفتن فقط برای فایل‌های .xlsx پشتیبانی می‌شود (BOM فعلی .xls است).")

    wb = openpyxl.load_workbook(bom_path)

    for sheet_title, src_path, wanted_index in (
        ("top", top_path, 1),
        ("bot", bot_path, 2),
    ):
        if sheet_title in wb.sheetnames:
            del wb[sheet_title]
        src_wb = openpyxl.load_workbook(src_path, data_only=True)
        src_ws = src_wb[sheet_title] if sheet_title in src_wb.sheetnames else src_wb.active
        index = min(wanted_index, len(wb.sheetnames))
        dst_ws = wb.create_sheet(sheet_title, index)
        _copy_sheet_values(src_ws, dst_ws)

    # ---- شیت گزارش اعتبارسنجی ----
    report_title = "Validation Report"
    if report_title in wb.sheetnames:
        del wb[report_title]
    ws = wb.create_sheet(report_title)
    ws.sheet_view.rightToLeft = True

    now_txt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    passed = sum(1 for r in results if r['Valid'])
    failed = len(results) - passed

    ws.append(["گزارش اعتبارسنجی BOM ↔ TOP/BOT"])
    ws.cell(row=1, column=1).font = _TITLE_FONT
    ws.append([f"تاریخ تولید: {now_txt}",
               f"BOM: {os.path.basename(bom_path)}",
               f"TOP: {os.path.basename(top_path)} (شیت {top_sheet_name})",
               f"BOT: {os.path.basename(bot_path)} (شیت {bot_sheet_name})"])
    ws.append([f"کل قطعات: {len(results)}", f"PASS: {passed}", f"FAIL: {failed}"])
    ws.append([])

    header = ["Stock ID", "Part Name", "Total Required",
              "Top Placements", "Bot Placements", "Verification Status"]
    ws.append(header)
    head_row = ws.max_row
    for cell in ws[head_row]:
        cell.font = _HEAD_FONT
        cell.fill = _DARK_FILL
        cell.alignment = Alignment(horizontal="center")

    for r in results:
        ws.append([r['Stock'], r['Part Name'], r['Qty'], r['Top'], r['Bot'], r['Status']])
        row_idx = ws.max_row
        fill = _PASS_FILL if r['Valid'] else _FAIL_FILL
        font = XlFont(bold=True, color="FF006100" if r['Valid'] else "FF9C0006")
        for col in range(1, 7):
            ws.cell(row=row_idx, column=col).fill = fill
            ws.cell(row=row_idx, column=col).alignment = Alignment(horizontal="center")
        ws.cell(row=row_idx, column=2).alignment = Alignment(horizontal="right")
        ws.cell(row=row_idx, column=6).font = font

    widths = [16, 46, 14, 14, 14, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=head_row, column=i).column_letter].width = w
    ws.freeze_panes = f"A{head_row + 1}"

    wb.save(out_path)
    return out_path
