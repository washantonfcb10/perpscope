import matplotlib.pyplot as plt
import pandas as pd
import io
import logging
from telegram import Update, InputFile
from telegram.ext import CallbackContext

# Configure logging
logger = logging.getLogger(__name__)

# Placeholder API functions that will be injected from bot.py
get_account_info = None
get_market_data = None

def set_api_functions(account_info_func, market_data_func):
    """Set the API functions from bot.py"""
    global get_account_info, get_market_data
    get_account_info = account_info_func
    get_market_data = market_data_func

async def generate_position_chart(positions):
    """Generate a visual chart of positions"""
    if not positions:
        return None
    
    # Create a DataFrame from positions
    df = pd.DataFrame([
        {
            'coin': pos.get('coin', 'Unknown'),
            'size': float(pos.get('position', {}).get('size', 0)),
            'entry_price': float(pos.get('position', {}).get('entryPx', 0)),
            'unrealized_pnl': float(pos.get('unrealizedPnl', 0)),
            'leverage': float(pos.get('position', {}).get('leverage', 1))
        }
        for pos in positions
    ])
    
    # Skip if no positions
    if df.empty:
        return None
    
    # Create a position value column
    df['position_value'] = abs(df['size'] * df['entry_price'])
    
    # Create a figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))
    
    # Plot 1: Position sizes by coin
    df_plot1 = df.copy()
    df_plot1['direction'] = df_plot1['size'].apply(lambda x: 'Long' if x > 0 else 'Short')
    df_plot1['abs_size'] = df_plot1['size'].abs()
    
    # Create a grouped bar chart for long and short positions
    longs = df_plot1[df_plot1['direction'] == 'Long']
    shorts = df_plot1[df_plot1['direction'] == 'Short']
    
    if not longs.empty:
        ax1.bar(longs['coin'], longs['abs_size'], color='green', label='Long')
    
    if not shorts.empty:
        ax1.bar(shorts['coin'], shorts['abs_size'], color='red', label='Short')
    
    ax1.set_title('Position Sizes by Asset')
    ax1.set_xlabel('Asset')
    ax1.set_ylabel('Position Size')
    ax1.tick_params(axis='x', rotation=45)
    ax1.legend()
    
    # Plot 2: PnL by coin
    colors = ['green' if pnl >= 0 else 'red' for pnl in df['unrealized_pnl']]
    ax2.bar(df['coin'], df['unrealized_pnl'], color=colors)
    ax2.set_title('Unrealized PnL by Asset')
    ax2.set_xlabel('Asset')
    ax2.set_ylabel('Unrealized PnL ($)')
    ax2.tick_params(axis='x', rotation=45)
    
    # Add a horizontal line at 0 for PnL
    ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    
    plt.tight_layout()
    
    # Save the figure to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    
    return buf

async def generate_portfolio_summary(context, wallet_info, market_data):
    """Generate a text summary of the portfolio"""
    portfolio_text = "📊 *Portfolio Summary*\n\n"
    
    # Get account value and available margin
    account_value = float(wallet_info.get('crossMarginSummary', {}).get('accountValue', 0))
    available_margin = float(wallet_info.get('crossMarginSummary', {}).get('availableMargin', 0))
    
    portfolio_text += f"Account Value: ${account_value:.2f}\n"
    portfolio_text += f"Available Margin: ${available_margin:.2f}\n"
    
    # Calculate margin usage
    margin_used = account_value - available_margin
    margin_usage_pct = (margin_used / account_value) * 100 if account_value > 0 else 0
    
    portfolio_text += f"Margin Usage: {margin_usage_pct:.2f}%\n\n"
    
    # Summarize positions
    if 'assetPositions' in wallet_info and wallet_info['assetPositions']:
        total_long_value = 0
        total_short_value = 0
        total_pnl = 0
        
        for position in wallet_info['assetPositions']:
            coin = position.get('coin', 'Unknown')
            size = float(position.get('position', {}).get('size', 0))
            unrealized_pnl = float(position.get('unrealizedPnl', 0))
            total_pnl += unrealized_pnl
            
            # Get current price from market data
            current_price = float(market_data.get(coin, 0))
            position_value = abs(size * current_price)
            
            if size > 0:
                total_long_value += position_value
            else:
                total_short_value += position_value
        
        portfolio_text += f"Total Positions: {len(wallet_info['assetPositions'])}\n"
        portfolio_text += f"Long Exposure: ${total_long_value:.2f}\n"
        portfolio_text += f"Short Exposure: ${total_short_value:.2f}\n"
        portfolio_text += f"Net Exposure: ${(total_long_value - total_short_value):.2f}\n"
        portfolio_text += f"Total Unrealized PnL: ${total_pnl:.2f}\n"
        
        # Calculate PnL as percentage of account value
        pnl_percentage = (total_pnl / account_value) * 100 if account_value > 0 else 0
        portfolio_text += f"PnL % of Account: {pnl_percentage:.2f}%"
    else:
        portfolio_text += "No open positions"
    
    return portfolio_text

