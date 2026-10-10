# Solana Telegram Scanner

An AI-powered Solana token scanner that provides real-time token information and beautiful visualizations via Telegram.

## Setup Instructions

1. Clone this repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - macOS/Linux: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in your API keys and settings
6. Run the scanner: `python BASENEWIMAGE1.2.py`

## Making 3D Quantum Charts Work

The 3D Quantum Charts feature requires your server to be accessible from the internet. Here's how to set it up:

### Option 1: Use ngrok (Easiest for Testing)

1. Download and install [ngrok](https://ngrok.com/)
2. Start your application: `python BASENEWIMAGE1.2.py`
3. In another terminal, run: `ngrok http 5000`
4. Copy the HTTPS URL provided by ngrok (e.g., `https://a1b2c3d4.ngrok.io`)
5. Set this URL in your `.env` file: `PUBLIC_URL=https://a1b2c3d4.ngrok.io`
6. Restart your application

### Option 2: Use a Public Server

If you're running on a server with a public IP:

1. Make sure port 5000 is open on your firewall
2. Set `PUBLIC_URL=http://your-server-ip:5000` in your `.env` file
3. For better security, consider setting up HTTPS with a reverse proxy

### Option 3: Use a Domain Name

For production use:

1. Register a domain and point it to your server
2. Set up HTTPS with Let's Encrypt
3. Configure a reverse proxy (Nginx, Apache, etc.)
4. Set `PUBLIC_URL=https://your-domain.com` in your `.env` file

## Testing the Charts

1. After starting the application, visit `http://localhost:5000/` in your browser
2. Enter a token ID (like "solana") and address
3. Click "Generate Quantum Chart" to test if the chart generation works

## Troubleshooting

- If the charts don't appear in Telegram, check the server logs for URL-related warnings
- Ensure your `PUBLIC_URL` is accessible from the internet
- Telegram only supports URLs that are publicly accessible

## Requirements

- Python 3.8+
- CoinGecko API key
- Telegram Bot Token
- OpenAI API key (for Claude integration) 
## Tests

```bash
pip install -r requirements-test.txt
pytest tests
```

27 tests cover the free-LLM rotation in `free_llm.py` with in-memory fake providers: rotating past empty replies, leaked reasoning and broken JSON; classifying errors correctly (a bad key disables a provider, a VPN 403 or a rate limit only cools it, a zero-quota plan disables it); shedding JSON mode on a 400; and never reporting an untested key as "ready". Every protection was verified by a deliberate mutation the suite catches (7/7). External network access is blocked during tests.
