import pandas as pd
import numpy as np
import jdatetime
from datetime import datetime
from sqlalchemy import func
import math
import re
from openpyxl import load_workbook
import os

# --- توابع کمکی برای پاکسازی داده‌ها ---
def extract_number(text):
    if pd.isna(text) or text is None:
        return ""
    return re.sub(r'\D', '', str(text))

def split_name(full_name):
    if pd.isna(full_name) or full_name is None:
        return "", ""
    name_text = re.sub(r'.*:', '', str(full_name)).strip()
    parts = name_text.split(' ', 1)
    first_name = parts[0].strip() if parts else ""
    last_name = parts[1].strip() if len(parts) > 1 else ""
    return first_name, last_name

def process_items_excel(filepath):
    """
    Reads an Excel file, processes its rows, and returns a list of item data dictionaries
    and any validation messages. This function DOES NOT interact with the database.
    """
    messages = []
    items_to_process = []

    column_mapping = {
        'شماره سند': 'document_number',
        'شماره صورتحساب': 'invoice_number_ref',
        'تاریخ سند': 'document_date',
        'فروشنده': 'seller',
        'استان فروشنده': 'seller_province',
        'نوع فعالیت': 'activity_type',
        'مبدا': 'origin',
        'طبقه کالا': 'item_category',
        'شرح کالا': 'product_description',
        'واحداندازه گیری': 'unit_of_measurement',
        'تعداد / مقدار کالا': 'quantity',
        'مبلغ واحد': 'unit_price',
        'مبلغ نهایی': 'final_amount',
        'شناسه کالا': 'product_id',
        'توضیحات': 'remarks',
    }
    
    try:
        # بهبود: تمام داده‌ها به صورت متنی خوانده می‌شوند تا از خطاهای نوع داده جلوگیری شود
        df = pd.read_excel(filepath, dtype=str)
        df = df.rename(columns=lambda x: x.strip())
        df = df.where(pd.notna(df), None)

        print("--- ستون‌های یافت شده در فایل اکسل ---")
        print(list(df.columns))
        print("---------------------------------")
        
        # چک کردن ستون‌های الزامی
        required_excel_columns = set(column_mapping.keys())
        actual_excel_columns = set(df.columns)
        if not required_excel_columns.issubset(actual_excel_columns):
            missing = required_excel_columns - actual_excel_columns
            messages.append(('danger', f"فایل اکسل ناقص است. ستون‌های زیر یافت نشدند: {', '.join(missing)}"))
            return [], messages

        for index, row in df.iterrows():
            try:
                product_id = row.get('شناسه کالا')
                if not product_id:
                    continue

                item_data = {}
                for excel_col, model_field in column_mapping.items():
                    item_data[model_field] = row.get(excel_col)

                quantity_str = item_data.get('quantity', '0')
                item_data['quantity'] = int(float(quantity_str or 0))

                unit_price_str = item_data.get('unit_price', '0.0')
                item_data['unit_price'] = float(unit_price_str or 0.0)
                
                jalali_date_str = item_data.get('document_date')
                gregorian_date = None
                if jalali_date_str:
                    try:
                        gregorian_date = jdatetime.datetime.strptime(str(jalali_date_str), '%Y/%m/%d').togregorian().date()
                    except (ValueError, TypeError):
                        messages.append(('warning', f"ردیف {index + 2}: فرمت تاریخ سند '{jalali_date_str}' نامعتبر است و از آن صرف‌نظر شد."))
                        continue
                
                if gregorian_date is None:
                    messages.append(('warning', f"ردیف {index + 2}: تاریخ سند خالی است و از آن صرف‌نظر شد."))
                    continue
                
                item_data['document_date'] = gregorian_date
                item_data['final_amount'] = item_data['quantity'] * item_data['unit_price']

                items_to_process.append(item_data)

            except Exception as e:
                messages.append(('danger', f"خطا در پردازش داخلی ردیف {index + 2} اکسل: {e}"))
                continue
    
    except Exception as e:
        messages.append(('danger', f"خطا در خواندن یا پردازش کلی فایل اکسل: {e}"))

    return items_to_process, messages

