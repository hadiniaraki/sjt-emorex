# app/main.py
import os
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory
from flask_login import login_required
from werkzeug.utils import secure_filename
from sqlalchemy import func
import pandas as pd
import zipfile
from app.extensions import db
from app.models import Item, ItemUsageLog, Settings
from app.forms import UploadInvoiceForm, UploadItemsFileForm, ItemForm, SettingsForm
from app.utils import process_items_excel, process_excel_invoices, generate_sjt_output_excel, generate_usage_log_excel, calculate_inventory_values
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

bp = Blueprint('main', __name__)

@bp.route('/')
@bp.route('/index')
@login_required
def index():
    return redirect(url_for('main.dashboard'))

@bp.route('/dashboard')
@login_required
def dashboard():
    start_invoice = Settings.query.filter_by(setting_name='START_INVOICE_NUMBER').first()
    start_invoice_number = (
        int(start_invoice.setting_value)
        if start_invoice and start_invoice.setting_value.isdigit()
        else current_app.config.get('DEFAULT_START_INVOICE_NUMBER', 1901)
    )
    
    db.session.expire_all()
    
    items = Item.query.all()
    items_in_stock = []
    for item in items:
        items_in_stock.append({
            'product_id': item.product_id,
            'product_description': item.product_description,
            'quantity': item.quantity,
            'remaining_quantity': item.remaining_quantity
        })
    
    # دریافت مقادیر ارز از جدول Settings
    initial_value = float(Settings.query.filter_by(setting_name='INITIAL_INVENTORY_VALUE').first().setting_value or 0)
    remaining_value = float(Settings.query.filter_by(setting_name='REMAINING_INVENTORY_VALUE').first().setting_value or 0)
    used_value = float(Settings.query.filter_by(setting_name='USED_INVENTORY_VALUE').first().setting_value or 0)
    
    recent_usages = ItemUsageLog.query.order_by(ItemUsageLog.exit_date.desc()).limit(10).all()
    return render_template(
        'dashboard.html',
        title="داشبورد",
        start_invoice_number=start_invoice_number,
        items_in_stock=items_in_stock,
        recent_usages=recent_usages,
        initial_value=initial_value,
        remaining_value=remaining_value,
        used_value=used_value
    )