async def send_position_details(update, context, coin):
    """Send detailed position information for a specific coin"""
    if not context.user_data.get('tracked_wallets'):
        await update.message.reply_text("No wallets are being tracked. Use /track <wallet_address> to start tracking.")
        return
    
    for wallet in context.user_data['tracked_wallets']:
        try:
            wallet_info = await get_account_info(wallet)
            
            if wallet_info and 'assetPositions' in wallet_info:
                # Find position for the specified coin
                position = next((pos for pos in wallet_info['assetPositions'] if pos.get('coin') == coin), None)
                
                if position:
                    # Get market data for current price
                    markets_data = await get_market_data()
                    current_price = float(markets_data.get(coin, 0))
                    
                    size = float(position.get('position', {}).get('size', 0))
                    entry_px = float(position.get('position', {}).get('entryPx', 0))
                    unrealized_pnl = float(position.get('unrealizedPnl', 0))
                    leverage = float(position.get('position', {}).get('leverage', 1))
                    
                    direction = "Long" if size > 0 else "Short"
                    size_abs = abs(size)
                    
                    position_value = size_abs * current_price
                    price_change = ((current_price / entry_px) - 1) * 100
                    price_change_direction = "+" if price_change > 0 else ""
                    
                    liquidation_price = position.get('position', {}).get('liquidationPx', 0)
                    
                    # Create detailed position information
                    position_text = f"🪙 *{coin} Position Details*\n\n"
                    position_text += f"Direction: {direction}\n"
                    position_text += f"Size: {size_abs}\n"
                    position_text += f"Entry Price: ${entry_px:.2f}\n"
                    position_text += f"Current Price: ${current_price:.2f} ({price_change_direction}{price_change:.2f}%)\n"
                    position_text += f"Position Value: ${position_value:.2f}\n"
                    position_text += f"Leverage: {leverage}x\n"
                    position_text += f"Unrealized PnL: ${unrealized_pnl:.2f}\n"
                    
                    if liquidation_price:
                        liquidation_price = float(liquidation_price)
                        distance_to_liq = ((liquidation_price / current_price) - 1) * 100
                        distance_to_liq = abs(distance_to_liq)
                        position_text += f"Liquidation Price: ${liquidation_price:.2f} ({distance_to_liq:.2f}% away)\n"
                    
                    await update.message.reply_text(position_text, parse_mode='Markdown')
                    return
        except Exception as e:
            logger.error(f"Error fetching position data: {e}")
    
    await update.message.reply_text(f"No position found for {coin}.")

# Add these to your main position command
async def position_command(update: Update, context: CallbackContext):
    """Handler for the /position command to view position details"""
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Please provide an asset name. Usage: /position <asset>")
        return
    
    coin = context.args[0].upper()
    await send_position_details(update, context, coin)

# Enhanced portfolio command with visual chart
async def enhanced_portfolio_command(update: Update, context: CallbackContext):
    """Enhanced portfolio command with visual representation"""
    if not context.user_data.get('tracked_wallets'):
        await update.message.reply_text("No wallets are being tracked. Use /track <wallet_address> to start tracking.")
        return
    
    for wallet in context.user_data['tracked_wallets']:
        try:
            wallet_info = await get_account_info(wallet)
            
            if wallet_info and 'assetPositions' in wallet_info and wallet_info['assetPositions']:
                # Get market data for current prices
                markets_data = await get_market_data()
                
                # Generate text summary
                portfolio_text = await generate_portfolio_summary(context, wallet_info, markets_data)
                await update.message.reply_text(portfolio_text, parse_mode='Markdown')
                
                # Generate and send position chart
                chart_buf = await generate_position_chart(wallet_info['assetPositions'])
                if chart_buf:
                    await update.message.reply_photo(InputFile(chart_buf, filename='portfolio.png'))
            else:
                await update.message.reply_text("No positions found for tracked wallets.")
                
        except Exception as e:
            logger.error(f"Error generating portfolio visualization: {e}")
            await update.message.reply_text("❌ Error generating portfolio visualization. Please try again later.")