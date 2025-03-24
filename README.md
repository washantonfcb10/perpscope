# Hyperliquid Telegram Bot

A Telegram bot for tracking positions, limit orders, and wallet information on the Hyperliquid exchange.

## Features

- Track multiple Hyperliquid wallet addresses
- View open positions for each wallet
- View combined portfolio across all wallets
- Monitor limit sell orders
- Easily navigate between different wallets

## Structure

The project uses a modular structure:

- `api/` - API interaction with Hyperliquid
- `core/` - Core functionality and UI components
- `handlers/` - Command and callback handlers
- `utils.py` - Utility functions
- `config.py` - Configuration settings
- `bot.py` - Main bot entry point

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/hyperliquid-bot.git
cd hyperliquid-bot
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file with your Telegram bot token:
```
TELEGRAM_TOKEN=your_telegram_bot_token_here
```

## Usage

1. Start the bot:
```bash
python bot.py
```

2. In Telegram, start a conversation with your bot using the `/start` command.

3. Use the command `/track <wallet_address>` to begin tracking a Hyperliquid wallet.

4. Use the buttons or commands to navigate and view your portfolio and orders.

## Commands

- `/start` - Start the bot and show welcome message
- `/menu` - Show the main menu
- `/help` - Show help information
- `/track <wallet_address>` - Track a wallet address
- `/wallets` - Manage tracked wallets
- `/portfolio` - View positions in tracked wallets
- `/position <coin>` - View positions for a specific coin
- `/orders` - View limit sell orders

## License

MIT License 