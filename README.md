# Amazon Stock Checker

Monitors Amazon.de product pages for stock availability and sends push notifications via [ntfy](https://ntfy.sh).

## Features

- Monitors multiple products simultaneously
- Push notifications when items come back in stock
- Runs as a systemd service (checks every 5 minutes)
- Rotates browser headers to avoid detection
- Only notifies on status *change* to prevent spam

## Installation

```bash
./install.sh
```

This creates a Python virtual environment, installs dependencies, and sets up the systemd service.

## Configuration

1. Copy `.env.example` to `.env` and set your ntfy URL:
```bash
cp .env.example .env
# Edit .env with your ntfy topic URL
```

2. Edit `config.yaml` to add products:
```yaml
products:
  - name: "Product Name"
    url: "https://www.amazon.de/dp/PRODUCT_ID/"
    enabled: true
```

## Usage

```bash
# Test single check
./venv/bin/python amazon_checker.py --once

# Service management
systemctl start amazon-checker
systemctl status amazon-checker
journalctl -u amazon-checker -f
```

## How It Works

1. Fetches product pages with rotating browser headers
2. Parses availability from multiple page elements
3. Tracks stock status changes in memory
4. Sends ntfy notification only when status changes to "in stock"
