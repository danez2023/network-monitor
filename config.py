# config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///network_monitor.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Cloud forwarding settings (defaults, can be changed via UI)
    CLOUD_ENDPOINT_URL = os.environ.get('CLOUD_ENDPOINT_URL', '')
    CLOUD_METHOD = os.environ.get('CLOUD_METHOD', 'POST')  # GET or POST
    CLOUD_AUTH_TOKEN = os.environ.get('CLOUD_AUTH_TOKEN', '')
    
    # Monitoring settings
    DEFAULT_CHECK_INTERVAL = 60  # seconds
    PING_TIMEOUT = 2
    TCP_TIMEOUT = 3
    HTTP_TIMEOUT = 5
    SNMP_TIMEOUT = 3