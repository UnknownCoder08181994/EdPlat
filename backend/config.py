import os

class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(BASE_DIR)
    STORAGE_DIR = os.path.join(PROJECT_ROOT, 'storage')
    DEBUG = True
