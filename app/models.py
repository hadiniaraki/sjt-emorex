from app.extensions import db, login  # اضافه کردن login به imports
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(256))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    document_number = db.Column(db.String(64))
    invoice_number_ref = db.Column(db.String(64))
    document_date = db.Column(db.Date, nullable=False)
    seller = db.Column(db.String(128))
    seller_province = db.Column(db.String(64))
    activity_type = db.Column(db.String(64))
    origin = db.Column(db.String(64))
    item_category = db.Column(db.String(64))
    product_description = db.Column(db.String(256))
    unit_of_measurement = db.Column(db.String(32))
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    final_amount = db.Column(db.Float)
    product_id = db.Column(db.String(128), unique=True, nullable=False)
    remarks = db.Column(db.Text, nullable=True)
    remaining_quantity = db.Column(db.Integer, nullable=False, default=0)  
    
    usages = db.relationship('ItemUsageLog', backref='item', lazy='dynamic', cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Item {self.product_id}>'

class ItemUsageLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    exit_date = db.Column(db.Date, default=datetime.utcnow)
    invoice_number_used = db.Column(db.String(64), nullable=False)
    quantity_used = db.Column(db.Integer, nullable=False)
    price_at_usage = db.Column(db.Float)

    def __repr__(self):
        return f'<ItemUsageLog Item_ID:{self.item_id} Qty:{self.quantity_used}>'

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    setting_name = db.Column(db.String(64), unique=True, nullable=False)
    setting_value = db.Column(db.String(256), nullable=False)

    def __repr__(self):
        return f'<Settings {self.setting_name}: {self.setting_value}>'

@login.user_loader
def load_user(id):
    return User.query.get(int(id))