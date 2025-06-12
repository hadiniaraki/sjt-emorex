import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') 
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    UPLOAD_FOLDER = os.path.join(SCRIPT_DIR, 'uploads')
    OUTPUT_FILE = os.path.join(SCRIPT_DIR, "sjt.xlsm") 
    DEFAULT_START_INVOICE_NUMBER = 1901
    ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'xlsm'}