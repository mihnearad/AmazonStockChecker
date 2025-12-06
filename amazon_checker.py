#!/usr/bin/env python3
"""
Amazon.de Stock Checker Service

Monitors Amazon.de product pages for stock availability and sends
notifications via ntfy when products become available.
"""

import logging
import os
import sys
import time
import random
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

import requests
from bs4 import BeautifulSoup
import yaml

from user_agents import get_random_headers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class StockStatus(Enum):
    """Product stock status enumeration."""
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    TEMPORARILY_OUT = "temporarily_out"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class Product:
    """Product information container."""
    name: str
    url: str
    enabled: bool = True
    last_status: StockStatus = StockStatus.UNKNOWN


@dataclass
class CheckResult:
    """Result of a stock check."""
    product: Product
    status: StockStatus
    message: str
    price: Optional[str] = None


class AmazonChecker:
    """Amazon.de stock availability checker."""

    # German and English text patterns for stock detection
    # IMPORTANT: Check OUT_OF_STOCK before IN_STOCK because "nicht auf lager" contains "auf lager"
    OUT_OF_STOCK_PATTERNS = [
        "derzeit nicht auf lager",
        "nicht auf lager",
        "derzeit nicht verfügbar",
        "currently unavailable",
        "nicht verfügbar",
        "not available",
        "currently not in stock",
    ]

    TEMPORARILY_OUT_PATTERNS = [
        "vorübergehend nicht verfügbar",
        "temporarily out of stock",
        "vorübergehend nicht auf lager",
    ]

    IN_STOCK_PATTERNS = [
        "auf lager",
        "in stock",
        "versandfertig",
        "lieferbar",
        "sofort lieferbar",
    ]

    def __init__(self, config_path: str = "config.yaml"):
        """Initialize the checker with configuration."""
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.products = self._load_products()
        self.last_notified: Dict[str, StockStatus] = {}

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            logger.error(f"Configuration file not found: {self.config_path}")
            sys.exit(1)

        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _load_products(self) -> list[Product]:
        """Load products from configuration."""
        products = []
        for p in self.config.get('products', []):
            if p.get('enabled', True):
                products.append(Product(
                    name=p['name'],
                    url=p['url'],
                    enabled=p.get('enabled', True)
                ))
        logger.info(f"Loaded {len(products)} enabled products to monitor")
        return products

    def _normalize_url(self, url: str) -> str:
        """Normalize Amazon URL to standard format."""
        if '/ref=' in url:
            url = url.split('/ref=')[0]
        url = url.rstrip('/')
        return url

    def _add_random_delay(self):
        """Add random delay between requests to avoid detection."""
        delay = random.uniform(2, 5)
        time.sleep(delay)

    def _fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch product page with anti-detection measures.
        Returns HTML content or None on error.
        """
        headers = get_random_headers()
        timeout = self.config.get('request', {}).get('timeout', 30)
        max_retries = self.config.get('request', {}).get('max_retries', 3)
        retry_delay = self.config.get('request', {}).get('retry_delay', 10)

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True
                )
                response.raise_for_status()

                # Check for CAPTCHA page
                if len(response.text) < 10000:
                    if 'captcha' in response.text.lower() or 'robot' in response.text.lower():
                        logger.warning(f"CAPTCHA detected on attempt {attempt + 1}")
                        if attempt < max_retries - 1:
                            time.sleep(retry_delay * (attempt + 1))
                            headers = get_random_headers()
                            continue
                        return None

                return response.text

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1} for {url}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error on attempt {attempt + 1}: {e}")

            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        return None

    def _parse_availability(self, html: str) -> tuple[StockStatus, str]:
        """
        Parse product page HTML to determine stock status.
        Returns tuple of (StockStatus, message).
        """
        soup = BeautifulSoup(html, 'lxml')

        # Primary method: Check #availability div
        availability_div = soup.find('div', {'id': 'availability'})
        if availability_div:
            availability_text = availability_div.get_text(strip=True).lower()

            # Check for temporarily out of stock first (more specific)
            for pattern in self.TEMPORARILY_OUT_PATTERNS:
                if pattern in availability_text:
                    return StockStatus.TEMPORARILY_OUT, availability_div.get_text(strip=True)

            # Check for general out of stock
            for pattern in self.OUT_OF_STOCK_PATTERNS:
                if pattern in availability_text:
                    return StockStatus.OUT_OF_STOCK, availability_div.get_text(strip=True)

            # Check for in stock
            for pattern in self.IN_STOCK_PATTERNS:
                if pattern in availability_text:
                    return StockStatus.IN_STOCK, availability_div.get_text(strip=True)

        # Secondary method: Check for outOfStock buybox
        out_of_stock_box = soup.find('div', {'id': 'outOfStockBuyBox_feature_div'})
        if out_of_stock_box and out_of_stock_box.get_text(strip=True):
            return StockStatus.OUT_OF_STOCK, "Out of stock (buybox)"

        # Tertiary method: Check for add-to-cart button
        add_to_cart = soup.find('input', {'id': 'add-to-cart-button'})
        if add_to_cart:
            return StockStatus.IN_STOCK, "Add to cart button present"

        # Check for "Add to List" only (no buy option = out of stock)
        add_to_list = soup.find('input', {'id': 'add-to-wishlist-button-submit'})
        if add_to_list and not add_to_cart:
            return StockStatus.OUT_OF_STOCK, "Only wishlist available"

        # Fallback: Search entire page for availability keywords
        page_text = soup.get_text().lower()

        for pattern in self.TEMPORARILY_OUT_PATTERNS:
            if pattern in page_text:
                return StockStatus.TEMPORARILY_OUT, f"Found: {pattern}"

        for pattern in self.OUT_OF_STOCK_PATTERNS:
            if pattern in page_text:
                return StockStatus.OUT_OF_STOCK, f"Found: {pattern}"

        for pattern in self.IN_STOCK_PATTERNS:
            if pattern in page_text:
                return StockStatus.IN_STOCK, f"Found: {pattern}"

        return StockStatus.UNKNOWN, "Could not determine availability"

    def _extract_price(self, html: str) -> Optional[str]:
        """Extract product price if available."""
        soup = BeautifulSoup(html, 'lxml')

        price_whole = soup.find('span', {'class': 'a-price-whole'})
        price_fraction = soup.find('span', {'class': 'a-price-fraction'})

        if price_whole:
            price = price_whole.get_text(strip=True).rstrip(',').rstrip('.')
            if price_fraction:
                price += ',' + price_fraction.get_text(strip=True)
            return f"{price} EUR"

        return None

    def check_product(self, product: Product) -> CheckResult:
        """Check stock status for a single product."""
        logger.info(f"Checking: {product.name}")

        url = self._normalize_url(product.url)
        html = self._fetch_page(url)

        if html is None:
            return CheckResult(
                product=product,
                status=StockStatus.ERROR,
                message="Failed to fetch page"
            )

        status, message = self._parse_availability(html)
        price = self._extract_price(html) if status == StockStatus.IN_STOCK else None

        logger.info(f"  Status: {status.value} - {message}")

        return CheckResult(
            product=product,
            status=status,
            message=message,
            price=price
        )

    def _get_ntfy_url(self) -> Optional[str]:
        """Get ntfy URL from environment variable or config."""
        return os.environ.get('NTFY_URL') or self.config.get('notification', {}).get('ntfy_url')

    def send_notification(self, result: CheckResult):
        """Send notification via ntfy."""
        ntfy_url = self._get_ntfy_url()
        if not ntfy_url:
            logger.warning("No ntfy URL configured, skipping notification")
            return

        # Determine notification priority and tags
        if result.status == StockStatus.IN_STOCK:
            priority = "urgent"
            tags = "white_check_mark,package"
            title = f"IN STOCK: {result.product.name}"
        else:
            priority = "default"
            tags = "warning"
            title = f"Stock Alert: {result.product.name}"

        # Build message body
        message = f"{result.message}"
        if result.price:
            message += f"\nPrice: {result.price}"
        message += f"\n\n{result.product.url}"

        headers = {
            "Title": title,
            "Priority": priority,
            "Tags": tags,
            "Click": result.product.url,
            "User-Agent": "AmazonStockChecker/1.0",
            "Content-Type": "text/plain; charset=utf-8",
        }

        try:
            response = requests.post(
                ntfy_url,
                data=message.encode('utf-8'),
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"Notification sent for {result.product.name}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send notification: {e}")

    def should_notify(self, result: CheckResult) -> bool:
        """Determine if notification should be sent based on status change."""
        product_key = result.product.url
        last_status = self.last_notified.get(product_key)

        # Always notify if product is now in stock
        if result.status == StockStatus.IN_STOCK:
            if last_status != StockStatus.IN_STOCK:
                return True

        # Optionally notify on errors
        notify_on_error = self.config.get('notification', {}).get('notify_on_error', False)
        if result.status == StockStatus.ERROR and notify_on_error:
            return True

        return False

    def check_all_products(self):
        """Check all enabled products."""
        logger.info(f"Starting check cycle for {len(self.products)} products")

        for i, product in enumerate(self.products):
            if i > 0:
                self._add_random_delay()

            result = self.check_product(product)

            if self.should_notify(result):
                self.send_notification(result)

            # Update last known status
            self.last_notified[product.url] = result.status

        logger.info("Check cycle complete")

    def run_forever(self):
        """Run the checker in continuous loop."""
        check_interval = self.config.get('check_interval', 300)
        logger.info(f"Starting Amazon Stock Checker (interval: {check_interval}s)")

        # Send startup notification
        startup_msg = f"Amazon Stock Checker started. Monitoring {len(self.products)} products."
        try:
            ntfy_url = self._get_ntfy_url()
            if ntfy_url:
                requests.post(
                    ntfy_url,
                    data=startup_msg.encode('utf-8'),
                    headers={
                        "Title": "Stock Checker Started",
                        "Priority": "low",
                        "Tags": "rocket",
                        "User-Agent": "AmazonStockChecker/1.0",
                        "Content-Type": "text/plain; charset=utf-8",
                    },
                    timeout=10
                )
        except Exception:
            pass

        while True:
            try:
                self.check_all_products()
            except Exception as e:
                logger.error(f"Error during check cycle: {e}", exc_info=True)

            # Add some randomness to the interval
            jitter = random.uniform(-30, 30)
            sleep_time = max(60, check_interval + jitter)
            logger.info(f"Sleeping for {sleep_time:.0f} seconds")
            time.sleep(sleep_time)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Amazon.de Stock Checker')
    parser.add_argument(
        '-c', '--config',
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run once and exit (for testing)'
    )
    args = parser.parse_args()

    checker = AmazonChecker(config_path=args.config)

    if args.once:
        checker.check_all_products()
    else:
        checker.run_forever()


if __name__ == '__main__':
    main()
