import asyncio
import logging
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackContext, CallbackQueryHandler, ConversationHandler, MessageHandler, filters

# Configure logging
logger = logging.getLogger(__name__)

# Alert states for conversation handler
SELECTING_COIN, ENTERING_PRICE, SELECTING_DIRECTION = range(3)

# Alert types
PRICE_ABOVE = "PRICE_ABOVE"
PRICE_BELOW = "PRICE_BELOW"
LIQUIDATION_WARN = "LIQUIDATION_WARN"
FUNDING_RATE = "FUNDING_RATE"

# Placeholder API functions that will be injected from bot.py
get_account_info = None
get_market_data = None

def set_api_functions(account_info_func, market_data_func):
    """Set the API functions from bot.py"""
    global get_account_info, get_market_data
    get_account_info = account_info_func
    get_market_data = market_data_func

class AlertManager:
    def __init__(self):
        self.alerts = {}  # user_id -> list of alerts
        self.running = False

    def add_alert(self, user_id, alert_data):
        """Add a new alert for a user"""
        if user_id not in self.alerts:
            self.alerts[user_id] = []
        
        # Add timestamp and unique ID
        alert_data['timestamp'] = datetime.now().isoformat()
        alert_data['id'] = f"{user_id}_{len(self.alerts[user_id])}"
        
        self.alerts[user_id].append(alert_data)
        return alert_data['id']
    
    def remove_alert(self, user_id, alert_id):
        """Remove an alert for a user"""
        if user_id in self.alerts:
            self.alerts[user_id] = [a for a in self.alerts[user_id] if a.get('id') != alert_id]
            return True
        return False
    
    def get_user_alerts(self, user_id):
        """Get all alerts for a user"""
        return self.alerts.get(user_id, [])
    
    async def check_alerts(self, application):
        """Check all active alerts and send notifications"""
        try:
            # Fetch latest market data once for efficiency
            market_data = await get_market_data()
            
            for user_id in self.alerts:
                triggered_alerts = []
                alerts = self.alerts[user_id]
                
                for alert in alerts:
                    triggered = False
                    alert_type = alert.get('type')
                    coin = alert.get('coin')
                    
                    if coin in market_data:
                        current_price = float(market_data[coin])
                        
                        if alert_type == PRICE_ABOVE and current_price >= float(alert.get('price', 0)):
                            triggered = True
                            message = f"🔔 *ALERT:* {coin} price is now above ${float(alert.get('price', 0)):.2f}\nCurrent price: ${current_price:.2f}"
                        
                        elif alert_type == PRICE_BELOW and current_price <= float(alert.get('price', 0)):
                            triggered = True
                            message = f"🔔 *ALERT:* {coin} price is now below ${float(alert.get('price', 0)):.2f}\nCurrent price: ${current_price:.2f}"
                    
                    if alert_type == LIQUIDATION_WARN:
                        # Check for liquidation warnings in user positions
                        wallet_address = alert.get('wallet_address')
                        
                        if wallet_address:
                            wallet_info = await get_account_info(wallet_address)
                            
                            if wallet_info and 'assetPositions' in wallet_info:
                                for position in wallet_info['assetPositions']:
                                    position_coin = position.get('coin')
                                    
                                    if position_coin == coin and position_coin in market_data:
                                        liquidation_price = float(position.get('position', {}).get('liquidationPx', 0))
                                        current_price = float(market_data[position_coin])
                                        
                                        # Calculate distance to liquidation as a percentage
                                        distance_pct = abs((liquidation_price / current_price - 1) * 100)
                                        
                                        if distance_pct <= float(alert.get('threshold', 10)):
                                            triggered = True
                                            message = (
                                                f"⚠️ *LIQUIDATION WARNING:* {coin}\n"
                                                f"Current price: ${current_price:.2f}\n"
                                                f"Liquidation price: ${liquidation_price:.2f}\n"
                                                f"Distance to liquidation: {distance_pct:.2f}%"
                                            )
                    
                    if triggered:
                        triggered_alerts.append((alert, message))
                
                # Process triggered alerts
                for alert, message in triggered_alerts:
                    # Send notification to user
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                    
                    # Remove one-time alerts after triggering
                    if alert.get('one_time', True):
                        self.remove_alert(user_id, alert.get('id'))
        
        except Exception as e:
            logging.error(f"Error in alert checking: {e}")

# Initialize alert manager
alert_manager = AlertManager()

