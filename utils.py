# utils.py
import logging
import json
import aiohttp
from config import DEFAULT_HEADERS

logger = logging.getLogger(__name__)

async def fetch_data(session, url, payload):
    """
    Helper function to make POST requests to APIs
    
    Args:
        session (aiohttp.ClientSession): The HTTP session to use
        url (str): The URL to make the request to
        payload (dict): The JSON payload to send
        
    Returns:
        dict or None: The JSON response data or None if there was an error
    """
    logger.info(f"Fetching data from {url} with payload: {json.dumps(payload)[:200]}")
    try:
        async with session.post(url, json=payload, headers=DEFAULT_HEADERS) as response:
            if response.status != 200:
                logger.error(f"Error response from API: {response.status}")
                try:
                    error_text = await response.text()
                    logger.error(f"Error response content: {error_text[:500]}")
                except:
                    pass
                return None
                
            try:
                data = await response.json()
                logger.debug(f"Response data: {json.dumps(data)[:500]}")
                return data
            except Exception as e:
                logger.error(f"Error parsing JSON: {e}")
                text = await response.text()
                logger.debug(f"Raw response: {text[:500]}")
                return None
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return None

async def safe_api_call(session, url, payload, error_message="API call failed"):
    """
    Make an API call with better error handling and logging
    
    Args:
        session (aiohttp.ClientSession): The HTTP session to use
        url (str): The URL to make the request to
        payload (dict): The JSON payload to send
        error_message (str): Custom error message to log
        
    Returns:
        tuple: (data, error) where data is the response data or None,
               and error is None or an error message
    """
    try:
        data = await fetch_data(session, url, payload)
        if data:
            return data, None
        return None, error_message
    except Exception as e:
        error_detail = f"{error_message}: {str(e)}"
        logger.error(error_detail)
        return None, error_detail

def extract_position_data(position):
    """
    Safely extract position data from various API response formats
    
    Args:
        position (dict): Position data from API
        
    Returns:
        dict: Standardized position data
    """
    try:
        # Default values
        position_data = {
            'coin': 'Unknown',
            'size': 0,
            'entry_price': 0,
            'leverage': 1,
            'unrealized_pnl': 0,
            'liquidation_price': 0
        }
        
        # Extract coin
        position_data['coin'] = position.get('coin', 'Unknown')
        
        # Extract position details
        pos_details = position.get('position', {})
        if not pos_details and 'szi' in position:
            # Handle direct format where position fields are at the top level
            pos_details = position
        
        # Safely extract numeric values
        try:
            position_data['size'] = float(pos_details.get('szi', 0))
        except (TypeError, ValueError):
            position_data['size'] = 0
            
        try:
            position_data['entry_price'] = float(pos_details.get('entryPx', 0))
        except (TypeError, ValueError):
            position_data['entry_price'] = 0
            
        try:
            position_data['leverage'] = float(pos_details.get('leverage', 1))
        except (TypeError, ValueError):
            position_data['leverage'] = 1
            
        try:
            position_data['unrealized_pnl'] = float(position.get('unrealizedPnl', 0))
        except (TypeError, ValueError):
            position_data['unrealized_pnl'] = 0
        
        # Extract liquidation price if available
        liquidation_px = 0.0
        if 'liquidationPx' in pos_details:
            liquidation_px = float(pos_details.get('liquidationPx', 0))
        
        position_data['liquidation_price'] = liquidation_px
        
        return position_data
    except Exception as e:
        logger.error(f"Error extracting position data: {e}")
        return None

def format_position_text(position_data, current_price):
    """
    Format position data into a readable string
    
    Args:
        position_data (dict): Standardized position data
        current_price (float): Current price of the asset
        
    Returns:
        str: Formatted position text for display
    """
    size = position_data['size']
    entry_px = position_data['entry_price']
    unrealized_pnl = position_data['unrealized_pnl']
    leverage = position_data['leverage']
    coin = position_data['coin']
    liquidation_price = position_data.get('liquidation_price', 0)
    
    # Calculate position metrics
    size_abs = abs(size)
    position_value = size_abs * current_price
    
    # Determine if long or short
    direction = "LONG" if size > 0 else "SHORT"
    
    # Calculate PnL percentage
    pnl_percentage = 0
    if position_value > 0:
        pnl_percentage = (unrealized_pnl / position_value) * 100
    
    # Calculate price change percentage
    price_change = ((current_price / entry_px) - 1) * 100 if entry_px > 0 else 0
    price_change_direction = "+" if price_change > 0 else ""
    
    # Format position information
    position_text = f"🪙 *{coin}*\n"
    position_text += f"Direction: {direction} {leverage}x\n"
    position_text += f"Size: {size_abs} {coin} (${position_value:.2f})\n"
    position_text += f"Entry Price: ${entry_px:.4f}\n"
    position_text += f"Current Price: ${current_price:.4f} ({price_change_direction}{price_change:.2f}%)\n"
    position_text += f"Unrealized PnL: ${unrealized_pnl:.2f} ({pnl_percentage:.2f}%)\n"
    
    # Add liquidation price if available and not a 1x long position
    is_one_x_long = (size > 0 and leverage <= 1)
    if liquidation_price > 0 and not is_one_x_long:
        position_text += f"Liquidation Price: ${liquidation_price:.4f}\n"
    
    return position_text

def format_wallet_address(wallet_address):
    """
    Format wallet address for display (truncate middle)
    
    Args:
        wallet_address (str): Full wallet address
        
    Returns:
        str: Truncated wallet address for display
    """
    if wallet_address and len(wallet_address) > 10:
        return f"{wallet_address[:6]}...{wallet_address[-4:]}"
    return wallet_address

def get_current_price(markets_data, coin):
    """
    Get the current price for a coin with case-insensitive fallback
    
    Args:
        markets_data (dict): Market data with coin prices
        coin (str): The coin to get the price for
        
    Returns:
        float: The current price or 0 if not found
    """
    if coin in markets_data:
        return float(markets_data.get(coin, 0))
    
    # Try case-insensitive search
    if coin != "Unknown":
        for market_coin, price in markets_data.items():
            if market_coin.upper() == coin.upper():
                return float(price)
    
    return 0.0