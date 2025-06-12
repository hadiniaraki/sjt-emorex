import os
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory
from flask_login import login_required
from werkzeug.utils import secure_filename
from sqlalchemy import func
import pandas as pd
from app.extensions import db
from app.models import Item, ItemUsageLog, Settings
from app.forms import (UploadInvoiceForm, UploadItemsFileForm, ItemForm, 
                       SettingsForm)
from app.utils import (process_items_excel, process_excel_invoices, 
                       generate_sjt_output_excel, generate_usage_log_excel)

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
    start_invoice_number = (int(start_invoice.setting_value) if start_invoice and start_invoice.setting_value.isdigit() else current_app.config.get('DEFAULT_START_INVOICE_NUMBER', 1901))
    
    items = Item.query.all()
    items_in_stock = []
    for item in items:
        total_used = db.session.query(func.sum(ItemUsageLog.quantity_used)).filter_by(item_id=item.id).scalar() or 0
        items_in_stock.append({
            'product_id': item.product_id,
            'product_description': item.product_description,
            'quantity': item.quantity,
            'remaining_quantity': item.quantity - total_used
        })
    
    recent_usages = ItemUsageLog.query.order_by(ItemUsageLog.exit_date.desc()).limit(10).all()
    
    return render_template('dashboard.html', title="داشبورد", start_invoice_number=start_invoice_number, items_in_stock=items_in_stock, recent_usages=recent_usages)

