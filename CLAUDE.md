# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Amazon.de stock checker that monitors product pages for availability and sends push notifications via ntfy. Runs as a systemd service checking every 5 minutes.

## Commands

```bash
# Install/reinstall
./install.sh

# Run single check (testing)
./venv/bin/python amazon_checker.py --once

# Service management
systemctl start amazon-checker
systemctl stop amazon-checker
systemctl restart amazon-checker
systemctl status amazon-checker

# View logs
journalctl -u amazon-checker -f
```

## Architecture

**Main Components:**
- `amazon_checker.py` - Core `AmazonChecker` class that fetches pages, parses availability, and sends notifications
- `user_agents.py` - Browser header rotation with complete header sets (not just User-Agent strings)
- `config.yaml` - Products to monitor, ntfy URL, check interval, request settings

**Stock Detection Flow:**
1. Primary: Parse `#availability` div text
2. Secondary: Check `#outOfStockBuyBox_feature_div` presence
3. Tertiary: Look for `#add-to-cart-button`
4. Fallback: Full page text search for availability keywords

**Pattern Matching Note:** OUT_OF_STOCK patterns must be checked before IN_STOCK patterns because "nicht auf lager" contains "auf lager" as a substring.

**Notification Logic:** Only notifies on status *change* to IN_STOCK (prevents spam). State is in-memory only, so service restart triggers notification for any currently in-stock items.

## Configuration

Products are defined in `config.yaml`. Set `enabled: false` to disable without removing. The `check_interval` is in seconds with ±30s jitter applied.
