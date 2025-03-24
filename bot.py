# bot.py
import logging
import os
import json
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, BotCommand
from telegram.ext import Application, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, filters

# Import our custom modules
import utils
import config
from position_tracker import set_api_functions as set_position_tracker_functions
from price_alerts import set_api_functions as set_price_alerts_functions
from price_alerts import setup_alerts, alert_manager

# Configure detailed logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Print startup message
print("Bot is starting...")
logger.info("Bot is initializing...")

# Validate bot token
from config import TELEGRAM_BOT_TOKEN  # Make sure this import is correct
if TELEGRAM_BOT_TOKEN:
    masked_token = TELEGRAM_BOT_TOKEN[:4] + "..." + TELEGRAM_BOT_TOKEN[-4:]
    print(f"Bot token loaded: {masked_token}")
    logger.info(f"Bot token loaded: {masked_token}")
else:
    print("ERROR: No bot token found in environment variables!")
    logger.error("No bot token found in environment variables")
    exit(1)

# Function to get main menu as inline buttons with improved layout
def get_main_menu_markup():
    """Create the main menu with inline buttons in a 2-column layout"""
    keyboard = [
        [
            InlineKeyboardButton("📊 Positions", callback_data="view_portfolio"),
            InlineKeyboardButton("👁️ My Wallets", callback_data="view_wallets")
        ],
        [
            InlineKeyboardButton("➕ Track Wallet", callback_data="track_wallet"),
            InlineKeyboardButton("⚙️ Settings", callback_data="settings")
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_data"),
            InlineKeyboardButton("❌ Close", callback_data="close_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# Define an inline keyboard for navigation
def get_back_button(back_to="show_main_menu", text="◀️ Back to Menu"):
    """Create a back button for navigation"""
    keyboard = [[InlineKeyboardButton(text, callback_data=back_to)]]
    return InlineKeyboardMarkup(keyboard)

# API function implementations
async def  get_account_info(wallet_address):
    """
    Fetch account information for a given wallet address with multiple fallback methods
    
    Args:
        wallet_address (str): The wallet address to fetch info for
        
    Returns:
        dict: Account information including positions and margin data
    """
    logger.info(f"Getting account info for wallet: {wallet_address}")
    
    # Try the V2 API endpoint first
    try:
        async with aiohttp.ClientSession() as session:
            endpoint = config.API_ENDPOINTS["v2_positions"]["url"]
            payload = {"address": wallet_address}
            
            async with session.post(endpoint, json=payload, headers=config.DEFAULT_HEADERS) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"New API V2 positions response received")
                    
                    if data and isinstance(data, list):
                        asset_positions = []
                        for pos in data:
                            asset_position = {
                                "coin": pos.get("coin", "Unknown"),
                                "position": {
                                    "coin": pos.get("coin", "Unknown"),
                                    "szi": pos.get("szi", 0),
                                    "entryPx": pos.get("entryPx", 0),
                                    "leverage": pos.get("leverage", 1)
                                },
                                "unrealizedPnl": pos.get("unrealizedPnl", 0)
                            }
                            asset_positions.append(asset_position)
                        
                        return {"assetPositions": asset_positions}
    except Exception as e:
        logger.error(f"Error with V2 API: {e}")
    
    # If V2 API failed, try the original approach
    try:
        async with aiohttp.ClientSession() as session:
            endpoint_info = config.API_ENDPOINTS["clearinghouse"]
            payload = {"type": endpoint_info["payload_type"], "user": wallet_address}
            
            data = await utils.fetch_data(session, endpoint_info["url"], payload)
            
            if data and isinstance(data, dict) and 'assetPositions' in data:
                logger.info(f"Found data using clearinghouseState endpoint")
                return data
    except Exception as e:
        logger.error(f"Error with clearinghouseState endpoint: {e}")
    
    # Try scraping approach as a third option
    try:
        result = await scrape_hyperliquid_data(wallet_address)
        if result:
            return result
    except Exception as e:
        logger.error(f"Error with scraping approach: {e}")
    
    # If all API calls fail, use the sample data for development/testing
    logger.warning("Using sample data as fallback")
    return config.SAMPLE_ACCOUNT_DATA

async def get_market_data():
    """
    Fetch current market data for all available assets
    
    Returns:
        dict: A dictionary mapping coin symbols to their current prices
              Example: {'BTC': 50000.0, 'ETH': 2800.0}
    """
    logger.info("Getting market data")
    async with aiohttp.ClientSession() as session:
        endpoint_info = config.API_ENDPOINTS["allMids"]
        payload = {"type": endpoint_info["payload_type"]}
        
        data = await utils.fetch_data(session, endpoint_info["url"], payload)
        
        if not data:
            # Fallback to sample market data
            logger.warning("Using sample market data as fallback")
            return config.SAMPLE_MARKET_DATA
        
        return data

async def scrape_hyperliquid_data(wallet_address):
    """
    Scrape data from Hyperliquid by trying multiple API endpoints
    
    Args:
        wallet_address (str): The wallet address to fetch data for
        
    Returns:
        dict or None: Combined position data or None if unsuccessful
    """
    try:
        async with aiohttp.ClientSession() as session:
            all_data = {}
            
            # Try all possible endpoints
            for endpoint_key, endpoint_info in config.API_ENDPOINTS.items():
                # Skip v2 endpoints that have different format
                if endpoint_key.startswith("v2_"):
                    continue
                    
                try:
                    url = endpoint_info["url"]
                    payload_type = endpoint_info.get("payload_type")
                    
                    if payload_type:
                        payload = {"type": payload_type, "user": wallet_address}
                        
                        async with session.post(url, json=payload, headers=config.DEFAULT_HEADERS) as response:
                            if response.status == 200:
                                data = await response.json()
                                logger.debug(f"{payload_type} API response received")
                                all_data[payload_type] = data
                except Exception as e:
                    logger.error(f"Error with {endpoint_key} endpoint: {e}")
            
            # Extract and combine position data
            combined_positions = []
            pnl_by_coin = {}
            
            # Process each data source to build a complete picture
            for source_type, data in all_data.items():
                if source_type == "positions" and isinstance(data, list):
                    for position in data:
                        if "coin" in position and "unrealizedPnl" in position:
                            coin = position["coin"]
                            pnl_by_coin[coin] = float(position.get("unrealizedPnl", 0))
                
                if source_type in ["userState", "clearinghouseState", "accountState"] and isinstance(data, dict) and "assetPositions" in data:
                    for position in data["assetPositions"]:
                        coin = position.get("coin", "Unknown")
                        # Add PnL data from other sources if available
                        if coin in pnl_by_coin and ("unrealizedPnl" not in position or float(position.get("unrealizedPnl", 0)) == 0):
                            position["unrealizedPnl"] = pnl_by_coin[coin]
                        
                        combined_positions.append(position)
            
            # If we found any positions, return them in a structured format
            if combined_positions:
                return {"assetPositions": combined_positions}
            
            return None
            
    except Exception as e:
        logger.error(f"Error in scraping: {e}")
        return None

# Function to show the main menu with improved formatting
async def show_main_menu(update: Update, context: CallbackContext):
    """Show the main menu with inline buttons and better formatting"""
    
    menu_text = (
        "Track and monitor your Hyperliquid positions.\n\n"
        "Select an option below:"
    )
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                menu_text,
                reply_markup=get_main_menu_markup(),
                parse_mode='Markdown'
            )
        except:
            # If we can't edit the message, send a new one
            await update.effective_chat.send_message(
                menu_text,
                reply_markup=get_main_menu_markup(),
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text(
            menu_text,
            reply_markup=get_main_menu_markup(),
            parse_mode='Markdown'
        )

# Bot command handlers
async def start_command(update: Update, context: CallbackContext):
    """Handler for the /start command"""
    logger.info(f"Start command received from user {update.effective_user.id}")
    welcome_text = (
        "This bot helps you track your Hyperliquid perpetual futures positions."
    )
    await update.message.reply_text(welcome_text)
    await show_main_menu(update, context)

async def help_command(update: Update, context: CallbackContext):
    """Handler for the /help command"""
    logger.info(f"Help command received from user {update.effective_user.id}")
    help_text = (
        "📚 *Hyperliquid Tracking Bot Commands*\n\n"
        "• *Positions* - View your tracked portfolio\n"
        "• *Track Wallet* - Add a new wallet to track\n"
        "• *My Wallets* - Manage your tracked wallets\n"
        "• *Settings* - Configure alerts and preferences\n"
        "• *Refresh* - Update all your tracking data\n\n"
        "You can also use these text commands:\n"
        "/start - Show main menu\n"
        "/help - Show this help message\n"
        "/menu - Show main menu\n"
        "/markets - View current market prices"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')
    await show_main_menu(update, context)

async def menu_command(update: Update, context: CallbackContext):
    """Handler for the /menu command to show main menu"""
    logger.info(f"Menu command received from user {update.effective_user.id}")
    await show_main_menu(update, context)

async def prompt_track_wallet(update: Update, context: CallbackContext):
    """Prompt user to enter a wallet address with improved UI"""
    prompt_text = (
        "🔍 *Add a Wallet to Track*\n\n"
        "Please send the wallet address you want to track.\n\n"
        "*Format:* `0x` followed by 40 hexadecimal characters\n"
        "*Example:* `0x1234abcd...`\n\n"
        "Type or paste the address in your next message."
    )
    
    keyboard = [[InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        # If called from a button
        query = update.callback_query
        await query.edit_message_text(
            prompt_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        # If called directly
        await update.message.reply_text(
            prompt_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    context.user_data['awaiting_wallet_address'] = True

async def track_wallet_command(update: Update, context: CallbackContext):
    """Handler for the /track command to set a wallet to be tracked"""
    logger.info(f"Track command received from user {update.effective_user.id}")
    if not context.args or len(context.args) < 1:
        # If no wallet address given, prompt for one
        await prompt_track_wallet(update, context)
        return
    
    wallet_address = context.args[0]
    await add_wallet(update, context, wallet_address)

async def add_wallet(update: Update, context: CallbackContext, wallet_address):
    """Add a wallet to tracking list without showing initial data"""
    logger.info(f"Adding wallet: {wallet_address}")
    
    # Initialize wallet tracking structure if not exists
    if not context.user_data.get('tracked_wallets'):
        context.user_data['tracked_wallets'] = []
    
    # Add wallet if not already tracked
    already_tracked = wallet_address in context.user_data['tracked_wallets']
    if not already_tracked:
        context.user_data['tracked_wallets'].append(wallet_address)
    
    formatted_wallet = utils.format_wallet_address(wallet_address)
    
    # Create inline buttons for wallet actions
    keyboard = [
        [InlineKeyboardButton("👁️ View Positions", callback_data=f"view_positions_{wallet_address}")],
        [InlineKeyboardButton("📊 View Portfolio", callback_data="view_portfolio")],
        [InlineKeyboardButton("➕ Track Another Wallet", callback_data="track_wallet")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"{'✅ Now tracking' if not already_tracked else '⚠️ Already tracking'} wallet: {formatted_wallet}"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

async def wallets_command(update: Update, context: CallbackContext):
    """Handler for the /wallets command"""
    logger.info(f"Wallets command received from user {update.effective_user.id}")
    
    # Just show the wallet management screen
    keyboard = [
        [InlineKeyboardButton("👁️ View Tracked Wallets", callback_data="view_wallets")],
        [InlineKeyboardButton("➕ Track New Wallet", callback_data="track_wallet")],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Wallet Management:", reply_markup=reply_markup)

async def markets_command(update: Update, context: CallbackContext):
    """Handler for the /markets command to view current market data"""
    logger.info(f"Markets command received from user {update.effective_user.id}")
    try:
        markets_data = await get_market_data()
        
        if markets_data:
            markets_text = "📊 *Current Market Prices*\n\n"
            
            # Create keyboard for market selection
            keyboard = []
            row = []
            
            sorted_markets = sorted(markets_data.items(), key=lambda x: float(x[1]), reverse=True)
            
            for idx, (coin, price) in enumerate(sorted_markets):
                markets_text += f"*{coin}*: ${float(price):.2f}\n"
                
                # Add button to keyboard
                row.append(InlineKeyboardButton(coin, callback_data=f"market_{coin}"))
                
                # Create a new row every 3 buttons
                if (idx + 1) % 3 == 0 or idx == len(markets_data) - 1:
                    keyboard.append(row)
                    row = []
            
            keyboard.append([InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(markets_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Error fetching market data.")
            
    except Exception as e:
        logger.error(f"Error in markets command: {e}")
        await update.message.reply_text("❌ Error fetching market data. Please try again later.")

async def portfolio_command(update: Update, context: CallbackContext):
    """Handler for the portfolio view with improved UI"""
    logger.info(f"Portfolio command received from user {update.effective_user.id}")
    if not context.user_data.get('tracked_wallets'):
        # No wallets tracked, offer to add one
        keyboard = [
            [InlineKeyboardButton("➕ Track New Wallet", callback_data="track_wallet")],
            [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "📭 *No Wallets Tracked*\n\n"
            "You need to add a wallet before you can view positions.\n"
            "Press the button below to track your first wallet.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    # Show loading message
    loading_message = await update.message.reply_text("⏳ *Loading portfolio data...*", parse_mode='Markdown')
    
    portfolio_text = "📈 *Your Portfolio Summary*\n\n"
    total_equity = 0
    total_pnl = 0
    
    # Fetch market data for current prices
    markets_data = await get_market_data()
    
    for wallet in context.user_data['tracked_wallets']:
        formatted_wallet = utils.format_wallet_address(wallet)
        try:
            wallet_info = await get_account_info(wallet)
            
            if wallet_info:
                # Safely extract account value with type conversion
                account_value_str = wallet_info.get('crossMarginSummary', {}).get('accountValue', "0")
                account_value = float(account_value_str)
                total_equity += account_value
                
                portfolio_text += f"━━━━━━━━━━━━━━━━━━━━━\n"
                portfolio_text += f"*Wallet:* `{formatted_wallet}`\n"
                portfolio_text += f"*Equity:* ${account_value:.2f}\n\n"
                
                if 'assetPositions' in wallet_info and wallet_info['assetPositions']:
                    portfolio_text += "*Active Positions:*\n\n"
                    
                    for position in wallet_info['assetPositions']:
                        try:
                            # Extract standardized position data
                            position_data = utils.extract_position_data(position)
                            coin = position_data['coin']
                            unrealized_pnl = position_data['unrealized_pnl']
                            
                            total_pnl += unrealized_pnl
                            
                            # Get current price
                            current_price = utils.get_current_price(markets_data, coin)
                            
                            # Calculate position value and other metrics
                            size = position_data['size']
                            size_abs = abs(size)
                            position_value = size_abs * current_price
                            direction = "Long" if size > 0 else "Short"
                            
                            # Add appropriate emoji indicators
                            direction_emoji = "🟢" if direction == "Long" else "🔴"
                            pnl_emoji = "✅" if unrealized_pnl >= 0 else "❌"
                            
                            # Format position with improved styling
                            portfolio_text += f"{direction_emoji} *{coin}*: {direction} {position_data['leverage']}x\n"
                            portfolio_text += f"  {size_abs:.6f} {coin} @ ${position_data['entry_price']:.4f}\n"
                            portfolio_text += f"  Current: ${current_price:.4f} | PnL: {pnl_emoji} ${unrealized_pnl:.2f}\n"
                            portfolio_text += f"  Value: ${position_value:.2f}\n\n"
                        except Exception as e:
                            logger.error(f"Error processing position in portfolio: {e}")
                            portfolio_text += f"• Error processing a position: {str(e)}\n"
                    
                else:
                    portfolio_text += "*No active positions*\n\n"
                    
        except Exception as e:
            logger.error(f"Error fetching data for wallet {wallet}: {e}")
            portfolio_text += f"❌ Error fetching data for wallet {formatted_wallet}\n\n"
    
    # Add summary section with visual emphasis
    portfolio_text += "━━━━━━━━━━━━━━━━━━━━━\n"
    portfolio_text += f"*📊 Portfolio Summary*\n\n"
    portfolio_text += f"*Total Equity:* ${total_equity:.2f}\n"
    
    # Add emoji for PnL based on positive/negative
    pnl_emoji = "✅" if total_pnl >= 0 else "❌"
    portfolio_text += f"*Total PnL:* {pnl_emoji} ${total_pnl:.2f}"
    
    # Create navigation buttons
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Data", callback_data="refresh_portfolio")],
        [InlineKeyboardButton("➕ Track New Wallet", callback_data="track_wallet"),
         InlineKeyboardButton("👁️ Manage Wallets", callback_data="view_wallets")],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Delete loading message and send portfolio
    await loading_message.delete()
    await update.message.reply_text(portfolio_text, parse_mode='Markdown', reply_markup=reply_markup)

async def position_command(update: Update, context: CallbackContext):
    """Handler for viewing position details"""
    logger.info(f"Position command received from user {update.effective_user.id}")
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Please provide an asset name. Usage: /position <asset>")
        return
    
    coin = context.args[0].upper()
    
    if not context.user_data.get('tracked_wallets'):
        await update.message.reply_text("No wallets are being tracked. Use /track <wallet_address> to start tracking.")
        return
    
    found_position = False
    
    for wallet in context.user_data['tracked_wallets']:
        try:
            wallet_info = await get_account_info(wallet)
            
            if wallet_info and 'assetPositions' in wallet_info:
                for position in wallet_info['assetPositions']:
                    position_data = utils.extract_position_data(position)
                    position_coin = position_data['coin']
                    
                    if position_coin.upper() == coin:
                        found_position = True
                        
                        # Get market data for current price
                        markets_data = await get_market_data()
                        current_price = utils.get_current_price(markets_data, coin)
                        
                        # Format position text
                        position_text = utils.format_position_text(position_data, current_price)
                        
                        # Create navigation buttons
                        keyboard = [
                            [InlineKeyboardButton("📊 View All Positions", callback_data="view_portfolio")],
                            [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_position_{coin}")],
                            [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await update.message.reply_text(position_text, parse_mode='Markdown', reply_markup=reply_markup)
                        return
        except Exception as e:
            logger.error(f"Error fetching position data: {e}")
    
    if not found_position:
        await update.message.reply_text(f"No position found for {coin}.")

async def settings_command(update: Update, context: CallbackContext):
    """Handler for the settings menu"""
    logger.info(f"Settings requested by user {update.effective_user.id}")
    
    # Create inline keyboard for settings options
    keyboard = [
        [InlineKeyboardButton("➕ Track New Wallet", callback_data="track_wallet")],
        [InlineKeyboardButton("👁️ Manage Wallets", callback_data="view_wallets")],
        [InlineKeyboardButton("⏰ Configure Alerts", callback_data="configure_alerts")],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if update.message:
            await update.message.reply_text("⚙️ *Settings*\n\nManage your tracked wallets and preferences:", 
                                        reply_markup=reply_markup, parse_mode='Markdown')
        else:
            # If update.message is not available, this might be a callback query
            chat_id = update.effective_chat.id
            await context.bot.send_message(chat_id=chat_id, 
 text="⚙️ *Settings*\n\nManage your tracked wallets and preferences:", 
                                        reply_markup=reply_markup, 
                                        parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error showing settings: {e}")
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id=chat_id, 
                                     text="⚙️ *Settings*\n\nManage your tracked wallets and preferences:", 
                                     reply_markup=reply_markup, 
                                     parse_mode='Markdown')

async def refresh_command(update: Update, context: CallbackContext):
    """Handler for refresh button to update data"""
    logger.info(f"Refresh requested by user {update.effective_user.id}")
    
    tracked_wallets = context.user_data.get('tracked_wallets', [])
    
    if not tracked_wallets:
        keyboard = [
            [InlineKeyboardButton("➕ Track New Wallet", callback_data="track_wallet")],
            [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "You are not tracking any wallets yet. Add a wallet first.",
            reply_markup=reply_markup
        )
        return
    
    # Show refreshing message
    message = await update.message.reply_text("🔄 Refreshing data...")
    
    try:
        # Refresh market data
        markets_data = await get_market_data()
        
        # Count positions across all wallets
        total_positions = 0
        total_equity = 0
        
        # Refresh each wallet
        for wallet in tracked_wallets:
            wallet_info = await get_account_info(wallet)
            if wallet_info:
                if 'assetPositions' in wallet_info:
                    total_positions += len(wallet_info['assetPositions'])
                
                # Add equity if available
                account_value_str = wallet_info.get('crossMarginSummary', {}).get('accountValue', "0")
                account_value = float(account_value_str)
                total_equity += account_value
        
        # Create buttons for next actions
        keyboard = [
            [InlineKeyboardButton("📊 View Portfolio", callback_data="view_portfolio")],
            [InlineKeyboardButton("📈 Market Data", callback_data="view_markets")],
            [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Update message with refresh results
        refresh_time = datetime.now().strftime("%H:%M:%S")
        await message.edit_text(
            f"✅ Data refreshed at {refresh_time}\n\n"
            f"Found {total_positions} active positions across {len(tracked_wallets)} wallets.\n"
            f"Total portfolio equity: ${total_equity:.2f}",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error refreshing data: {e}")
        await message.edit_text(
            f"❌ Error refreshing data: {str(e)}",
            reply_markup=get_back_button()
        )

# Navigation and button handlers
async def handle_callback(update: Update, context: CallbackContext):
    """Handler for all callback queries"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "show_main_menu":
        # Show main menu
        await show_main_menu(update, context)
    
    elif data == "close_menu":
        # Close the menu
        await query.delete_message()
    
    elif data == "view_portfolio":
        # View portfolio - with better wallet selection interface
        tracked_wallets = context.user_data.get('tracked_wallets', [])
        if not tracked_wallets:
            # No wallets tracked, offer to add one with improved empty state
            keyboard = [
                [InlineKeyboardButton("➕ Track New Wallet", callback_data="track_wallet")],
                [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "📭 *No Wallets Tracked*\n\n"
                "You need to add a wallet before you can view positions.\n"
                "Press the button below to track your first wallet.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            # Show wallet selection menu with improved formatting
            wallet_text = "📊 *Select a Wallet*\n\n" 
            wallet_text += "Choose which wallet's positions you want to view:\n\n"
            
            keyboard = []
            
            # Add wallet options with better visual separation
            for i, wallet in enumerate(tracked_wallets, 1):
                formatted_wallet = utils.format_wallet_address(wallet)
                keyboard.append([InlineKeyboardButton(f"{i}. {formatted_wallet}", callback_data=f"view_positions_{wallet}")])
            
            # Add view all option with visual emphasis
            wallet_text += "\n*Or view your complete portfolio:*"
            keyboard.append([InlineKeyboardButton("📈 View All Positions", callback_data="view_all_portfolio")])
            keyboard.append([InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(wallet_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif data == "refresh_data":
        # Refresh data
        await query.delete_message()
        await refresh_command(update, context)
    
    elif data == "track_wallet":
        # Prompt to add a wallet
        await prompt_track_wallet(update, context)
    
    elif data == "settings":
        # Show settings menu
        await query.delete_message()
        await settings_command(update, context)
    
    elif data == "view_markets":
        # View markets
        await query.delete_message()
        await markets_command(update, context)
        
    elif data == "refresh_portfolio":
        # Refresh portfolio
        await query.delete_message()
        await portfolio_command(update, context)
        
    elif data.startswith("refresh_position_"):
        # Refresh specific position
        coin = data.split("_")[2]
        context.args = [coin]  # Set args for position_command
        await query.delete_message()
        await position_command(update, context)
        
    elif data == "add_wallet":
        # Prompt to add a wallet
        await prompt_track_wallet(update, context)
        
    elif data == "view_wallets":
        # Show tracked wallets with inline buttons in an improved layout
        await list_wallets_inline(update, context)
        
    elif data == "configure_alerts":
        # Configure alerts inline
        from price_alerts import setup_inline_alerts
        await setup_inline_alerts(update, context)
        
    elif data == "back_to_settings":
        # Go back to settings menu
        await settings_command(update, context)
        try:
            await query.message.delete()
        except:
            pass
        
    elif data.startswith("untrack_"):
        # Untrack a wallet
        wallet_to_remove = data.replace("untrack_", "")
        tracked_wallets = context.user_data.get('tracked_wallets', [])
        
        if wallet_to_remove in tracked_wallets:
            tracked_wallets.remove(wallet_to_remove)
            context.user_data['tracked_wallets'] = tracked_wallets
            
            formatted_wallet = utils.format_wallet_address(wallet_to_remove)    
            
            # Return to wallet list
            await list_wallets_inline(update, context)
            await query.answer(f"Stopped tracking {formatted_wallet}")
        else:
            await query.answer("Wallet not found")
            
    elif data.startswith("view_positions_"):
        # View positions for a specific wallet with improved formatting
        wallet = data.split("_")[2]
        formatted_wallet = utils.format_wallet_address(wallet)
        
        try:
            # Show loading message first
            await query.edit_message_text(f"⏳ Loading positions for wallet {formatted_wallet}...")
            
            # Fetch wallet data
            wallet_info = await get_account_info(wallet)
            
            if wallet_info and 'assetPositions' in wallet_info and wallet_info['assetPositions']:
                positions_text = f"📈 *Positions for wallet*\n`{formatted_wallet}`\n\n"
                
                # Fetch market data for current prices
                markets_data = await get_market_data()
                
                # Process each position with improved formatting
                for position in wallet_info['assetPositions']:
                    try:
                        # Get the coin name with fallbacks
                        coin = position.get('coin', None)
                        if not coin or coin == 'Unknown':
                            # Try to extract from position.position.coin
                            pos_details = position.get('position', {})
                            if isinstance(pos_details, dict) and 'coin' in pos_details:
                                coin = pos_details['coin']
                            # If still no coin found, use BTC as placeholder
                            if not coin:
                                coin = "BTC"
                        
                        # Get position details safely
                        pos_details = position.get('position', {})
                        if not isinstance(pos_details, dict):
                            pos_details = {}  # Ensure it's a dict
                        
                        # Extract numeric values safely
                        # Size (szi)
                        size = 0
                        try:
                            size_value = pos_details.get('szi')
                            if size_value is not None:
                                if isinstance(size_value, dict):
                                    # Try to find value in dict
                                    for k, v in size_value.items():
                                        if v is not None and (isinstance(v, (int, float)) or 
                                                            (isinstance(v, str) and v.replace('.', '', 1).isdigit())):
                                            size = float(v)
                                            break
                                else:
                                    size = float(size_value)
                        except (TypeError, ValueError) as e:
                            logger.error(f"Error processing size: {e}")
                            
                        # Skip positions with zero size
                        if size == 0:
                            continue
                            
                        # Determine direction and calculate absolute size
                        direction = "Long" if size > 0 else "Short"
                        size_abs = abs(size)
                        
                        # Entry price
                        entry_price = 0
                        try:
                            entry_value = pos_details.get('entryPx')
                            if entry_value is not None:
                                if isinstance(entry_value, dict):
                                    for k, v in entry_value.items():
                                        if v is not None and (isinstance(v, (int, float)) or 
                                                            (isinstance(v, str) and v.replace('.', '', 1).isdigit())):
                                            entry_price = float(v)
                                            break
                                else:
                                    entry_price = float(entry_value)
                        except (TypeError, ValueError) as e:
                            logger.error(f"Error processing entry price: {e}")
                        
                        # Leverage
                        leverage = 1
                        try:
                            lev_value = pos_details.get('leverage')
                            if lev_value is not None:
                                if isinstance(lev_value, dict):
                                    for k, v in lev_value.items():
                                        if v is not None and (isinstance(v, (int, float)) or 
                                                            (isinstance(v, str) and v.replace('.', '', 1).isdigit())):
                                            leverage = float(v)
                                            break
                                else:
                                    leverage = float(lev_value)
                        except (TypeError, ValueError) as e:
                            logger.error(f"Error processing leverage: {e}")
                        
                        # Get current price from markets data
                        current_price = 0
                        try:
                            if coin in markets_data and markets_data[coin] is not None:
                                current_price = float(markets_data[coin])
                        except (TypeError, ValueError) as e:
                            logger.error(f"Error getting current price: {e}")
                        
                        # Calculate position value
                        position_value = size_abs * current_price if current_price > 0 else 0
                        
                        # Get unrealized PnL - try multiple locations in the response
                        unrealized_pnl = 0
                        pnl_sources = [
                            position.get('unrealizedPnl'),                # Standard location
                            position.get('bankBalance', {}).get('pnl'),   # Sometimes it's here
                            position.get('pnl'),                          # Or directly here
                            # Look for any field containing 'pnl' at top level
                            *[v for k, v in position.items() if 'pnl' in k.lower()]
                        ]
                        
                        for pnl_value in pnl_sources:
                            try:
                                if pnl_value is not None:
                                    if isinstance(pnl_value, dict):
                                        for k, v in pnl_value.items():
                                            if v is not None and (isinstance(v, (int, float)) or 
                                                                (isinstance(v, str) and v.replace('.', '', 1).replace('-', '', 1).isdigit())):
                                                unrealized_pnl = float(v)
                                                break
                                    else:
                                        unrealized_pnl = float(pnl_value)
                                        
                                    # If we found a non-zero PnL, stop looking
                                    if unrealized_pnl != 0:
                                        break
                            except (TypeError, ValueError) as e:
                                logger.error(f"Error processing a PnL value: {e}")
                                continue
                        
                        # If PnL is still 0, calculate it based on entry, current price, and size
                        if unrealized_pnl == 0 and entry_price > 0 and current_price > 0:
                            price_diff = current_price - entry_price
                            unrealized_pnl = price_diff * size_abs * (1 if direction == "Long" else -1)
                            logger.info(f"Calculated PnL for {coin}: {unrealized_pnl}")
                        
                        # Get liquidation price - try multiple possible locations
                        liquidation_price = 0
                        liq_sources = [
                            pos_details.get('liquidationPx'),                # Standard location
                            position.get('liquidationPx'),                   # Sometimes at top level
                            pos_details.get('liquidationPrice'),             # Alternative name
                            position.get('liquidationPrice'),                # Alternative at top
                            # Look for any field containing 'liquidation' at both levels
                            *[v for k, v in pos_details.items() if 'liquidation' in k.lower()],
                            *[v for k, v in position.items() if 'liquidation' in k.lower()]
                        ]
                        
                        for liq_value in liq_sources:
                            try:
                                if liq_value is not None:
                                    if isinstance(liq_value, dict):
                                        for k, v in liq_value.items():
                                            if v is not None and (isinstance(v, (int, float)) or 
                                                                (isinstance(v, str) and v.replace('.', '', 1).isdigit())):
                                                liquidation_price = float(v)
                                                break
                                    else:
                                        liquidation_price = float(liq_value)
                                        
                                    # If we found a non-zero liquidation price, stop looking
                                    if liquidation_price != 0:
                                        break
                            except (TypeError, ValueError) as e:
                                logger.error(f"Error processing a liquidation price: {e}")
                                continue
                        
                        # If liquidation price is still 0, make a simple estimate if long
                        if liquidation_price == 0 and entry_price > 0 and leverage > 1:
                            # Very rough approximation (for demonstration only)
                            if direction == "Long":
                                liquidation_price = entry_price * (1 - (0.9 / leverage))
                            else:
                                liquidation_price = entry_price * (1 + (0.9 / leverage))
                            logger.info(f"Estimated liquidation price for {coin}: {liquidation_price}")
                        
                        # Format the position text with cleaner styling
                        positions_text += f"━━━━━━━━━━━━━━━━━━━━━\n"
                        positions_text += f"💎 *{coin}*\n\n"
                        
                        # Direction with colored emoji indicators
                        direction_emoji = "🟢" if direction == "Long" else "🔴"
                        positions_text += f"{direction_emoji} *{direction}* {leverage}x\n\n"
                        
                        # Size and value in clear format
                        positions_text += f"*Size:* {size_abs:.6f} {coin}\n"
                        positions_text += f"*Value:* ${position_value:.2f}\n\n"
                        
                        # Price information with improved formatting
                        positions_text += f"*Entry:* ${entry_price:.4f}\n"
                        positions_text += f"*Current:* ${current_price:.4f}\n"
                        
                        # Calculate and show percentage change with emoji
                        if entry_price > 0 and current_price > 0:
                            price_change_pct = ((current_price / entry_price) - 1) * 100
                            change_emoji = "📈" if price_change_pct >= 0 else "📉"
                            positions_text += f"*Change:* {change_emoji} {price_change_pct:.2f}%\n\n"
                        else:
                            positions_text += "\n"
                        
                        # PnL with emoji indicator
                        pnl_emoji = "✅" if unrealized_pnl >= 0 else "❌"
                        positions_text += f"*PnL:* {pnl_emoji} ${unrealized_pnl:.2f}\n"
                        
                        # Liquidation price with warning emoji if close
                        if liquidation_price > 0:
                            # Calculate distance to liquidation as percentage
                            if direction == "Long":
                                liq_distance = ((current_price - liquidation_price) / current_price) * 100
                            else:
                                liq_distance = ((liquidation_price - current_price) / current_price) * 100
                                
                            liq_emoji = "🔴" if liq_distance < 5 else ("🟠" if liq_distance < 15 else "🟡")
                            positions_text += f"*Liquidation:* {liq_emoji} ${liquidation_price:.4f}\n"
                        
                        positions_text += "\n"
                        
                    except Exception as e:
                        logger.error(f"Error processing position for {coin}: {str(e)}")
                        positions_text += f"• Error processing {coin if coin else 'Unknown'} position\n\n"
                
                # Create back button with improved styling
                keyboard = [
                    [InlineKeyboardButton("🔄 Refresh", callback_data=f"view_positions_{wallet}")],
                    [InlineKeyboardButton("📊 View All Positions", callback_data="view_all_portfolio")],
                    [InlineKeyboardButton("◀️ Back to Wallets", callback_data="view_wallets")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(positions_text, parse_mode='Markdown', reply_markup=reply_markup)
            else:
                # No positions found - improved empty state message
                keyboard = [
                    [InlineKeyboardButton("🔄 Refresh", callback_data=f"view_positions_{wallet}")],
                    [InlineKeyboardButton("◀️ Back to Wallets", callback_data="view_wallets")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"📭 *No Active Positions*\n\n"
                    f"Wallet `{formatted_wallet}` doesn't have any open positions at the moment.\n\n"
                    f"Track another wallet or refresh to check again.",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Error fetching position data: {e}")
            await query.edit_message_text(
                f"❌ *Error fetching positions*\n\n"
                f"Could not retrieve data for wallet `{formatted_wallet}`.\n"
                f"Error: {str(e)}",
                reply_markup=get_back_button("view_wallets", "◀️ Back to Wallets"),
                parse_mode='Markdown'
            )
    
    elif data.startswith("market_"):
        # Show detail for a specific market
        coin = data.split("_")[1]
        
        try:
            markets_data = await get_market_data()
            price = float(markets_data.get(coin, 0))
            
            market_info = f"📊 *{coin} Market Information*\n\n"
            market_info += f"Current Price: ${price:.4f}\n\n"
            
            # Check if user has positions in this market
            has_position = False
            position_info = ""
            
            for wallet in context.user_data.get('tracked_wallets', []):
                wallet_info = await get_account_info(wallet)
                
                if wallet_info and 'assetPositions' in wallet_info:
                    for position in wallet_info['assetPositions']:
                        position_data = utils.extract_position_data(position)
                        if position_data['coin'].upper() == coin.upper():
                            has_position = True
                            size = position_data['size']
                            direction = "Long" if size > 0 else "Short"
                            leverage = position_data['leverage']
                            pnl = position_data['unrealized_pnl']
                            
                            position_info += f"Your Position: {direction} {leverage}x\n"
                            position_info += f"Unrealized PnL: ${pnl:.2f}\n\n"
            
            if has_position:
                market_info += position_info
            
            # Create buttons for next actions
            keyboard = [
                [InlineKeyboardButton("📈 View All Markets", callback_data="view_markets")],
                [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
            ]
            
            # Add position viewing button if available
            if has_position:
                keyboard.insert(0, [InlineKeyboardButton(f"View {coin} Position", callback_data=f"refresh_position_{coin}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(market_info, parse_mode='Markdown', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling market callback: {e}")
            await query.edit_message_text(f"❌ Error fetching data for {coin}. Please try again.")

    # Add a new handler for viewing all positions
    elif data == "view_all_portfolio":
        # View all portfolios (this uses the existing portfolio_command function)
        await query.delete_message()
        await portfolio_command(update, context)

async def list_wallets_inline(update: Update, context: CallbackContext):
    """Show tracked wallets with inline buttons in an improved layout"""
    query = update.callback_query
    tracked_wallets = context.user_data.get('tracked_wallets', [])
    
    if not tracked_wallets:
        # Empty state with visual improvement
        keyboard = [
            [InlineKeyboardButton("➕ Track New Wallet", callback_data="track_wallet")],
            [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📭 *No Wallets Tracked*\n\n"
            "You haven't added any wallets to track yet.\n"
            "Press the button below to get started.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    wallets_text = "👁️ *Your Tracked Wallets*\n\n"
    wallets_text += "Here are all the wallets you're currently tracking:\n\n"
    
    keyboard = []
    
    for i, wallet in enumerate(tracked_wallets, 1):
        formatted_wallet = utils.format_wallet_address(wallet)
        wallets_text += f"{i}. `{wallet}`\n"
        
        # Group related actions for each wallet
        view_button = InlineKeyboardButton(f"👁️ View", callback_data=f"view_positions_{wallet}")
        remove_button = InlineKeyboardButton(f"❌ Remove", callback_data=f"untrack_{wallet}")
        keyboard.append([view_button, remove_button])
    
    wallets_text += "\nSelect an action for any wallet below:"
    
    # Add general actions at the bottom with visual separation
    keyboard.append([InlineKeyboardButton("➕ Track New Wallet", callback_data="track_wallet")])
    keyboard.append([InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(wallets_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_wallet_input(update: Update, context: CallbackContext):
    """Handle wallet address input after prompting"""
    if context.user_data.get('awaiting_wallet_address'):
        wallet_address = update.message.text.strip()
        
        # Validate wallet address (basic check)
        if not wallet_address.startswith('0x') or len(wallet_address) != 42:
            keyboard = [[InlineKeyboardButton("➕ Try Again", callback_data="track_wallet")],
                       [InlineKeyboardButton("◀️ Back to Menu", callback_data="show_main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "❌ Invalid wallet address format. Please enter a valid wallet address.\n\n"
                "Example: 0x1234abcd...",
                reply_markup=reply_markup
            )
            return
        
        # Clear the awaiting flag
        context.user_data['awaiting_wallet_address'] = False
        
        # Add the wallet
        await add_wallet(update, context, wallet_address)

async def handle_alert_check_job(context: CallbackContext):
    """Background task to periodically check alerts"""
    logger.info("Running alert check job")
    from price_alerts import alert_manager
    await alert_manager.check_alerts(context.application)

# Set up command menu
async def set_commands(application):
    """Set up the bot commands in the menu"""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("menu", "Show main menu"),
        BotCommand("help", "Show help information"),
        BotCommand("markets", "View market prices"),
        BotCommand("positions", "View your positions"),
        BotCommand("track", "Track a wallet"),
        BotCommand("wallets", "Manage your wallets"),
        BotCommand("settings", "Access settings menu")
    ]
    
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands menu set up")

def main():
    """Start the bot"""
    print("In main function, setting up the bot...")
    
    # Import here to avoid circular imports
    from position_tracker import set_api_functions as set_position_tracker_functions
    from price_alerts import set_api_functions as set_price_alerts_functions
    from price_alerts import setup_alerts, alert_manager
    
    # Set the API functions for the other modules
    print("Setting up API functions...")
    set_position_tracker_functions(get_account_info, get_market_data)
    set_price_alerts_functions(get_account_info, get_market_data)
    
    # Create the Application
    print(f"Building application with token: {TELEGRAM_BOT_TOKEN[:4]}...{TELEGRAM_BOT_TOKEN[-4:]}")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    print("Adding command handlers...")
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("track", track_wallet_command))
    application.add_handler(CommandHandler("wallets", wallets_command))
    application.add_handler(CommandHandler("markets", markets_command))
    application.add_handler(CommandHandler("portfolio", portfolio_command))
    application.add_handler(CommandHandler("positions", portfolio_command))  # Alias for portfolio
    application.add_handler(CommandHandler("position", position_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("refresh", refresh_command))
    
    # Add callback query handler for navigation
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Add message handler for wallet input
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_input))
    
    # Set up alerts system
    print("Setting up alerts system...")
    setup_alerts(application)
    
    # Add alert checking job
    print("Setting up alert check job...")
    job_queue = application.job_queue
    job_queue.run_repeating(handle_alert_check_job, interval=config.ALERT_CHECK_INTERVAL, first=10)
    
    # Setup command menu
    job_queue.run_once(lambda _: set_commands(application), 0)
    
    # Start the Bot
    print("Starting the bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    print("Bot is now running!")

if __name__ == '__main__':
    main()