@bp.route('/upload_invoices', methods=['GET', 'POST'])
@login_required
def upload_invoices():
    """
    Handles uploading, processing, and committing invoice data.
    Updates remaining_quantity in the Item table for inventory control.
    Updates inventory values (initial, remaining, used) after processing.
    Returns a zip file if multiple output files are generated, otherwise returns a single Excel file.
    """
    form = UploadInvoiceForm()
    if form.validate_on_submit():
        uploaded_files = request.files.getlist('invoice_files')
        if not uploaded_files or all(f.filename == '' for f in uploaded_files):
            flash('فایلی انتخاب نشده است.', 'warning')
            return redirect(request.url)

        start_invoice_setting = Settings.query.filter_by(setting_name='START_INVOICE_NUMBER').first()
        current_invoice_number = (
            int(start_invoice_setting.setting_value)
            if start_invoice_setting and start_invoice_setting.setting_value.isdigit()
            else current_app.config.get('DEFAULT_START_INVOICE_NUMBER', 1901)
        )
        
        output_files = []
        successfully_processed_files = []
        all_files_processed_successfully = True
        all_log_entries = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for file in uploaded_files:
            if not (file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']):
                flash(f"فایل '{file.filename}' نامعتبر است یا پسوند مجاز ندارد.", 'warning')
                all_files_processed_successfully = False
                continue

            filename = secure_filename(file.filename)
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            
            try:
                file.save(filepath)
                flash(f"فایل '{filename}' دریافت شد. در حال پردازش...", 'info')
            except Exception as e:
                flash(f"خطا در ذخیره فایل {filename}: {str(e)}", 'danger')
                all_files_processed_successfully = False
                continue

            try:
                db.session.expire_all()
                output_df, log_entries, next_invoice_num, messages = process_excel_invoices(
                    filepath, db, Item, ItemUsageLog, current_invoice_number
                )

                for msg_type, msg_content in messages:
                    flash(msg_content, msg_type)

                if output_df.empty:
                    all_files_processed_successfully = False
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except OSError:
                            pass
                    continue

                try:
                    for entry in log_entries:
                        db.session.add(entry)
                    db.session.commit()
                    flash(f"فایل '{filename}' با موفقیت پردازش و موجودی کالاها به‌روز‌رسانی شد.", 'success')
                    successfully_processed_files.append(filename)
                    all_log_entries.extend(log_entries)

                    # Generate output Excel file
                    output_filename = f'sjt_output_{current_invoice_number}_{timestamp}.xlsm'
                    output_sjt_path = os.path.join(current_app.config['UPLOAD_FOLDER'], output_filename)
                    template_path = os.path.join(current_app.root_path, 'sjt.xlsm')
                    output_file_path, error = generate_sjt_output_excel(output_df, template_path, output_sjt_path)
                    if error:
                        flash(f"خطا در تولید فایل خروجی برای '{filename}': {error}", 'warning')
                    else:
                        output_files.append(output_sjt_path)

                    current_invoice_number = next_invoice_num

                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Database error processing {filename}: {str(e)}")
                    flash(f"خطا در به‌روزرسانی دیتابیس برای فایل '{filename}': {str(e)}", 'danger')
                    all_files_processed_successfully = False
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except OSError:
                            pass
                    continue

            except Exception as e:
                db.session.rollback()
                logger.error(f"Unexpected error processing {filename}: {str(e)}")
                flash(f"خطای غیرمنتظره در پردازش فایل '{filename}': {str(e)}", 'danger')
                all_files_processed_successfully = False
            finally:
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        logger.warning(f"Failed to remove temporary file {filepath}")

        if successfully_processed_files and all_files_processed_successfully:
            try:
                if start_invoice_setting:
                    start_invoice_setting.setting_value = str(current_invoice_number)
                else:
                    start_invoice_setting = Settings(setting_name='START_INVOICE_NUMBER', setting_value=str(current_invoice_number))
                    db.session.add(start_invoice_setting)
                db.session.commit()
                # محاسبه و به‌روزرسانی مقادیر ارز
                initial_value, remaining_value, used_value = calculate_inventory_values(db, Item, Settings)
                flash(f"شماره فاکتور شروع به‌روز‌رسانی شد به: {current_invoice_number}. ارز اولیه: {initial_value:,.2f}, ارز باقیمانده: {remaining_value:,.2f}, ارز مصرف‌شده: {used_value:,.2f}", 'info')
            except Exception as e:
                db.session.rollback()
                flash(f"خطا در به‌روز‌رسانی شماره فاکتور شروع: {e}", 'danger')
        elif successfully_processed_files:
            flash("برخی فایل‌ها با موفقیت پردازش شدند، اما برخی خطا داشتند. شماره فاکتور شروع به‌روز نشد.", 'warning')

        if output_files:
            if len(output_files) > 1:
                zip_filename = f"invoices_{timestamp}.zip"
                zip_path = os.path.join(current_app.config['UPLOAD_FOLDER'], zip_filename)
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for output_file in output_files:
                        zipf.write(output_file, os.path.basename(output_file))
                        try:
                            os.remove(output_file)
                        except OSError:
                            logger.warning(f"Failed to remove temporary output file {output_file}")
                flash(f"فایل‌های خروجی در یک فایل زیپ آماده دانلود هستند. <a href='{url_for('main.download_file', filename=zip_filename)}' class='alert-link'>دانلود فایل زیپ</a>", 'info')
                return redirect(url_for('main.dashboard'))
            else:
                download_url = url_for('main.download_file', filename=os.path.basename(output_files[0]))
                flash(f"فایل خروجی آماده است. <a href='{download_url}' class='alert-link'>دانلود کنید</a>", 'info')
                return redirect(url_for('main.dashboard'))
        else:
            flash("هیچ فایل خروجی تولید نشد.", 'warning')
            return redirect(url_for('main.dashboard'))

    return render_template('upload_invoices.html', form=form, title="آپلود فاکتورها")

@bp.route('/upload_items', methods=['GET', 'POST'])
@login_required
def upload_items_file():
    """
    Handles uploading, processing, and committing item data to the database.
    Updates existing items if product_id exists, adding quantity to both quantity and remaining_quantity.
    Updates inventory values after processing.
    """
    form = UploadItemsFileForm()
    if form.validate_on_submit():
        items_file = form.items_file.data[0]
        if not items_file or not items_file.filename:
            flash("شما فایلی را برای آپلود انتخاب نکرده‌اید.", "warning")
            return redirect(request.url)
        
        filename = secure_filename(items_file.filename)
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        
        try:
            items_file.save(filepath)
        except Exception as e:
            flash(f"خطا در ذخیره فایل: {str(e)}", 'danger')
            return redirect(url_for('main.upload_items_file'))
            
        items_to_process, messages = process_items_excel(filepath)
        for msg_type, msg_content in messages:
            flash(msg_content, msg_type)
        
        new_item_count = 0
        updated_item_count = 0
        if items_to_process:
            try:
                for item_data in items_to_process:
                    product_id = item_data.get('product_id')
                    if not product_id:
                        flash(f"شناسه کالا در ردیف نامعتبر است: {item_data}", 'warning')
                        continue
                    
                    quantity_val = pd.to_numeric(item_data.get('quantity'), errors='coerce')
                    new_quantity = int(quantity_val) if pd.notna(quantity_val) and quantity_val > 0 else 0
                    if new_quantity <= 0:
                        flash(f"مقدار نامعتبر برای کالا با شناسه {product_id}", 'warning')
                        continue
                    
                    existing_item = Item.query.filter_by(product_id=product_id).first()
                    if existing_item:
                        existing_item.document_number = item_data.get('document_number', existing_item.document_number)
                        existing_item.invoice_number_ref = item_data.get('invoice_number_ref', existing_item.invoice_number_ref)
                        existing_item.document_date = item_data.get('document_date', existing_item.document_date)
                        existing_item.seller = item_data.get('seller', existing_item.seller)
                        existing_item.seller_province = item_data.get('seller_province', existing_item.seller_province)
                        existing_item.activity_type = item_data.get('activity_type', existing_item.activity_type)
                        existing_item.origin = item_data.get('origin', existing_item.origin)
                        existing_item.item_category = item_data.get('item_category', existing_item.item_category)
                        existing_item.product_description = item_data.get('product_description', existing_item.product_description)
                        existing_item.unit_of_measurement = item_data.get('unit_of_measurement', existing_item.unit_of_measurement)
                        existing_item.quantity += new_quantity
                        existing_item.unit_price = item_data.get('unit_price', existing_item.unit_price)
                        existing_item.final_amount = existing_item.quantity * existing_item.unit_price
                        existing_item.remarks = item_data.get('remarks', existing_item.remarks)
                        existing_item.remaining_quantity += new_quantity
                        updated_item_count += 1
                        logger.debug(f"Updated item {product_id}: quantity={existing_item.quantity}, remaining_quantity={existing_item.remaining_quantity}")
                    else:
                        new_item = Item(
                            product_id=product_id,
                            document_number=item_data.get('document_number'),
                            invoice_number_ref=item_data.get('invoice_number_ref'),
                            document_date=item_data.get('document_date'),
                            seller=item_data.get('seller'),
                            seller_province=item_data.get('seller_province'),
                            activity_type=item_data.get('activity_type'),
                            origin=item_data.get('origin'),
                            item_category=item_data.get('item_category'),
                            product_description=item_data.get('product_description'),
                            unit_of_measurement=item_data.get('unit_of_measurement'),
                            quantity=new_quantity,
                            unit_price=item_data.get('unit_price', 0.0),
                            final_amount=item_data.get('final_amount'),
                            remarks=item_data.get('remarks'),
                            remaining_quantity=new_quantity
                        )
                        db.session.add(new_item)
                        new_item_count += 1
                        logger.debug(f"Added new item {product_id} with quantity: {new_quantity}")
                
                db.session.commit()
                # محاسبه و به‌روزرسانی مقادیر ارز
                initial_value, remaining_value, used_value = calculate_inventory_values(db, Item, Settings)
                flash(f"عملیات با موفقیت انجام شد. {new_item_count} کالای جدید اضافه و {updated_item_count} کالای موجود آپدیت شد. ارز اولیه: {initial_value:,.2f}, ارز باقیمانده: {remaining_value:,.2f}, ارز مصرف‌شده: {used_value:,.2f}", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"خطا در هنگام ذخیره‌سازی در دیتابیس: {str(e)}", "danger")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                logger.warning(f"Failed to remove temporary file {filepath}")
                
        return redirect(url_for('main.manage_items'))
    elif request.method == 'POST':
        flash("خطا در اعتبارسنجی فرم. لطفاً از صحت فایل انتخابی مطمئن شوید.", "danger")
        
    return render_template('upload_items_file.html', title='آپلود فایل کالاها', form=form)

@bp.route('/manage_items')
@login_required
def manage_items():
    """Route to display, search, and manage all items."""
    db.session.expire_all()
    items = Item.query.order_by(Item.document_date.desc()).all()
    items_with_stock = []
    for item in items:
        items_with_stock.append({
            'id': item.id,
            'document_number': item.document_number,
            'invoice_number_ref': item.invoice_number_ref,
            'document_date': item.document_date,
            'seller': item.seller,
            'seller_province': item.seller_province,
            'activity_type': item.activity_type,
            'origin': item.origin,
            'item_category': item.item_category,
            'product_description': item.product_description,
            'unit_of_measurement': item.unit_of_measurement,
            'quantity': item.quantity,
            'unit_price': item.unit_price,
            'final_amount': item.final_amount,
            'product_id': item.product_id,
            'remarks': item.remarks,
            'remaining_quantity': item.remaining_quantity
        })
    return render_template('manage_items.html', title='مدیریت کالاها', items=items_with_stock)

@bp.route('/item/add', methods=['GET', 'POST'])
@login_required
def add_item():
    """Route to add a new item manually."""
    form = ItemForm()
    if form.validate_on_submit():
        product_id = form.product_id.data
        existing_item = Item.query.filter_by(product_id=product_id).first()
        if existing_item:
            flash(f"کالایی با شناسه {product_id} از قبل وجود دارد. لطفاً از آپلود فایل یا ویرایش استفاده کنید.", 'warning')
            return redirect(url_for('main.add_item'))
        
        new_item = Item(
            document_number=form.document_number.data,
            invoice_number_ref=form.invoice_number_ref.data,
            document_date=form.document_date.data,
            seller=form.seller.data,
            seller_province=form.seller_province.data,
            activity_type=form.activity_type.data,
            origin=form.origin.data,
            item_category=form.item_category.data,
            product_id=product_id,
            product_description=form.product_description.data,
            unit_of_measurement=form.unit_of_measurement.data,
            quantity=form.quantity.data,
            unit_price=form.unit_price.data,
            final_amount=form.quantity.data * form.unit_price.data,
            remaining_quantity=form.quantity.data
        )
        db.session.add(new_item)
        db.session.commit()
        # محاسبه و به‌روزرسانی مقادیر ارز
        initial_value, remaining_value, used_value = calculate_inventory_values(db, Item, Settings)
        flash(f"کالای جدید با موفقیت اضافه شد. ارز اولیه: {initial_value:,.2f}, ارز باقیمانده: {remaining_value:,.2f}, ارز مصرف‌شده: {used_value:,.2f}", 'success')
        return redirect(url_for('main.manage_items'))
    return render_template('item_form.html', title='افزودن کالا', form=form, action='add')

@bp.route('/item/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_item(item_id):
    """Route to edit an existing item."""
    item = Item.query.get_or_404(item_id)
    form = ItemForm(obj=item, original_product_id=item.product_id)
    if form.validate_on_submit():
        form.populate_obj(item)
        item.final_amount = item.quantity * item.unit_price
        item.remaining_quantity = item.quantity  # Reset remaining_quantity to quantity
        db.session.commit()
        # محاسبه و به‌روزرسانی مقادیر ارز
        initial_value, remaining_value, used_value = calculate_inventory_values(db, Item, Settings)
        flash(f"کالا با موفقیت ویرایش شد. ارز اولیه: {initial_value:,.2f}, ارز باقیمانده: {remaining_value:,.2f}, ارز مصرف‌شده: {used_value:,.2f}", 'success')
        return redirect(url_for('main.manage_items'))
    return render_template('item_form.html', title='ویرایش کالا', form=form, action='edit')

@bp.route('/item/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    """Route to delete an item."""
    item = Item.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    # محاسبه و به‌روزرسانی مقادیر ارز
    initial_value, remaining_value, used_value = calculate_inventory_values(db, Item, Settings)
    flash(f"کالا و لاگ‌های مصرف مربوط به آن با موفقیت حذف شدند. ارز اولیه: {initial_value:,.2f}, ارز باقیمانده: {remaining_value:,.2f}, ارز مصرف‌شده: {used_value:,.2f}", 'success')
    return redirect(url_for('main.manage_items'))

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def app_settings():
    """Route to manage application settings like start invoice number."""
    form = SettingsForm()
    setting = Settings.query.filter_by(setting_name='START_INVOICE_NUMBER').first()
    if form.validate_on_submit():
        if setting:
            setting.setting_value = str(form.start_invoice_number.data)
        else:
            setting = Settings(setting_name='START_INVOICE_NUMBER', setting_value=str(form.start_invoice_number.data))
            db.session.add(setting)
        db.session.commit()
        flash('تنظیمات با موفقیت ذخیره شد.', 'success')
        return redirect(url_for('main.dashboard'))
    elif request.method == 'GET':
        if setting and setting.setting_value:
            form.start_invoice_number.data = int(setting.setting_value)
        else:
            form.start_invoice_number.data = current_app.config.get('DEFAULT_START_INVOICE_NUMBER')
    return render_template('settings.html', title='تنظیمات', form=form)

@bp.route('/download/<path:filename>')
@login_required
def download_file(filename):
    """A secure and dynamic route to download any file from the upload folder."""
    safe_filename = secure_filename(filename)
    uploads_dir = current_app.config['UPLOAD_FOLDER']
    if not os.path.normpath(os.path.join(uploads_dir, safe_filename)).startswith(os.path.normpath(uploads_dir)):
        flash("دسترسی غیرمجاز به فایل.", "danger")
        return redirect(url_for('main.dashboard'))
    try:
        return send_from_directory(uploads_dir, safe_filename, as_attachment=True)
    except FileNotFoundError:
        flash("فایل درخواستی یافت نشد.", "danger")
        return redirect(url_for('main.dashboard'))