# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file (for local development only)
load_dotenv()

# Get the token from environment variables
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

# Print debug information safely
print("Looking for TELEGRAM_BOT_TOKEN...")
print(f"Token found: {bool(TELEGRAM_BOT_TOKEN)}")

if not TELEGRAM_BOT_TOKEN:
    print("WARNING: No TELEGRAM_BOT_TOKEN found in environment variables.")
    print("Set this variable in your .env file for local development or in your hosting platform.")

# Bot configuration
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_API_V2_URL = "https://api-v2.hyperliquid.xyz"

# Headers for API requests
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}

# Alert configuration
ALERT_CHECK_INTERVAL = 60  # seconds

# Endpoint configurations
API_ENDPOINTS = {
    "clearinghouse": {"url": HYPERLIQUID_API_URL, "payload_type": "clearinghouseState"},
    "userState": {"url": HYPERLIQUID_API_URL, "payload_type": "userState"},
    "positions": {"url": HYPERLIQUID_API_URL, "payload_type": "positions"},
    "accountState": {"url": HYPERLIQUID_API_URL, "payload_type": "accountState"},
    "marginDetails": {"url": HYPERLIQUID_API_URL, "payload_type": "marginDetails"},
    "fundingHistory": {"url": HYPERLIQUID_API_URL, "payload_type": "fundingHistory"},
    "allMids": {"url": HYPERLIQUID_API_URL, "payload_type": "allMids"},
    "v2_positions": {"url": f"{HYPERLIQUID_API_V2_URL}/info/positions"}
}

# Sample data for development and testing
SAMPLE_ACCOUNT_DATA = {
    # Your sample data here
}

SAMPLE_MARKET_DATA = {
    "HYPE": 15.8555,
    "BERA": 6.6557
}