# scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import current_app
from models import db, Device, StatusLog, SystemSetting
from monitoring import check_device
import requests
from datetime import datetime
import json

scheduler = BackgroundScheduler()

def forward_to_cloud(device, status, response_time, error_msg):
    """Forward device status to cloud endpoint via GET or POST"""
    cloud_url = SystemSetting.get_setting('cloud_endpoint_url', '')
    if not cloud_url:
        return
    
    method = SystemSetting.get_setting('cloud_method', 'POST').upper()
    auth_token = SystemSetting.get_setting('cloud_auth_token', '')
    
    payload = {
        'device_id': device.id,
        'device_name': device.name,
        'device_type': device.device_type,
        'ip_address': device.ip_address,
        'status': status,
        'response_time_ms': response_time,
        'error_message': error_msg,
        'timestamp': datetime.utcnow().isoformat(),
        'check_method': device.check_method
    }
    
    headers = {}
    if auth_token:
        headers['Authorization'] = f'Bearer {auth_token}'
    
    try:
        if method == 'POST':
            response = requests.post(cloud_url, json=payload, headers=headers, timeout=5)
        else:  # GET
            response = requests.get(cloud_url, params=payload, headers=headers, timeout=5)
        
        if response.status_code >= 400:
            current_app.logger.error(f"Cloud forwarding failed: {response.status_code}")
    except Exception as e:
        current_app.logger.error(f"Cloud forwarding exception: {str(e)}")

def monitor_device(device_id):
    """Background job to monitor a single device"""
    with current_app.app_context():
        device = Device.query.get(device_id)
        if not device or not device.enabled:
            return
        
        # Perform the check
        success, response_time, error_msg = check_device(device)
        new_status = 'up' if success else 'down'
        
        # Log the status
        log = StatusLog(
            device_id=device.id,
            status=new_status,
            response_time=response_time,
            error_message=error_msg,
            timestamp=datetime.utcnow()
        )
        db.session.add(log)
        
        # Check if status changed
        status_changed = (device.last_status != new_status)
        
        # Update device record
        device.last_status = new_status
        device.last_check_time = datetime.utcnow()
        device.last_response_time = response_time
        device.last_error_message = error_msg if error_msg else None
        db.session.commit()
        
        # Forward to cloud if status changed
        if status_changed and new_status in ['up', 'down']:
            forward_to_cloud(device, new_status, response_time, error_msg)
        
        # Reschedule job with custom interval (in case interval was changed)
        reschedule_device_job(device)

def schedule_device(device):
    """Schedule monitoring job for a device"""
    job_id = f"device_{device.id}"
    trigger = IntervalTrigger(seconds=device.check_interval)
    
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    scheduler.add_job(
        func=monitor_device,
        trigger=trigger,
        args=[device.id],
        id=job_id,
        replace_existing=True
    )

def reschedule_device_job(device):
    """Reschedule device job (used when interval changes)"""
    schedule_device(device)

def schedule_all_devices():
    """Schedule monitoring for all enabled devices"""
    with current_app.app_context():
        devices = Device.query.filter_by(enabled=True).all()
        for device in devices:
            schedule_device(device)

def init_scheduler(app):
    """Initialize and start the background scheduler"""
    scheduler.start()
    
    # Schedule all devices
    with app.app_context():
        schedule_all_devices()
    
    # Shutdown scheduler on app teardown
    import atexit
    atexit.register(lambda: scheduler.shutdown())