@bp.route('/upload_invoices', methods=['GET', 'POST'])
@login_required
def upload_invoices():
    form = UploadInvoiceForm()
    if form.validate_on_submit():
        uploaded_files = request.files.getlist('invoice_files')
        if not uploaded_files or all(f.filename == '' for f in uploaded_files):
            flash('فایلی انتخاب نشده است.', 'warning')
            return redirect(request.url)

        processed_files_count = 0
        
        start_invoice = Settings.query.filter_by(setting_name='START_INVOICE_NUMBER').first()
        current_invoice_number = ( int(start_invoice.setting_value) if start_invoice and start_invoice.setting_value.isdigit() else current_app.config.get('DEFAULT_START_INVOICE_NUMBER', 1901) )

        for file in uploaded_files:
            if not (file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']):
                continue

            filename = secure_filename(file.filename)
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                output_df, log_entries, next_invoice_num, messages = process_excel_invoices(
                    filepath, db, Item, ItemUsageLog, current_invoice_number
                )
                
                for msg_type, msg_content in messages:
                    flash(msg_content, msg_type)

                # ✅✅✅ منطق جدید برای رفع باگ موجودی منفی ✅✅✅
                if not output_df.empty:
                    # برای این فایل، لاگ‌ها را اضافه کرده و بلافاصله کامیت می‌کنیم
                    for entry in log_entries:
                        db.session.add(entry)
                    db.session.commit() 
                    
                    # حالا فایل‌های خروجی را تولید می‌کنیم
                    processed_files_count += 1
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    template_path = os.path.join(current_app.root_path, 'sjt.xlsm')
                    output_filename = f'sjt_output_{filename.split(".")[0]}_{timestamp}.xlsm'
                    output_sjt_path = os.path.join(current_app.config['UPLOAD_FOLDER'], output_filename)
                    
                    _, error = generate_sjt_output_excel(output_df, template_path, output_sjt_path)
                    if error:
                        flash(f"خطا در تولید فایل SJT: {error}", 'danger')
                    else:
                        download_url = url_for('main.download_file', filename=output_filename)
                        flash(f"فایل خروجی SJT برای '{filename}' آماده است. <a href='{download_url}' class='alert-link'>دانلود کنید</a>", "info")
                    
                    # شماره فاکتور را برای فایل بعدی آپدیت می‌کنیم
                    current_invoice_number = next_invoice_num

            except Exception as e:
                db.session.rollback()
                flash(f"خطا در پردازش فایل {filename}: {str(e)}", 'danger')
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
        
        # در انتها، فقط تنظیمات شماره فاکتور را یک بار کامیت می‌کنیم
        if processed_files_count > 0:
            if start_invoice:
                start_invoice.setting_value = str(current_invoice_number)
            else:
                db.session.add(Settings(setting_name='START_INVOICE_NUMBER', setting_value=str(current_invoice_number)))
            db.session.commit()

        return redirect(url_for('main.dashboard'))
    return render_template('upload_invoices.html', form=form, title="آپلود فاکتورها")

# ✅✅✅ بازگرداندن route های دانلود ثابت و حذف route داینامیک ✅✅✅
@bp.route('/download/sjt_output')
@login_required
def download_sjt_output():
    """Route to download the generated sjt_output.xlsm file."""
    directory = current_app.config['UPLOAD_FOLDER']
    filename = 'sjt_output.xlsm'
    try:
        return send_from_directory(directory, filename, as_attachment=True)
    except FileNotFoundError:
        flash("فایل خروجی SJT هنوز ایجاد نشده است.", "warning")
        return redirect(url_for('main.dashboard'))

@bp.route('/download/usage_log')
@login_required
def download_usage_log():
    """Route to download the generated usage_log.xlsx file."""
    directory = current_app.config['UPLOAD_FOLDER']
    filename = 'usage_log.xlsx'
    try:
        return send_from_directory(directory, filename, as_attachment=True)
    except FileNotFoundError:
        flash("فایل لاگ مصرف هنوز ایجاد نشده است.", "warning")
        return redirect(url_for('main.dashboard'))

@bp.route('/upload_items', methods=['GET', 'POST'])
@login_required
def upload_items_file():
    """Handles uploading, processing, and committing item data to the database."""
    form = UploadItemsFileForm()
    if form.validate_on_submit():
        items_file = form.items_file.data[0]
        if not items_file or not items_file.filename:
            flash("شما فایلی را برای آپلود انتخاب نکرده‌اید.", "warning")
            return redirect(request.url)
        filename = secure_filename(items_file.filename)
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        items_file.save(filepath)
        
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
                        continue
                    existing_item = Item.query.filter_by(product_id=product_id).first()
                    if existing_item:
                        existing_item.quantity += item_data.get('quantity', 0)
                        existing_item.unit_price = item_data.get('unit_price', 0.0)
                        existing_item.document_date = item_data.get('document_date')
                        existing_item.seller = item_data.get('seller')
                        existing_item.product_description = item_data.get('product_description')
                        existing_item.final_amount = existing_item.quantity * existing_item.unit_price
                        updated_item_count += 1
                    else:
                        new_item = Item(**item_data)
                        db.session.add(new_item)
                        new_item_count += 1
                db.session.commit()
                flash(f"عملیات با موفقیت انجام شد. {new_item_count} کالای جدید اضافه و {updated_item_count} کالای موجود آپدیت شد.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"خطا در هنگام ذخیره‌سازی در دیتابیس: {e}", "danger")
        
        if os.path.exists(filepath):
            os.remove(filepath)
        return redirect(url_for('main.manage_items'))
    elif request.method == 'POST':
        flash("خطا در اعتبارسنجی فرم. لطفاً از صحت فایل انتخابی مطمئن شوید.", "danger")
    return render_template('upload_items_file.html', title='آپلود فایل کالاها', form=form)


@bp.route('/manage_items')
@login_required
def manage_items():
    """Route to display, search, and manage all items."""
    items = Item.query.order_by(Item.document_date.desc()).all()
    return render_template('manage_items.html', title='مدیریت کالاها', items=items)


@bp.route('/item/add', methods=['GET', 'POST'])
@login_required
def add_item():
    """Route to add a new item manually."""
    form = ItemForm()
    if form.validate_on_submit():
        new_item = Item(
            document_number=form.document_number.data,
            invoice_number_ref=form.invoice_number_ref.data,
            document_date=form.document_date.data,
            seller=form.seller.data,
            seller_province=form.seller_province.data,
            activity_type=form.activity_type.data,
            origin=form.origin.data,
            item_category=form.item_category.data,
            product_id=form.product_id.data,
            product_description=form.product_description.data,
            unit_of_measurement=form.unit_of_measurement.data,
            quantity=form.quantity.data,
            unit_price=form.unit_price.data,
            final_amount=form.quantity.data * form.unit_price.data
        )
        db.session.add(new_item)
        db.session.commit()
        flash('کالای جدید با موفقیت اضافه شد.', 'success')
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
        db.session.commit()
        flash('کالا با موفقیت ویرایش شد.', 'success')
        return redirect(url_for('main.manage_items'))
    return render_template('item_form.html', title='ویرایش کالا', form=form, action='edit')


@bp.route('/item/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_item(item_id):
    """Route to delete an item."""
    item = Item.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash('کالا و لاگ‌های مصرف مربوط به آن با موفقیت حذف شدند.', 'success')
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
        return "Access Denied", 403

    try:
        return send_from_directory(uploads_dir, safe_filename, as_attachment=True)
    except FileNotFoundError:
        flash("فایل درخواستی یافت نشد.", "danger")
        return redirect(url_for('main.dashboard'))