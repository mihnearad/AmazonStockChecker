#!/bin/bash
set -e

PROJECT_DIR="/root/AmazonStockChecker"

echo "=== Amazon Stock Checker Installation ==="

# Check Python version
echo "Python version:"
python3 --version

# Create virtual environment
echo ""
echo "Creating virtual environment..."
python3 -m venv "$PROJECT_DIR/venv"

# Activate and install dependencies
echo "Installing dependencies..."
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# Copy systemd service file
echo ""
echo "Installing systemd service..."
cp "$PROJECT_DIR/amazon-checker.service" /etc/systemd/system/

# Reload systemd
systemctl daemon-reload

# Enable service (but don't start yet)
systemctl enable amazon-checker.service

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "1. Test with: $PROJECT_DIR/venv/bin/python $PROJECT_DIR/amazon_checker.py --once"
echo "2. Start service: systemctl start amazon-checker"
echo "3. Check status: systemctl status amazon-checker"
echo "4. View logs: journalctl -u amazon-checker -f"
