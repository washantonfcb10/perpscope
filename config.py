# config.py
import os
from dotenv import load_dotenv

# Try to load environment variables from .env file if it exists
load_dotenv(verbose=True)  # This will not fail if the file doesn't exist

print("Available environment variables:", list(os.environ.keys()))
print("Looking for TELEGRAM_BOT_TOKEN...")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
print(f"Token found: {TELEGRAM_BOT_TOKEN is not None}")
# Bot configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Add a fallback for local development if token isn't found
if not TELEGRAM_BOT_TOKEN:
    print("WARNING: No TELEGRAM_BOT_TOKEN found in environment variables.")
    print("Set this variable in your .env file for local development or in your hosting platform.")

# Hyperliquid API configuration
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
    "marginSummary": {"accountValue": "327916.95555", "totalNtlPos": "892655.67336", "totalRawUsd": "485816.62891", "totalMarginUsed": "248568.157786"}, 
    "crossMarginSummary": {"accountValue": "327916.95555", "totalNtlPos": "892655.67336", "totalRawUsd": "485816.62891", "totalMarginUsed": "248568.157786"}, 
    "assetPositions": [
        {
            "type": "oneWay", 
            "position": {
                "coin": "HYPE", 
                "szi": "-33546.92", 
                "leverage": {"type": "cross", "value": 3}, 
                "entryPx": "16.2323", 
                "positionValue": "525277.67336", 
                "unrealizedPnl": "19268.6216", 
                "liquidationPx": "20.8609356408"
            }
        }, 
        {
            "type": "oneWay", 
            "position": {
                "coin": "BERA", 
                "szi": "55000.0", 
                "leverage": {"type": "cross", "value": 5}, 
                "entryPx": "8.41613", 
                "positionValue": "367378.0", 
                "unrealizedPnl": "-95509.50483", 
                "liquidationPx": "2.565804512"
            }
        }
    ]
}

SAMPLE_MARKET_DATA = {
    "HYPE": 15.8555,
    "BERA": 6.6557
}