# Handler functions for alerts
async def alerts_command(update: Update, context: CallbackContext):
    """Handler for the /alerts command to manage price alerts"""
    keyboard = [
        [
            InlineKeyboardButton("Add Price Alert", callback_data="alert_add_price"),
            InlineKeyboardButton("Add Liquidation Alert", callback_data="alert_add_liquidation")
        ],
        [
            InlineKeyboardButton("View All Alerts", callback_data="alert_view"),
            InlineKeyboardButton("Cancel", callback_data="alert_cancel")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔔 *Alert Management*\n\nWhat would you like to do?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return SELECTING_COIN

async def handle_alert_callback(update: Update, context: CallbackContext):
    """Handler for alert management callbacks"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "alert_cancel":
        await query.edit_message_text("Alert creation cancelled.")
        return ConversationHandler.END
    
    elif data == "alert_view":
        user_alerts = alert_manager.get_user_alerts(update.effective_user.id)
        
        if not user_alerts:
            await query.edit_message_text("You don't have any active alerts.")
            return ConversationHandler.END
        
        alerts_text = "🔔 *Your Active Alerts*\n\n"
        
        for i, alert in enumerate(user_alerts, 1):
            alert_type = alert.get('type')
            coin = alert.get('coin')
            
            alerts_text += f"{i}. {coin}: "
            
            if alert_type == PRICE_ABOVE:
                alerts_text += f"Price above ${float(alert.get('price', 0)):.2f}"
            elif alert_type == PRICE_BELOW:
                alerts_text += f"Price below ${float(alert.get('price', 0)):.2f}"
            elif alert_type == LIQUIDATION_WARN:
                alerts_text += f"Liquidation warning (threshold: {alert.get('threshold')}%)"
            
            alerts_text += "\n"
        
        # Create keyboard for deleting alerts
        keyboard = []
        for i, alert in enumerate(user_alerts):
            keyboard.append([InlineKeyboardButton(
                f"Delete Alert #{i+1}", callback_data=f"alert_delete_{alert.get('id')}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(alerts_text, reply_markup=reply_markup, parse_mode='Markdown')
        return ConversationHandler.END
    
    elif data.startswith("alert_delete_"):
        alert_id = data.replace("alert_delete_", "")
        success = alert_manager.remove_alert(update.effective_user.id, alert_id)
        
        if success:
            await query.edit_message_text("✅ Alert deleted successfully.")
        else:
            await query.edit_message_text("❌ Error deleting alert.")
        
        return ConversationHandler.END
    
    elif data == "alert_add_price":
        # Ask user to select a coin for price alert
        markets_data = await get_market_data()
        
        keyboard = []
        row = []
        
        for i, coin in enumerate(sorted(markets_data.keys())):
            row.append(InlineKeyboardButton(coin, callback_data=f"coin_{coin}"))
            
            if (i + 1) % 3 == 0 or i == len(markets_data) - 1:
                keyboard.append(row)
                row = []
        
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="alert_cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Select a coin for your price alert:",
            reply_markup=reply_markup
        )
        
        context.user_data['alert_type'] = "price"
        return SELECTING_COIN
    
    elif data == "alert_add_liquidation":
        # Ask user to select a coin for liquidation alert
        if not context.user_data.get('tracked_wallets'):
            await query.edit_message_text(
                "You need to track a wallet first using /track <wallet_address>"
            )
            return ConversationHandler.END
        
        context.user_data['alert_type'] = "liquidation"
        
        # Get all coins with positions from tracked wallets
        position_coins = set()
        
        for wallet in context.user_data['tracked_wallets']:
            try:
                wallet_info = await get_account_info(wallet)
                
                if wallet_info and 'assetPositions' in wallet_info:
                    for position in wallet_info['assetPositions']:
                        coin = position.get('coin')
                        if coin:
                            position_coins.add((coin, wallet))
            
            except Exception as e:
                logging.error(f"Error fetching wallet positions: {e}")
        
        if not position_coins:
            await query.edit_message_text("No open positions found in your tracked wallets.")
            return ConversationHandler.END
        
        keyboard = []
        for coin, wallet in position_coins:
            keyboard.append([InlineKeyboardButton(
                f"{coin} ({wallet[:6]}...{wallet[-4:]})",
                callback_data=f"liq_{coin}_{wallet}"
            )])
        
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="alert_cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Select a position for liquidation alert:",
            reply_markup=reply_markup
        )
        
        return SELECTING_COIN
    
    elif data.startswith("coin_"):
        # User selected a coin for price alert
        coin = data.replace("coin_", "")
        context.user_data['alert_coin'] = coin
        
        # Ask if they want above or below price
        keyboard = [
            [
                InlineKeyboardButton("Price Above", callback_data="dir_above"),
                InlineKeyboardButton("Price Below", callback_data="dir_below")
            ],
            [InlineKeyboardButton("Cancel", callback_data="alert_cancel")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get current price for reference
        markets_data = await get_market_data()
        current_price = float(markets_data.get(coin, 0))
        
        await query.edit_message_text(
            f"Alert for {coin}\nCurrent price: ${current_price:.2f}\n\nDo you want to be alerted when price goes above or below your target?",
            reply_markup=reply_markup
        )
        
        return SELECTING_DIRECTION
    
    elif data.startswith("liq_"):
        # User selected a coin for liquidation alert
        _, coin, wallet = data.split("_", 2)
        
        context.user_data['alert_coin'] = coin
        context.user_data['alert_wallet'] = wallet
        
        # Ask for liquidation threshold percentage
        await query.edit_message_text(
            f"Set a liquidation warning threshold for {coin}.\n\n"
            "Enter the percentage distance to liquidation that should trigger the alert (e.g., 10 for 10%):"
        )
        
        return ENTERING_PRICE
    
    elif data.startswith("dir_"):
        # User selected price direction
        direction = data.replace("dir_", "")
        
        context.user_data['alert_direction'] = direction
        coin = context.user_data.get('alert_coin', '')
        
        # Get current price for reference
        markets_data = await get_market_data()
        current_price = float(markets_data.get(coin, 0))
        
        await query.edit_message_text(
            f"Alert for {coin}\nCurrent price: ${current_price:.2f}\n\n"
            f"Enter the target price for your alert:"
        )
        
        return ENTERING_PRICE

async def handle_price_input(update: Update, context: CallbackContext):
    """Handler for price input in alert creation"""
    try:
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        if context.user_data.get('alert_type') == "price":
            # Process price alert
            coin = context.user_data.get('alert_coin', '')
            direction = context.user_data.get('alert_direction', '')
            
            try:
                price = float(text)
                
                if price <= 0:
                    await update.message.reply_text("Price must be greater than zero. Please try again:")
                    return ENTERING_PRICE
                
                alert_data = {
                    'type': PRICE_ABOVE if direction == 'above' else PRICE_BELOW,
                    'coin': coin,
                    'price': price,
                    'one_time': False  # Persistent alert
                }
                
                alert_id = alert_manager.add_alert(user_id, alert_data)
                
                await update.message.reply_text(
                    f"✅ Alert created successfully!\n\n"
                    f"You will be notified when {coin} price goes {direction} ${price:.2f}"
                )
            
            except ValueError:
                await update.message.reply_text("Please enter a valid number for the price:")
                return ENTERING_PRICE
        
        elif context.user_data.get('alert_type') == "liquidation":
            # Process liquidation alert
            coin = context.user_data.get('alert_coin', '')
            wallet = context.user_data.get('alert_wallet', '')
            
            try:
                threshold = float(text)
                
                if threshold <= 0 or threshold > 100:
                    await update.message.reply_text("Threshold must be between 0 and 100 percent. Please try again:")
                    return ENTERING_PRICE
                
                alert_data = {
                    'type': LIQUIDATION_WARN,
                    'coin': coin,
                    'wallet_address': wallet,
                    'threshold': threshold,
                    'one_time': False  # Persistent alert
                }
                
                alert_id = alert_manager.add_alert(user_id, alert_data)
                
                await update.message.reply_text(
                    f"✅ Liquidation alert created successfully!\n\n"
                    f"You will be notified when your {coin} position is within {threshold}% of liquidation."
                )
            
            except ValueError:
                await update.message.reply_text("Please enter a valid number for the threshold percentage:")
                return ENTERING_PRICE
        
        # Clear user data
        context.user_data.pop('alert_type', None)
        context.user_data.pop('alert_coin', None)
        context.user_data.pop('alert_direction', None)
        context.user_data.pop('alert_wallet', None)
        
        return ConversationHandler.END
    
    except Exception as e:
        logging.error(f"Error processing price input: {e}")
        await update.message.reply_text("An error occurred. Please try creating your alert again.")
        return ConversationHandler.END

async def handle_cancel(update: Update, context: CallbackContext):
    """Handle cancelation of alert creation"""
    await update.message.reply_text("Alert creation cancelled.")
    return ConversationHandler.END

# Alert conversation handler
alert_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('alerts', alerts_command)],
    states={
        SELECTING_COIN: [CallbackQueryHandler(handle_alert_callback)],
        SELECTING_DIRECTION: [CallbackQueryHandler(handle_alert_callback)],
        ENTERING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input)]
    },
    fallbacks=[CommandHandler('cancel', handle_cancel)],
    per_message=True  # Added to avoid the warning
)

# This is the function that will be called regularly to check for alerts
async def check_alerts_callback(context: CallbackContext):
    """Callback function for the alert check job"""
    try:
        await alert_manager.check_alerts(context.application)
    except Exception as e:
        logging.error(f"Error in alert check job: {e}")

# Add this function to price_alerts.py
async def setup_inline_alerts(update: Update, context: CallbackContext):
    """Set up alerts using inline buttons"""
    query = update.callback_query
    
    # Create inline keyboard for alert options
    keyboard = [
        [InlineKeyboardButton("💲 Price Alert", callback_data="alert_price")],
        [InlineKeyboardButton("⚠️ Liquidation Alert", callback_data="alert_liquidation")],
        [InlineKeyboardButton("👁️ View Active Alerts", callback_data="alert_view")],
        [InlineKeyboardButton("◀️ Back to Settings", callback_data="back_to_settings")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "🔔 *Alert Configuration*\n\n"
        "Set up alerts for price movements or liquidation risks:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

def setup_alerts(application):
    """Setup the alert system and handlers"""
    # Add conversation handler
    application.add_handler(alert_conv_handler)
    
    # We'll manually check alerts every minute
    logging.info("Alert system set up - manual checking only")