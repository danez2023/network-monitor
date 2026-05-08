# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g
from flask_bcrypt import Bcrypt
from flask_login import login_user, logout_user, current_user, login_required
from functools import wraps
from datetime import datetime, timedelta
import json

from config import Config
from models import db, User, Device, StatusLog, SystemSetting
from monitoring import check_device
from scheduler import init_scheduler, schedule_device, reschedule_device_job
from auth import init_auth, login_manager

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
bcrypt = Bcrypt(app)
init_auth(app)

# Role-based access decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Create default admin user and settings
def init_db():
    with app.app_context():
        db.create_all()
        
        # Create default admin if none exists
        if User.query.count() == 0:
            admin = User(username='admin', email='admin@example.com', role='admin')
            admin.set_password('admin123', bcrypt)
            db.session.add(admin)
            db.session.commit()
            print("Default admin created: username='admin', password='admin123'")
        
        # Initialize system settings if not present
        if not SystemSetting.get_setting('cloud_endpoint_url'):
            SystemSetting.set_setting('cloud_endpoint_url', '', 'Cloud endpoint URL for forwarding')
            SystemSetting.set_setting('cloud_method', 'POST', 'HTTP method for forwarding (GET/POST)')
            SystemSetting.set_setting('cloud_auth_token', '', 'Bearer token for cloud authentication')
            db.session.commit()

@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password, bcrypt):
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    devices = Device.query.all()
    stats = {
        'total': Device.query.count(),
        'up': Device.query.filter_by(last_status='up').count(),
        'down': Device.query.filter_by(last_status='down').count(),
        'unknown': Device.query.filter_by(last_status='unknown').count()
    }
    return render_template('dashboard.html', devices=devices, stats=stats)

@app.route('/api/status')
@login_required
def api_status():
    """API endpoint for real-time status updates"""
    devices = []
    for device in Device.query.all():
        devices.append({
            'id': device.id,
            'name': device.name,
            'ip_address': device.ip_address,
            'device_type': device.device_type,
            'status': device.last_status or 'unknown',
            'response_time': device.last_response_time,
            'last_check': device.last_check_time.isoformat() if device.last_check_time else None,
            'error_message': device.last_error_message,
            'uptime_percentage': device.get_current_uptime_percentage(24) if device.last_check_time else 100
        })
    return jsonify({'devices': devices, 'timestamp': datetime.utcnow().isoformat()})

@app.route('/api/device/<int:device_id>/history')
@login_required
def api_device_history(device_id):
    """Get device status history for charts"""
    hours = request.args.get('hours', 24, type=int)
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    logs = StatusLog.query.filter(
        StatusLog.device_id == device_id,
        StatusLog.timestamp >= cutoff
    ).order_by(StatusLog.timestamp).all()
    
    history = [{
        'timestamp': log.timestamp.isoformat(),
        'status': log.status,
        'response_time': log.response_time
    } for log in logs]
    
    return jsonify(history)

@app.route('/devices')
@login_required
def devices():
    devices_list = Device.query.all()
    return render_template('devices.html', devices=devices_list)

