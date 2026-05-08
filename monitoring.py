# monitoring.py
import socket
import subprocess
import time
import requests
from ping3 import ping
from pysnmp.hlapi import *
from flask import current_app

def check_device_icmp(ip_address, timeout=2):
    """Check device via ICMP ping"""
    try:
        response_time = ping(ip_address, timeout=timeout)
        if response_time is not None and response_time > 0:
            return True, response_time * 1000  # convert to ms
        return False, None
    except Exception as e:
        return False, None

def check_device_tcp(ip_address, port, timeout=3):
    """Check device via TCP connection"""
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip_address, port))
        end_time = time.time()
        sock.close()
        if result == 0:
            response_ms = (end_time - start_time) * 1000
            return True, response_ms
        return False, None
    except Exception as e:
        return False, None

def check_device_http(ip_address, port=None, path='/', use_https=False, timeout=5):
    """Check device via HTTP/HTTPS request"""
    try:
        protocol = 'https' if use_https else 'http'
        url = f"{protocol}://{ip_address}"
        if port:
            url += f":{port}"
        url += path
        
        start_time = time.time()
        response = requests.get(url, timeout=timeout, verify=False)
        end_time = time.time()
        
        if response.status_code < 400:
            response_ms = (end_time - start_time) * 1000
            return True, response_ms
        return False, None
    except requests.RequestException:
        return False, None
    except Exception:
        return False, None

def check_device_snmp(ip_address, community='public', oid='1.3.6.1.2.1.1.1.0', timeout=3):
    """Check device via SNMP GET"""
    try:
        error_indication, error_status, error_index, var_binds = next(
            getCmd(SnmpEngine(),
                   CommunityData(community),
                   UdpTransportTarget((ip_address, 161), timeout=timeout),
                   ContextData(),
                   ObjectType(ObjectIdentity(oid)))
        )
        
        if error_indication:
            return False, None
        elif error_status:
            return False, None
        else:
            # SNMP response received, device is up
            return True, 10.0  # approximate response time
    except Exception:
        return False, None

def check_device(device):
    """Main function to check a device based on its configuration"""
    if not device.enabled:
        return None, None, "Device disabled"
    
    method = device.check_method
    ip = device.ip_address
    
    try:
        if method == 'icmp':
            success, response_time = check_device_icmp(ip, timeout=current_app.config.get('PING_TIMEOUT', 2))
            error_msg = None if success else "ICMP ping failed"
        elif method == 'tcp':
            if not device.check_port:
                return False, None, "TCP port not configured"
            success, response_time = check_device_tcp(ip, device.check_port, 
                                                      timeout=current_app.config.get('TCP_TIMEOUT', 3))
            error_msg = None if success else f"TCP connection to port {device.check_port} failed"
        elif method == 'http':
            success, response_time = check_device_http(ip, device.check_port, 
                                                        device.check_http_path or '/', 
                                                        use_https=False,
                                                        timeout=current_app.config.get('HTTP_TIMEOUT', 5))
            error_msg = None if success else "HTTP request failed"
        elif method == 'https':
            success, response_time = check_device_http(ip, device.check_port, 
                                                        device.check_http_path or '/', 
                                                        use_https=True,
                                                        timeout=current_app.config.get('HTTP_TIMEOUT', 5))
            error_msg = None if success else "HTTPS request failed"
        elif method == 'snmp':
            community = device.check_community or 'public'
            oid = device.snmp_oid or '1.3.6.1.2.1.1.1.0'
            success, response_time = check_device_snmp(ip, community, oid,
                                                        timeout=current_app.config.get('SNMP_TIMEOUT', 3))
            error_msg = None if success else "SNMP query failed"
        else:
            return False, None, f"Unknown check method: {method}"
        
        return success, response_time, error_msg
    except Exception as e:
        return False, None, str(e)