def process_excel_invoices(filepath, db, Item, ItemUsageLog, current_invoice_number_start):
    output_data = []
    log_entries = []
    messages = []
    next_invoice_number = current_invoice_number_start

    try:
        df = pd.read_excel(filepath, header=None, dtype=str).where(pd.notna, None)
        
        CELL_POSITIONS = {"date": (2, 26), "zip_code": (11, 4), "national_id": (9, 16), "buyer_name": (9, 0)}
        PRODUCT_COLUMNS = {"quantity": 4, "unit_price": 6, "discount": 12, "product_description": 2}
        PRODUCT_START_ROW_INDEX = 15

        date_str = df.iloc[CELL_POSITIONS["date"]] if CELL_POSITIONS["date"][0] < len(df) and CELL_POSITIONS["date"][1] < df.shape[1] else ""
        zip_code_raw = df.iloc[CELL_POSITIONS["zip_code"]] if CELL_POSITIONS["zip_code"][0] < len(df) and CELL_POSITIONS["zip_code"][1] < df.shape[1] else ""
        national_id_raw = df.iloc[CELL_POSITIONS["national_id"]] if CELL_POSITIONS["national_id"][0] < len(df) and CELL_POSITIONS["national_id"][1] < df.shape[1] else ""
        buyer_name_full = df.iloc[CELL_POSITIONS["buyer_name"]] if CELL_POSITIONS["buyer_name"][0] < len(df) and CELL_POSITIONS["buyer_name"][1] < df.shape[1] else ""
        
        zip_code = extract_number(zip_code_raw)
        national_id = extract_number(national_id_raw)
        buyer_name, buyer_surname = split_name(buyer_name_full)

        for row_idx in range(PRODUCT_START_ROW_INDEX, len(df)):
            # ✅✅✅ منطق جدید و ضد خطا برای تبدیل اعداد ✅✅✅
            # 1. خواندن مقدار خام
            raw_unit_price = df.iloc[row_idx, PRODUCT_COLUMNS["unit_price"]]
            # 2. تبدیل امن به عدد
            unit_price_val = pd.to_numeric(raw_unit_price, errors='coerce')
            
            if pd.isna(unit_price_val) or unit_price_val == 0:
                break
            
            raw_quantity = df.iloc[row_idx, PRODUCT_COLUMNS["quantity"]]
            quantity_val = pd.to_numeric(raw_quantity, errors='coerce')
            quantity_needed = int(quantity_val) if pd.notna(quantity_val) else 0
            if quantity_needed <= 0: continue

            raw_discount = df.iloc[row_idx, PRODUCT_COLUMNS["discount"]]
            discount_val = pd.to_numeric(raw_discount, errors='coerce')
            discount = float(discount_val) if pd.notna(discount_val) else 0.0

            product_description_from_invoice = str(df.iloc[row_idx, PRODUCT_COLUMNS["product_description"]] or '')

            available_items = db.session.query(Item).filter(Item.quantity > 0).order_by(Item.unit_price.desc()).all()
            item_found_and_processed = False
            for item_in_db in available_items:
                total_used = db.session.query(func.sum(ItemUsageLog.quantity_used)).filter_by(item_id=item_in_db.id).scalar() or 0
                remaining_quantity = item_in_db.quantity - total_used
                
                if remaining_quantity >= quantity_needed:
                    calculated_vat = math.ceil((unit_price_val * quantity_needed) / 10.0)
                    output_data.append({
                        'A': date_str, 'B': next_invoice_number, 'C': zip_code, 'D': national_id,
                        'E': buyer_name, 'F': buyer_surname, 'G': '', 'H': '', 'I': '', 'J': '',
                        'K': item_in_db.product_id, 'L': product_description_from_invoice,
                        'M': item_in_db.unit_of_measurement or '4', 'N': quantity_needed,
                        'O': 'IRR', 'P': 1, 'Q': unit_price_val, 'R': discount, 'S': calculated_vat,
                    })
                    pd_exit_date = pd.to_datetime(date_str, errors='coerce')
                    exit_date_obj = pd_exit_date.date() if pd.notna(pd_exit_date) else datetime.utcnow().date()
                    log_entries.append(ItemUsageLog(
                        item_id=item_in_db.id, exit_date=exit_date_obj,
                        invoice_number_used=str(next_invoice_number),
                        quantity_used=quantity_needed, price_at_usage=unit_price_val
                    ))
                    item_found_and_processed = True
                    break
            
            if not item_found_and_processed:
                messages.append(('warning', f"برای '{product_description_from_invoice}' با تعداد {quantity_needed}، هیچ موجودی کافی در انبار یافت نشد."))
        
        if len(output_data) > 0:
            next_invoice_number += 1
        
        messages.append(('success', f"فایل {os.path.basename(filepath)} با موفقیت پردازش شد."))
    
    except Exception as e:
        messages.append(('danger', f"خطا در پردازش فایل {os.path.basename(filepath)}: {e}"))

    return pd.DataFrame(output_data), log_entries, next_invoice_number, messages

def generate_sjt_output_excel(data_df, template_path, output_path):
    try:
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"فایل الگو در مسیر زیر یافت نشد: {template_path}")

        book = load_workbook(template_path, keep_vba=True)
        sheet = book.active
        merged_ranges = list(sheet.merged_cells.ranges)
        for merged_range in merged_ranges:
            sheet.unmerge_cells(str(merged_range))
        
        start_row = 2
        
        for row in sheet.iter_rows(min_row=start_row, max_row=sheet.max_row):
            for cell in row:
                cell.value = None
        
        for index, row_data in data_df.iterrows():
            current_write_row = start_row + index
            for col_name, value in row_data.items():
                col_index = ord(col_name) - ord('A') + 1
                cell = sheet.cell(row=current_write_row, column=col_index, value=value)

        book.save(output_path)
        return output_path, None
    except Exception as e:
        return None, str(e)

def generate_usage_log_excel(data_df, output_path):
    """
    Generates the usage log Excel file at the specified path.
    """
    try:
        data_df.to_excel(output_path, index=False, engine='openpyxl')
        return output_path, None
    except Exception as e:
        return None, str(e)