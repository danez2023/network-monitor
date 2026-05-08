#!/bin/bash
# deploy.sh

echo "=== Network Monitoring Software Installation ==="

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
sudo apt install -y python3 python3-pip python3-venv snmpd snmp

# Create application directory
sudo mkdir -p /opt/network-monitor
sudo chown $USER:$USER /opt/network-monitor

# Copy all files to /opt/network-monitor
# (Assuming you're in the directory with all the code)
cp -r ./* /opt/network-monitor/

# Create virtual environment
cd /opt/network-monitor
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install -r requirements.txt

# Create systemd service
sudo tee /etc/systemd/system/network-monitor.service > /dev/null <<EOF
[Unit]
Description=Network Monitor Flask Application
After=network.target

[Service]
User=$USER
WorkingDirectory=/opt/network-monitor
Environment="PATH=/opt/network-monitor/venv/bin"
ExecStart=/opt/network-monitor/venv/bin/python3 app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Start service
sudo systemctl daemon-reload
sudo systemctl enable network-monitor
sudo systemctl start network-monitor

echo "=== Installation Complete ==="
echo "The application is running on port 5000"
echo "Access it at: http://$(hostname -I | awk '{print $1}'):5000"
echo "Default login: admin / admin123"
echo ""
echo "To check status: sudo systemctl status network-monitor"
echo "To view logs: sudo journalctl -u network-monitor -f"