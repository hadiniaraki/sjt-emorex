# app/utils.py
import pandas as pd
import numpy as np
import jdatetime
from datetime import datetime
from sqlalchemy import func
import math
import re
from openpyxl import load_workbook
import os
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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
        'واحداندازه‌گیری': 'unit_of_measurement',
        'تعداد / مقدار کالا': 'quantity',
        'مبلغ واحد': 'unit_price',
        'مبلغ نهایی': 'final_amount',
        'شناسه کالا': 'product_id',
        'توضیحات': 'remarks',
    }
    try:
        df = pd.read_excel(filepath, dtype=str)
        df = df.rename(columns=lambda x: x.strip())
        df = df.where(pd.notna(df), None)
        logger.debug(f"Excel columns: {list(df.columns)}")
        
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
                messages.append(('danger', f"خطا در پردازش ردیف {index + 2} اکسل: {e}"))
                continue
    except Exception as e:
        messages.append(('danger', f"خطا در خواندن یا پردازش فایل اکسل: {e}"))
    return items_to_process, messages

def process_excel_invoices(filepath, db, Item, ItemUsageLog, current_invoice_number_start):
    """
    Processes an invoice Excel file and prepares data for output and logs.
    Selects items based on remaining_quantity and unit_price (descending order) without matching product_description.
    Uses product_description and unit_price from Item table for output.
    Date, zip_code, and national_id are optional.
    Selects another item from Item table if the current item has insufficient inventory, ensuring no product is skipped.
    """
    db.session.expire_all()
    
    output_data = []
    log_entries = []
    messages = []
    next_invoice_number = current_invoice_number_start
    required_products = []

    try:
        df = pd.read_excel(filepath, header=None, dtype=str).where(pd.notna, None)
        logger.debug(f"Excel file {filepath} loaded with shape: {df.shape}")

        CELL_POSITIONS = {
            "date": (2, 26),
            "zip_code": (11, 4),
            "national_id": (9, 16),
            "buyer_name": (9, 0)
        }
        PRODUCT_COLUMNS = {
            "quantity": 4,
            "unit_price": 6,
            "discount": 12,
            "product_description": 2
        }
        PRODUCT_START_ROW_INDEX = 15

        if df.shape[0] < PRODUCT_START_ROW_INDEX or df.shape[1] < max(col for col in CELL_POSITIONS.values())[1] + 1:
            messages.append(('danger', f"فایل {os.path.basename(filepath)} خیلی کوچک است یا ساختار نادرستی دارد."))
            return pd.DataFrame(), [], next_invoice_number, messages

        def get_cell_value(position):
            row, col = position
            try:
                return df.iloc[row, col] if row < df.shape[0] and col < df.shape[1] else ""
            except Exception as e:
                logger.warning(f"Error accessing cell at {position}: {e}")
                return ""

        date_str = get_cell_value(CELL_POSITIONS["date"]) or ""
        zip_code_raw = get_cell_value(CELL_POSITIONS["zip_code"]) or ""
        national_id_raw = get_cell_value(CELL_POSITIONS["national_id"]) or ""
        buyer_name_full = get_cell_value(CELL_POSITIONS["buyer_name"]) or ""
        
        zip_code = extract_number(zip_code_raw)
        national_id = extract_number(national_id_raw)
        buyer_name, buyer_surname = split_name(buyer_name_full)

        # هشدار برای فیلدهای خالی به جای توقف پردازش
        if not date_str:
            messages.append(('warning', f"تاریخ در فایل {os.path.basename(filepath)} خالی است. از تاریخ فعلی استفاده می‌شود."))
            date_str = datetime.utcnow().date().strftime('%Y/%m/%d')
        if not zip_code:
            messages.append(('warning', f"کد پستی در فایل {os.path.basename(filepath)} خالی است."))
        if not national_id:
            messages.append(('warning', f"کد ملی در فایل {os.path.basename(filepath)} خالی است."))
        if not buyer_name_full:
            messages.append(('warning', f"نام خریدار در فایل {os.path.basename(filepath)} خالی است."))

        for row_idx in range(PRODUCT_START_ROW_INDEX, df.shape[0]):
            try:
                raw_unit_price = df.iloc[row_idx, PRODUCT_COLUMNS["unit_price"]] if PRODUCT_COLUMNS["unit_price"] < df.shape[1] else None
                unit_price_val = pd.to_numeric(raw_unit_price, errors='coerce')
                if pd.isna(unit_price_val) or unit_price_val == 0:
                    break

                raw_quantity = df.iloc[row_idx, PRODUCT_COLUMNS["quantity"]] if PRODUCT_COLUMNS["quantity"] < df.shape[1] else None
                quantity_val = pd.to_numeric(raw_quantity, errors='coerce')
                quantity_needed = int(quantity_val) if pd.notna(quantity_val) and quantity_val > 0 else 0
                if quantity_needed <= 0:
                    continue

                raw_discount = df.iloc[row_idx, PRODUCT_COLUMNS["discount"]] if PRODUCT_COLUMNS["discount"] < df.shape[1] else None
                discount_val = pd.to_numeric(raw_discount, errors='coerce')
                discount = float(discount_val) if pd.notna(discount_val) else 0.0

                product_description_from_invoice = str(df.iloc[row_idx, PRODUCT_COLUMNS["product_description"]] or '').strip() if PRODUCT_COLUMNS["product_description"] < df.shape[1] else ''
                if not product_description_from_invoice:
                    continue

                required_products.append((product_description_from_invoice, quantity_needed, unit_price_val, discount))
                logger.debug(f"Added product: {product_description_from_invoice}, Quantity: {quantity_needed}")
            except Exception as e:
                logger.warning(f"Error processing row {row_idx + 2} in {filepath}: {e}")
                continue

        if not required_products:
            messages.append(('danger', f"هیچ محصول معتبری در فایل {os.path.basename(filepath)} یافت نشد."))
            return pd.DataFrame(), [], next_invoice_number, messages

        # متغیر برای ردیابی اینکه آیا حداقل یک محصول پردازش شده است
        at_least_one_product_processed = False

        for product_description_from_invoice, quantity_needed, unit_price_val, discount in required_products:
            # انتخاب کالاها صرفاً بر اساس موجودی کافی و ترتیب نزولی قیمت واحد
            all_potential_items = db.session.query(Item).filter(
                Item.remaining_quantity >= quantity_needed  # فقط کالاهایی با موجودی کافی
            ).order_by(Item.unit_price.desc()).all()
            
            if not all_potential_items:
                messages.append(('warning', f"برای '{product_description_from_invoice}' در فایل {os.path.basename(filepath)}، هیچ کالایی با موجودی کافی (نیاز: {quantity_needed}) یافت نشد. مقدار صفر تخصیص داده شد."))
                output_data.append({
                    'A': date_str, 'B': next_invoice_number, 'C': zip_code, 'D': national_id,
                    'E': buyer_name, 'F': buyer_surname, 'G': '', 'H': '', 'I': '', 'J': '',
                    'K': '', 'L': product_description_from_invoice,
                    'M': '4', 'N': 0, 'O': 'IRR', 'P': 1, 'Q': unit_price_val, 'R': discount, 'S': 0,
                })
                continue

            # انتخاب اولین کالا با موجودی کافی
            item_in_db = all_potential_items[0]
            qty_to_take = quantity_needed  # تخصیص دقیقاً به مقدار مورد نیاز
            
            # استفاده از unit_price از جدول item برای محاسبه مالیات و خروجی
            item_unit_price = item_in_db.unit_price if item_in_db.unit_price is not None else unit_price_val
            calculated_vat = math.ceil((item_unit_price * qty_to_take) / 10.0)
            
            output_data.append({
                'A': date_str, 'B': next_invoice_number, 'C': zip_code, 'D': national_id,
                'E': buyer_name, 'F': buyer_surname, 'G': '', 'H': '', 'I': '', 'J': '',
                'K': item_in_db.product_id, 'L': item_in_db.product_description or product_description_from_invoice,
                'M': item_in_db.unit_of_measurement or '4', 'N': qty_to_take,
                'O': 'IRR', 'P': 1, 'Q': item_unit_price, 'R': discount, 'S': calculated_vat,
            })
            
            pd_exit_date = pd.to_datetime(date_str, errors='coerce')
            exit_date_obj = pd_exit_date.date() if pd.notna(pd_exit_date) else datetime.utcnow().date()
            log_entries.append(ItemUsageLog(
                item_id=item_in_db.id, exit_date=exit_date_obj,
                invoice_number_used=str(next_invoice_number),
                quantity_used=qty_to_take, price_at_usage=unit_price_val
            ))
            
            at_least_one_product_processed = True  # حداقل یک محصول پردازش شد

        if at_least_one_product_processed:
            next_invoice_number += 1
        else:
            messages.append(('danger', f"هیچ محصولی در فایل {os.path.basename(filepath)} قابل پردازش نبود (هیچ کالایی با موجودی کافی یافت نشد)."))
            return pd.DataFrame(), [], next_invoice_number, messages

        messages.append(('success', f"فایل {os.path.basename(filepath)} با موفقیت پردازش شد."))

    except Exception as e:
        logger.error(f"Error processing {filepath}: {str(e)}")
        messages.append(('danger', f"خطا در پردازش فایل {os.path.basename(filepath)}: {str(e)}"))
        return pd.DataFrame(), [], next_invoice_number, messages

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
    try:
        data_df.to_excel(output_path, index=False, engine='openpyxl')
        return output_path, None
    except Exception as e:
        return None, str(e)