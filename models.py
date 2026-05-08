# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'admin' or 'user'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def set_password(self, password, bcrypt):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    
    def check_password(self, password, bcrypt):
        return bcrypt.check_password_hash(self.password_hash, password)

class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    device_type = db.Column(db.String(20), nullable=False)  # 'radio' or 'cctv'
    check_method = db.Column(db.String(20), nullable=False)  # 'icmp', 'tcp', 'http', 'https', 'snmp'
    check_port = db.Column(db.Integer, nullable=True)  # For TCP/HTTP/HTTPS
    check_http_path = db.Column(db.String(200), default='/')
    check_community = db.Column(db.String(50), nullable=True)  # SNMP community
    snmp_oid = db.Column(db.String(200), nullable=True)  # SNMP OID to check
    check_interval = db.Column(db.Integer, default=60)
    enabled = db.Column(db.Boolean, default=True)
    
    # Current status
    last_status = db.Column(db.String(10), default='unknown')  # 'up', 'down'
    last_check_time = db.Column(db.DateTime, nullable=True)
    last_response_time = db.Column(db.Float, nullable=True)  # milliseconds
    last_error_message = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    status_logs = db.relationship('StatusLog', backref='device', lazy='dynamic', cascade='all, delete-orphan')
    
    def get_current_uptime_percentage(self, hours=24):
        """Calculate uptime percentage for last N hours"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        logs = self.status_logs.filter(StatusLog.timestamp >= cutoff).order_by(StatusLog.timestamp).all()
        if not logs:
            return 100.0 if self.last_status == 'up' else 0.0
        
        total_seconds = hours * 3600
        up_seconds = 0
        last_time = cutoff
        last_status = 'unknown'
        
        for log in logs:
            if log.timestamp > last_time:
                if last_status == 'up':
                    up_seconds += (log.timestamp - last_time).total_seconds()
                last_time = log.timestamp
                last_status = log.status
        # Handle up to now
        if last_status == 'up':
            up_seconds += (datetime.utcnow() - last_time).total_seconds()
        
        return (up_seconds / total_seconds) * 100 if total_seconds > 0 else 100.0

class StatusLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False)
    status = db.Column(db.String(10), nullable=False)  # 'up', 'down'
    response_time = db.Column(db.Float, nullable=True)  # milliseconds
    error_message = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class SystemSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(200))
    
    @staticmethod
    def get_setting(key, default=None):
        setting = SystemSetting.query.filter_by(key=key).first()
        return setting.value if setting else default
    
    @staticmethod
    def set_setting(key, value, description=''):
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = SystemSetting(key=key, value=value, description=description)
            db.session.add(setting)
        db.session.commit()