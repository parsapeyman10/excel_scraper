import sys
import openpyxl
import pandas as pd
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QMessageBox, QFileDialog, QGroupBox, QLabel,
                             QStatusBar, QCheckBox)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt

class IndustrialBOMValidator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BOM Integrity & Placement Validator")
        self.resize(1150, 750)
        self.setup_ui()
        self.apply_industrial_theme()
        self.extracted_data_cache = []
        self.top_data_cache = []
        self.bot_data_cache = []

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Control Panel Group
        control_group = QGroupBox("پنل کنترل عملیات")
        control_group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        control_layout = QHBoxLayout(control_group)

        self.lbl_file_path = QLabel("فایلی انتخاب نشده است")
        self.lbl_file_path.setStyleSheet("color: #555; font-weight: normal;")
        
        self.btn_load = QPushButton("انتخاب فایل اکسل")
        self.btn_load.setMinimumHeight(35)
        self.btn_load.clicked.connect(self.select_file)

        self.btn_process = QPushButton("پردازش و اعتبارسنجی")
        self.btn_process.setMinimumHeight(35)
        self.btn_process.setEnabled(False)
        self.btn_process.clicked.connect(self.process_excel)

        control_layout.addWidget(self.btn_load)
        control_layout.addWidget(self.lbl_file_path, stretch=1)
        control_layout.addWidget(self.btn_process)
        main_layout.addWidget(control_group)

        # Data Visualization Group
        data_group = QGroupBox("خروجی تحلیل لایه‌های مونتاژ")
        data_group.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        data_layout = QVBoxLayout(data_group)

        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(7)
        self.table_widget.setHorizontalHeaderLabels([
            "انتخاب", "Stock ID", "Part Description", "Top Placements", "Bot Placements", "Total Required", "Verification Status"
        ])
        
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(3, 7):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
            
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        data_layout.addWidget(self.table_widget)
        main_layout.addWidget(data_group)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("سیستم آماده به کار است.")
        self.target_file = ""

    def apply_industrial_theme(self):
        style_sheet = """
            QMainWindow {
                background-color: #F0F2F5;
            }
            QGroupBox {
                border: 1px solid #B0B5B9;
                border-radius: 6px;
                margin-top: 12px;
                background-color: #FFFFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #2C3E50;
            }
            QPushButton {
                background-color: #2980B9;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #3498DB;
            }
            QPushButton:disabled {
                background-color: #BDC3C7;
                color: #7F8C8D;
            }
            QTableWidget {
                gridline-color: #D0D3D4;
                border: 1px solid #BDC3C7;
                border-radius: 4px;
                background-color: #FFFFFF;
                alternate-background-color: #F8F9F9;
            }
            QHeaderView::section {
                background-color: #34495E;
                color: white;
                padding: 6px;
                border: 1px solid #2C3E50;
                font-weight: bold;
            }
            QStatusBar {
                background-color: #EAECEE;
                color: #333;
                border-top: 1px solid #B0B5B9;
            }
        """
        self.setStyleSheet(style_sheet)

    def select_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "انتخاب فایل BOM", "", "Excel Files (*.xlsx *.xls)"
        )
        if file_name:
            self.target_file = file_name
            self.lbl_file_path.setText(file_name)
            self.btn_process.setEnabled(True)
            self.status_bar.showMessage("فایل بارگذاری شد. آماده پردازش.")

    def process_excel(self):
        self.table_widget.setRowCount(0)
        self.status_bar.showMessage("در حال تحلیل داده‌ها...")
        QApplication.processEvents()
        
        try:
            xls = pd.ExcelFile(self.target_file, engine='openpyxl')
            
            target_sheet = None
            for sheet in xls.sheet_names:
                if "مونتاژ" in sheet or "ماشین" in sheet:
                    target_sheet = sheet
                    break
                    
            if not target_sheet:
                QMessageBox.warning(self, "خطای اعتبارسنجی", "شیت مرجع 'مونتاژ ماشینی' یافت نشد.")
                self.status_bar.showMessage("خطا در یافتن شیت هدف.")
                return

            df_main = pd.read_excel(xls, sheet_name=target_sheet, header=None)
            
            try:
                df_top = pd.read_excel(xls, sheet_name='top', header=None)
                self.top_data_cache = df_top.astype(str).apply(lambda x: x.str.strip()).values.flatten().tolist()
            except ValueError:
                self.top_data_cache = []
                
            try:
                df_bot = pd.read_excel(xls, sheet_name='bot', header=None)
                self.bot_data_cache = df_bot.astype(str).apply(lambda x: x.str.strip()).values.flatten().tolist()
            except ValueError:
                self.bot_data_cache = []

            header_row, col_part, col_qty, col_stock = self.find_first_matching_headers(df_main)
            
            if header_row == -1 or col_part == -1 or col_qty == -1 or col_stock == -1:
                QMessageBox.warning(self, "خطای ساختاری", "عناوین اصلی Part Name، Qty و Stock طبق قانون یافت نشدند.")
                self.status_bar.showMessage("خطا در ساختار ستون‌ها.")
                return

            self.extracted_data_cache = self.extract_data(df_main, header_row, col_part, col_qty, col_stock)
            self.evaluate_and_display(self.extracted_data_cache, self.top_data_cache, self.bot_data_cache)
            
            self.status_bar.showMessage(f"پردازش با موفقیت انجام شد. {len(self.extracted_data_cache)} قطعه بررسی گردید.")
            
        except Exception as e:
            QMessageBox.critical(self, "خطای پردازشگر", f"توقف سیستم به دلیل خطای پیش‌بینی نشده:\n{str(e)}")
            self.status_bar.showMessage("پردازش متوقف شد.")

    def find_first_matching_headers(self, df):
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

    def extract_data(self, df, header_row, col_part, col_qty, col_stock):
        data = []
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
            stock_str = "" if is_stock_empty else str(stock_val).strip()
            if stock_str.endswith('.0'):
                stock_str = stock_str[:-2]
                
            qty_str = "" if is_qty_empty else str(qty_val).strip()
            
            # فیلتر پیشرفته برای حذف کامل سرتیترها و مقادیر تکراری عناوین
            stock_lower = stock_str.lower()
            part_lower = part_str.lower()
            
            header_keywords = [
                'stock no', 'stock id', 'stockid', 'part name', 'partname', 
                'part description', 'description', 'qty', 'quantity', 
                'total required', 'verification', 'ref', 'designator', 'item'
            ]
            
            is_header_row = any(kw in stock_lower or kw in part_lower for kw in header_keywords)
            
            try:
                qty_num = int(float(qty_str))
            except (ValueError, TypeError):
                is_header_row = True
                
            if is_header_row:
                continue
                
            data.append({
                'Stock': stock_str,
                'Part Name': part_str,
                'Qty': qty_num
            })
            
        return data

    def evaluate_and_display(self, data, top_data_list, bot_data_list):
        self.table_widget.setRowCount(len(data))
        
        for row_idx, item in enumerate(data):
            stock = item['Stock']
            part_name = item['Part Name']
            qty = item['Qty']
            
            search_key = stock if stock else part_name
            
            num_top = top_data_list.count(search_key) if search_key else 0
            num_bot = bot_data_list.count(search_key) if search_key else 0
            
            is_valid = (num_top + num_bot) == qty
            status_text = "PASS" if is_valid else "FAIL"
            
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_box = QCheckBox()
            chk_box.setChecked(False)
            chk_layout.addWidget(chk_box)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.table_widget.setCellWidget(row_idx, 0, chk_widget)
            
            items = [
                None,
                QTableWidgetItem(stock),
                QTableWidgetItem(part_name),
                QTableWidgetItem(str(num_top)),
                QTableWidgetItem(str(num_bot)),
                QTableWidgetItem(str(qty)),
                QTableWidgetItem(status_text)
            ]
            
            bg_color = QColor(220, 255, 220) if is_valid else QColor(255, 220, 220)
            text_color = QColor(0, 100, 0) if is_valid else QColor(150, 0, 0)
            
            for col_idx, table_item in enumerate(items):
                if col_idx > 0:
                    table_item.setBackground(bg_color)
                    if col_idx == 6:
                        table_item.setForeground(text_color)
                        font = QFont()
                        font.setBold(True)
                        table_item.setFont(font)
                    
                    table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if col_idx == 2:
                        table_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    
                    self.table_widget.setItem(row_idx, col_idx, table_item)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    font = app.font()
    font.setPointSize(9)
    app.setFont(font)
    
    window = IndustrialBOMValidator()
    window.show()
    sys.exit(app.exec())