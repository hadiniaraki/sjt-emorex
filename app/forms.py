# sjt_app/app/forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, IntegerField, FloatField, DateField
from wtforms.fields import MultipleFileField # << ایمپورت جدید
from wtforms.validators import DataRequired, ValidationError, EqualTo, Length, NumberRange, Optional
from flask_wtf.file import FileAllowed
from app.models import User, Item

class LoginForm(FlaskForm):
    username = StringField('نام کاربری', validators=[DataRequired(message="نام کاربری الزامی است.")])
    password = PasswordField('رمز عبور', validators=[DataRequired(message="رمز عبور الزامی است.")])
    remember_me = BooleanField('مرا به خاطر بسپار')
    submit = SubmitField('ورود')

class RegistrationForm(FlaskForm):
    username = StringField('نام کاربری', validators=[DataRequired(message="نام کاربری الزامی است."), Length(min=3, max=64)])
    password = PasswordField('رمز عبور', validators=[DataRequired(message="رمز عبور الزامی است.")])
    password2 = PasswordField(
        'تکرار رمز عبور', validators=[DataRequired(message="تکرار رمز عبور الزامی است."), EqualTo('password', message="رمز عبورها باید یکسان باشند.")])
    submit = SubmitField('ثبت نام')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('این نام کاربری قبلاً استفاده شده است.')

class UploadInvoiceForm(FlaskForm):
    # << استفاده از MultipleFileField
    invoice_files = MultipleFileField('انتخاب فایل‌های فاکتور (Excel)', validators=[
        DataRequired(message="حداقل یک فایل فاکتور انتخاب کنید."),
        FileAllowed(['xlsx', 'xls', 'xlsm'], 'فقط فایل‌های Excel (xlsx, xls, xlsm) مجاز هستند.')
    ])
    submit = SubmitField('پردازش فاکتورها')

# ... بقیه فرم‌ها بدون تغییر هستند و صحیح به نظر می‌رسند ...
# (کدهای ItemForm, SettingsForm, UploadItemsFileForm را اینجا قرار دهید)

class UploadItemsFileForm(FlaskForm):
    """Form for uploading the main items data file."""
    items_file = MultipleFileField('انتخاب فایل اطلاعات کالاها (Excel)', validators=[
        DataRequired(message="فایل اطلاعات کالاها الزامی است."),
        FileAllowed(['xlsx', 'xls'], 'فقط فایل‌های Excel (xlsx, xls) مجاز هستند.')
    ])
    submit = SubmitField('آپلود و ذخیره اطلاعات کالاها')

class ItemForm(FlaskForm):
    """Form for adding/editing a single item manually."""
    document_number = IntegerField('شماره سند', validators=[DataRequired(), NumberRange(min=1)])
    invoice_number_ref = StringField('شماره صورتحساب', validators=[Optional(), Length(max=64)])
    document_date = DateField('تاریخ سند', format='%Y-%m-%d', validators=[DataRequired()])
    seller = StringField('فروشنده', validators=[Optional(), Length(max=128)])
    seller_province = StringField('استان فروشنده', validators=[Optional(), Length(max=128)])
    activity_type = StringField('نوع فعالیت', validators=[Optional(), Length(max=128)])
    origin = StringField('مبدا', validators=[Optional(), Length(max=128)])
    item_category = StringField('طبقه کالا', validators=[Optional(), Length(max=128)])
    product_id = StringField('شناسه کالا', validators=[DataRequired(), Length(max=64)])
    product_description = StringField('شرح کالا', validators=[Optional(), Length(max=256)])
    unit_of_measurement = StringField('واحد اندازه‌گیری', validators=[Optional(), Length(max=64)])
    quantity = IntegerField('تعداد / مقدار کالا', validators=[DataRequired(), NumberRange(min=0)])
    unit_price = FloatField('مبلغ واحد', validators=[DataRequired(), NumberRange(min=0.0)])
    submit = SubmitField('ذخیره کالا')

    def __init__(self, original_product_id=None, *args, **kwargs):
        super(ItemForm, self).__init__(*args, **kwargs)
        self.original_product_id = original_product_id

    def validate_product_id(self, product_id):
        if product_id.data != self.original_product_id:
            item = Item.query.filter_by(product_id=product_id.data).first()
            if item is not None:
                raise ValidationError('شناسه کالا قبلاً استفاده شده است. لطفاً یک شناسه کالا منحصر به فرد وارد کنید.')

class SettingsForm(FlaskForm):
    """Form for application settings."""
    start_invoice_number = IntegerField('شماره شروع فاکتور', validators=[DataRequired(message="شماره شروع فاکتور الزامی است."), NumberRange(min=1)])
    submit = SubmitField('ذخیره تنظیمات')