import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a-default-fallback-secret-key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') 
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Ensure these paths are correct for your project structure
    SCRIPT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__))) # Points to sjt_app directory
    UPLOAD_FOLDER = os.path.join(SCRIPT_DIR, 'uploads')
    OUTPUT_FILE = os.path.join(SCRIPT_DIR, "sjt.xlsm")

    # Create UPLOAD_FOLDER if it doesn't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    DEFAULT_START_INVOICE_NUMBER = 1901 # Initial default, will be read from DB if set