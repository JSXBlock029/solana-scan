# Solana Scanner Setup Guide

## Prerequisites

1. **Python 3.8+** installed on your system
2. **API Keys** from the following services:
   - CoinGecko Pro API
   - Telegram Bot API
   - OpenAI API
   - Twilio (optional, for voice calls)

## Step 1: Install Dependencies

First, activate your virtual environment if you have one, then install the required packages:

```bash
pip install -r requirements.txt
```

## Step 2: Create Environment Variables

Create a `.env` file in the same directory as `BASETRENDLINESBQCKUP1111.py` with the following content:

```env
# Required API Keys
COINGECKO_API_KEY=your_coingecko_api_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here  
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
OPENAI_API_KEY=your_openai_api_key_here

# Optional Twilio Configuration (for voice calls)
TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here

# Scanner Configuration (Optional - defaults will be used if not set)
SCAN_INTERVAL=120
DEFAULT_BUY_AMOUNT=0.1
MAX_MARKET_CAP=100000000
MIN_PRICE_CHANGE=3
MIN_LIQUIDITY_RATIO=0.02
MAX_PRICE_DROP=-25
MIN_VOLUME=500
SIGNAL_COOLDOWN=600
SENTIMENT_THRESHOLD=0.5

# Server Configuration (Optional)
SERVER_HOST=0.0.0.0
SERVER_PORT=5000
PUBLIC_URL=http://localhost:5000
```

## Step 3: Get Your API Keys

### CoinGecko Pro API Key
1. Go to [CoinGecko](https://www.coingecko.com/en/api)
2. Sign up for a Pro account
3. Get your API key from the dashboard

### Telegram Bot Token and Chat ID
1. Create a bot by messaging [@BotFather](https://t.me/BotFather) on Telegram
2. Use `/newbot` command and follow instructions
3. Get your bot token
4. To get your chat ID, message your bot and visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`

### OpenAI API Key
1. Go to [OpenAI Platform](https://platform.openai.com/)
2. Create an account and get your API key
3. Make sure you have credits in your account

### Twilio (Optional)
1. Go to [Twilio](https://www.twilio.com/)
2. Create an account and get your Account SID and Auth Token

## Step 4: Run the Scanner

Once you have all the dependencies installed and environment variables set:

```bash
python BASETRENDLINESBQCKUP1111.py
```

## Features

- **Telegram Bot**: Interactive crypto assistant that responds to messages
- **Token Scanner**: Automatically scans for promising Solana tokens
- **AI Analysis**: Uses OpenAI to provide intelligent token analysis
- **3D Quantum Charts**: Creates animated 3D price charts
- **Technical Indicators**: RSI, MACD, and EMA predictions
- **News Aggregation**: Fetches and summarizes crypto news
- **Voice Support**: Optional Twilio integration for voice calls
- **Web Interface**: Flask server for chart visualization

## Telegram Commands

- `/start` - Initialize the bot
- `/help` - Show available commands
- `/scan [address]` - Scan a specific token address
- `/wallet [address]` - Check wallet details
- `/news` - Get latest crypto news
- `/market [symbol]` - Get market analysis
- `/explain [topic]` - Explain crypto concepts
- `/stop` - Shutdown the scanner

## Troubleshooting

1. **Import Errors**: Make sure all dependencies are installed via `pip install -r requirements.txt`
2. **API Errors**: Verify all API keys are correct and have sufficient credits/permissions
3. **Chart Issues**: The scanner uses matplotlib with 'Agg' backend for compatibility
4. **Permission Errors**: Make sure the script has permission to create files and folders

## Web Interface

The scanner also runs a Flask web server on `http://localhost:5000` where you can:
- View 3D quantum charts
- Test chart generation
- Access the quantum chart generator interface

## Security Notes

- Never commit your `.env` file to version control
- Keep your API keys secure
- Use environment variables for sensitive data
- Consider using API key rotation for production use 