@app.route('/device/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_device():
    if request.method == 'POST':
        device = Device(
            name=request.form['name'],
            ip_address=request.form['ip_address'],
            device_type=request.form['device_type'],
            check_method=request.form['check_method'],
            check_port=int(request.form['check_port']) if request.form.get('check_port') else None,
            check_http_path=request.form.get('check_http_path', '/'),
            check_community=request.form.get('check_community'),
            snmp_oid=request.form.get('snmp_oid'),
            check_interval=int(request.form.get('check_interval', 60)),
            enabled='enabled' in request.form
        )
        db.session.add(device)
        db.session.commit()
        
        # Schedule monitoring for this device
        from scheduler import schedule_device
        schedule_device(device)
        
        flash('Device added successfully.', 'success')
        return redirect(url_for('devices'))
    
    return render_template('device_form.html', device=None)

@app.route('/device/edit/<int:device_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_device(device_id):
    device = Device.query.get_or_404(device_id)
    
    if request.method == 'POST':
        device.name = request.form['name']
        device.ip_address = request.form['ip_address']
        device.device_type = request.form['device_type']
        device.check_method = request.form['check_method']
        device.check_port = int(request.form['check_port']) if request.form.get('check_port') else None
        device.check_http_path = request.form.get('check_http_path', '/')
        device.check_community = request.form.get('check_community')
        device.snmp_oid = request.form.get('snmp_oid')
        device.check_interval = int(request.form.get('check_interval', 60))
        device.enabled = 'enabled' in request.form
        
        db.session.commit()
        
        # Reschedule with new settings
        from scheduler import schedule_device
        schedule_device(device)
        
        flash('Device updated successfully.', 'success')
        return redirect(url_for('devices'))
    
    return render_template('device_form.html', device=device)

@app.route('/device/delete/<int:device_id>')
@login_required
@admin_required
def delete_device(device_id):
    device = Device.query.get_or_404(device_id)
    
    # Remove from scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from flask import current_app
    scheduler = current_app.config.get('scheduler')
    if scheduler:
        job_id = f"device_{device_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    
    db.session.delete(device)
    db.session.commit()
    flash('Device deleted successfully.', 'success')
    return redirect(url_for('devices'))

@app.route('/device/check/<int:device_id>')
@login_required
@admin_required
def manual_check(device_id):
    """Manually trigger a device check"""
    device = Device.query.get_or_404(device_id)
    from monitoring import check_device
    
    success, response_time, error_msg = check_device(device)
    new_status = 'up' if success else 'down'
    
    # Log the check
    log = StatusLog(
        device_id=device.id,
        status=new_status,
        response_time=response_time,
        error_message=error_msg,
        timestamp=datetime.utcnow()
    )
    
    # Update device
    old_status = device.last_status
    device.last_status = new_status
    device.last_check_time = datetime.utcnow()
    device.last_response_time = response_time
    device.last_error_message = error_msg
    
    db.session.add(log)
    db.session.commit()
    
    # Forward to cloud if status changed
    if old_status != new_status:
        from scheduler import forward_to_cloud
        forward_to_cloud(device, new_status, response_time, error_msg)
    
    flash(f'Manual check completed. Device is {new_status.upper()}.', 'info')
    return redirect(url_for('devices'))

@app.route('/logs')
@login_required
def logs():
    page = request.args.get('page', 1, type=int)
    device_id = request.args.get('device_id', type=int)
    
    query = StatusLog.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    
    logs_paginated = query.order_by(StatusLog.timestamp.desc()).paginate(page=page, per_page=50)
    devices = Device.query.all()
    
    return render_template('logs.html', logs=logs_paginated, devices=devices, selected_device=device_id)

@app.route('/users')
@login_required
@admin_required
def users():
    users_list = User.query.all()
    return render_template('users.html', users=users_list)

@app.route('/user/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    if request.method == 'POST':
        user = User(
            username=request.form['username'],
            email=request.form['email'],
            role=request.form['role']
        )
        user.set_password(request.form['password'], bcrypt)
        db.session.add(user)
        db.session.commit()
        flash('User added successfully.', 'success')
        return redirect(url_for('users'))
    
    return render_template('user_form.html', user=None)

@app.route('/user/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.username = request.form['username']
        user.email = request.form['email']
        user.role = request.form['role']
        if request.form.get('password'):
            user.set_password(request.form['password'], bcrypt)
        
        db.session.commit()
        flash('User updated successfully.', 'success')
        return redirect(url_for('users'))
    
    return render_template('user_form.html', user=user)

@app.route('/user/delete/<int:user_id>')
@login_required
@admin_required
def delete_user(user_id):
    # Prevent deleting yourself
    if user_id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('users'))
    
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully.', 'success')
    return redirect(url_for('users'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        # Update cloud forwarding settings
        SystemSetting.set_setting('cloud_endpoint_url', request.form.get('cloud_endpoint_url', ''))
        SystemSetting.set_setting('cloud_method', request.form.get('cloud_method', 'POST'))
        SystemSetting.set_setting('cloud_auth_token', request.form.get('cloud_auth_token', ''))
        flash('Settings updated successfully.', 'success')
        return redirect(url_for('settings'))
    
    cloud_endpoint_url = SystemSetting.get_setting('cloud_endpoint_url', '')
    cloud_method = SystemSetting.get_setting('cloud_method', 'POST')
    cloud_auth_token = SystemSetting.get_setting('cloud_auth_token', '')
    
    return render_template('settings.html', 
                          cloud_endpoint_url=cloud_endpoint_url,
                          cloud_method=cloud_method,
                          cloud_auth_token=cloud_auth_token)

if __name__ == '__main__':
    init_db()
    
    # Initialize scheduler after app is ready
    with app.app_context():
        from scheduler import init_scheduler
        init_scheduler(app)
        # Store scheduler in app config for access in routes
        from scheduler import scheduler
        app.config['scheduler'] = scheduler
    
    app.run(host='0.0.0.0', port=5000, debug=True)