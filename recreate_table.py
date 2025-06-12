# recreate_table.py (نسخه نهایی و کامل)
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("خطا: DATABASE_URL در .env یافت نشد.")
else:
    # ✅ تعریف دستورات SQL با ترتیب صحیح
    
    # دستور اول: حذف جدول فرزند
    drop_log_table = text("DROP TABLE IF EXISTS item_usage_log;")
    
    # دستور دوم: حذف جدول مادر
    drop_item_table = text("DROP TABLE IF EXISTS item;")

    # دستور سوم: ایجاد مجدد جدول مادر
    create_item_table = text("""
    CREATE TABLE item (
        id INT AUTO_INCREMENT PRIMARY KEY,
        document_number VARCHAR(64),
        invoice_number_ref VARCHAR(64),
        document_date DATE NOT NULL,
        seller VARCHAR(128),
        seller_province VARCHAR(64),
        activity_type VARCHAR(64),
        origin VARCHAR(64),
        item_category VARCHAR(64),
        product_description VARCHAR(256),
        unit_of_measurement VARCHAR(32),
        quantity INT NOT NULL,
        unit_price FLOAT NOT NULL,
        final_amount FLOAT,
        product_id VARCHAR(128) NOT NULL UNIQUE,
        remarks TEXT
    );
    """)

    # دستور چهارم: ایجاد مجدد جدول فرزند با کلید خارجی
    create_log_table = text("""
    CREATE TABLE item_usage_log (
        id INT AUTO_INCREMENT PRIMARY KEY,
        item_id INT NOT NULL,
        exit_date DATE,
        invoice_number_used VARCHAR(64) NOT NULL,
        quantity_used INT NOT NULL,
        price_at_usage FLOAT,
        FOREIGN KEY (item_id) REFERENCES item(id) ON DELETE CASCADE
    );
    """)

    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as connection:
            print("اتصال به دیتابیس برقرار شد...")
            
            # غیرفعال کردن موقت بررسی کلید خارجی برای حذف امن
            connection.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
            
            print("در حال حذف جدول 'item_usage_log'...")
            connection.execute(drop_log_table)
            
            print("در حال حذف جدول 'item'...")
            connection.execute(drop_item_table)

            # فعال کردن مجدد بررسی کلید خارجی
            connection.execute(text("SET FOREIGN_KEY_CHECKS=1;"))

            print("در حال ایجاد مجدد جدول 'item'...")
            connection.execute(create_item_table)

            print("در حال ایجاد مجدد جدول 'item_usage_log'...")
            connection.execute(create_log_table)
            
            connection.commit()
            
            print("\nعملیات با موفقیت انجام شد!")
            print("هر دو جدول با ساختار صحیح و ارتباط کلید خارجی مجدداً ایجاد شدند.")

    except Exception as e:
        # در صورت بروز خطا، اتصال را به حالت اولیه برمی‌گردانیم
        with engine.connect() as connection:
            connection.execute(text("SET FOREIGN_KEY_CHECKS=1;"))
        print(f"\nخطا در هنگام اجرای عملیات: {e}")