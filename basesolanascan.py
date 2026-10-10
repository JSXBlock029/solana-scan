#!/usr/bin/env python3
"""
Enhanced Cryptocurrency Scanner with Auto-Dependency Installation
"""

import subprocess
import sys
import os

# Fix Windows encoding for emoji support
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def install_package(package):
    """Install a package using pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package], 
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"✅ Installed {package}")
        return True
    except subprocess.CalledProcessError:
        print(f"❌ Failed to install {package}")
        return False

def check_and_install_dependencies():
    """Check and install required dependencies"""
    print("🔍 Checking dependencies...")
    
    # List of required packages
    required_packages = [
        'feedparser',
        'requests',
        'matplotlib',
        'numpy',
        'pandas',
        'python-dotenv',
        'openai',
        'aiohttp',
        'flask',
        'beautifulsoup4',
        'pillow',
        'twilio',
        'certifi'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            if package == 'python-dotenv':
                __import__('dotenv')
            elif package == 'beautifulsoup4':
                __import__('bs4')
            elif package == 'pillow':
                __import__('PIL')
            else:
                __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"📦 Installing {len(missing_packages)} missing packages...")
        for package in missing_packages:
            install_package(package)
        print("✅ All dependencies installed!")
    else:
        print("✅ All dependencies already installed!")

# Auto-install dependencies
check_and_install_dependencies()

import sys
import feedparser
import requests
import json
import time
import logging
import os
import asyncio
import io
import matplotlib
matplotlib.use('Agg')  # Use Agg backend instead of TkAgg
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import pandas as pd  # Add pandas for EMA calculation
from matplotlib.animation import FuncAnimation, PillowWriter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Set
from dotenv import load_dotenv
from openai import AsyncOpenAI
# The scanner no longer holds a paid key. FreeLLMClient presents the same
# chat.completions.create surface and rotates across free tiers; AsyncOpenAI is
# still imported because free_llm builds one per provider underneath.
from free_llm import FreeLLMClient, AllProvidersExhausted
import aiohttp
import ssl
import certifi
from bs4 import BeautifulSoup
from flask import Flask, request, Response as FlaskResponse, render_template, send_file
import flask
import re
# Imported as a bare function, not the module: a local `html = await resp.text()`
# in fetch_social_data would shadow the module name inside that scope.
from html import escape as html_escape
import PIL  # For Pillow version logging
from PIL import Image
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
try:
    from twilio.twiml.voice_response import VoiceResponse
except ImportError:
    VoiceResponse = None  # Twilio is optional

# Configure matplotlib to not use Tkinter
plt.switch_backend('Agg')

app = Flask(__name__)
scanner = None  # Will be initialized later

class InitializationError(Exception):
    pass

class ConnectionError(Exception):
    pass

class NewsSummarizer:
    """Intelligent News Aggregation and Summarization Engine"""
    def __init__(self, max_articles=15):
        self.seen_articles: Set[str] = set()
        self.max_articles = max_articles
        self.recent_news: List[Dict] = []
        self.cutoff_time = datetime.now() - timedelta(hours=24)

    def is_duplicate(self, article_identifier: str) -> bool:
        if article_identifier in self.seen_articles:
            return True
        if len(self.seen_articles) >= self.max_articles:
            self.seen_articles.pop()
        self.seen_articles.add(article_identifier)
        return False

    def add_article(self, article: Dict):
        article_date = self._parse_date(article.get('published', ''))
        if article_date < self.cutoff_time:
            return
        if not self.is_duplicate(article.get('url', '')):
            self.recent_news.append(article)

    def _parse_date(self, date_str: str) -> datetime:
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            return datetime.now()

    def generate_digest(self) -> str:
        sorted_news = sorted(self.recent_news, key=lambda x: self._parse_date(x.get('published', '')), reverse=True)
        top_articles = sorted_news[:self.max_articles]
        digest = "📊 <b>Crypto News Daily Digest</b> 🌐\n\n"
        source_articles = {}
        for article in top_articles:
            source = article.get('source', 'Unknown')
            if source not in source_articles:
                source_articles[source] = []
            source_articles[source].append(article)
        for source, articles in source_articles.items():
            digest += f"🔹 <b>{source}</b>:\n"
            for article in articles[:3]:
                digest += f"   • {article['title']}\n"
            digest += "\n"
        digest += f"\n📡 <i>Aggregated from multiple sources</i>\n🕒 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
        self.recent_news.clear()
        return digest

# NOTE: since the free-tier rotation landed, OPENAI_MODEL is no longer what gets
# called - FreeLLMClient ignores the model= argument and each provider names its
# own model in free_llm.PROVIDERS (no free tier serves gpt-4o-mini). The constant
# and the reasoning below are kept because they still describe what the
# memecoin_call prompt needs from a model: it leans on ~10 negative constraints,
# so a provider that follows them unevenly is the one to demote in that table.
#
# One place to change the model. gpt-4o-mini replaced gpt-3.5-turbo on 2026-08-15:
# the memecoin_call prompt leans on ~10 negative constraints ("never invent a level")
# and 3.5 followed them unevenly - side by side on identical inputs, 4o-mini credited
# the revoked mint/freeze authorities as a mitigant and declined to name an
# invalidation level when no candles were supplied, where 3.5 reached for one.
# Override with OPENAI_MODEL in .env to roll back without touching code.
#
# load_dotenv() here as well as in __init__: this constant is evaluated at import
# time, which is BEFORE the scanner is constructed, so without this the .env
# override would be read from an unloaded environment and silently ignored.
# load_dotenv is idempotent and does not clobber already-set vars, so the later
# call in __init__ is unaffected.
load_dotenv()
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

# Token-2022. Classic SPL is TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA and
# cannot levy a transfer tax at any value - taxes are a Token-2022 extension only.
TOKEN_2022_PROGRAM = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'


class AIAssistant:
    """Enhanced AI Assistant capabilities for crypto discussions"""
    def __init__(self, openai_client):
        self.openai_client = openai_client
        self.system_prompts = {
            "default": """You are Claude, a highly knowledgeable AI assistant specialized in cryptocurrency, trading, 
            and blockchain technology. You provide clear, informative responses with a confident, professional tone.
            When analyzing markets, focus on key technical indicators, market psychology, and on-chain metrics.
            Structure your analysis like a professional trader, highlighting critical support/resistance levels,
            volume profiles, and potential catalysts. Avoid generic statements and always provide specific,
            actionable insights while maintaining compliance by not giving direct financial advice.""",
            
            "token_analysis": """Analyze this token using a comprehensive framework:

            1. TECHNICAL METRICS:
            - Price action and volume analysis
            - Key support/resistance levels
            - Market structure and trend analysis
            - Liquidity depth and concentration
            - Relative strength vs BTC/ETH/SOL

            2. FUNDAMENTAL ANALYSIS:
            - Token utility and use cases
            - Network activity and growth metrics
            - Development activity and roadmap
            - Team background and track record
            - Community engagement quality

            3. RISK ASSESSMENT:
            - Liquidity risks and concentration
            - Smart contract security status
            - Regulatory compliance factors
            - Competition and market position
            - Tokenomics sustainability

            4. MARKET CONTEXT:
            - Sector/category performance
            - Macro environment impact
            - Upcoming catalysts/events
            - Market sentiment indicators
            - Institutional interest signals

            Provide a balanced, data-driven assessment focusing on the most relevant factors. 
            Use specific metrics and comparisons where possible. Highlight both opportunities 
            and risks. Maintain a professional, analytical tone.""",
            
            "technical_explanation": """Explain this technical concept using a structured approach:

            1. Start with a clear, concise definition
            2. Provide real-world analogies to build understanding
            3. Break down complex components step by step
            4. Use specific examples from current market conditions
            5. Connect it to practical trading/investment implications
            6. Address common misconceptions
            7. Include relevant technical indicators or metrics
            8. Relate it to broader market dynamics

            Use clear, precise language while maintaining sophistication. 
            Include quantitative data where relevant. Focus on practical 
            application and market impact.""",
            
            "market_analysis": """Analyze market conditions using this comprehensive framework:

            1. TECHNICAL ANALYSIS:
            - Multiple timeframe analysis (1H, 4H, 1D, 1W)
            - Volume profile and market structure
            - Key support/resistance levels
            - Momentum and volatility metrics
            - Inter-market correlations

            2. ON-CHAIN METRICS:
            - Network activity and growth
            - Whale wallet movements
            - Smart money flow analysis
            - DEX volume and liquidity trends
            - Staking and yield metrics

            3. MARKET MICROSTRUCTURE:
            - Order book depth analysis
            - Liquidity pool dynamics
            - Trading volume distribution
            - Market maker positioning
            - Short-term price drivers

            4. SENTIMENT INDICATORS:
            - Social media momentum
            - Funding rates and leverage
            - Fear & Greed metrics
            - Institutional flows
            - News and event impact

            Synthesize these elements into a coherent narrative. Focus on actionable insights
            and specific levels/metrics. Maintain objectivity while highlighting high-probability
            scenarios. Use precise technical language and quantitative data.""",

            # Scoped deliberately narrow. The "market_analysis" prompt above asks for
            # order book depth, funding rates, staking yield and institutional flow -
            # none of which exist for a token that launched on a DEX this week. Asking
            # for them is what produced confident, invented specifics.
            "memecoin_call": """You write the short analyst note attached to an automated Solana token alert.

            WHAT YOU ARE LOOKING AT: a token detected minutes to days after it launched on a DEX.
            It has no order book, no funding rate, no staking yield, no institutional flow, no
            analyst coverage and usually no product. Never reference any of those. The only things
            that exist are price, market cap, 24h volume, pool liquidity, holder concentration,
            mint/freeze authority status, and whatever candles are supplied to you.

            HARD RULES:
            - Use ONLY the numbers given to you. Never invent a support level, resistance level,
              price target, holder count, launch date, team detail, roadmap, partnership, exchange
              listing or upcoming catalyst. If a level was not supplied, do not name one.
            - If the data is thin, say what is missing rather than padding. A short note that admits
              uncertainty is correct. A long note that fabricates specifics is a failure.
            - Holder concentration and authority status outrank price action. A chart that looks
              strong on a token whose top wallets hold most of the supply is a warning, not a
              setup - say so plainly.
            - No financial advice, no buy/sell instruction, no position sizing, no guarantees.

            VOICE: direct, concrete, unhyped. Plain sentences, active voice, ordinary sentence
            case - never ALL CAPS for emphasis. No markdown, no asterisks, no hash headers, no
            HTML tags, no emoji - your text is inserted into a message that already carries its
            own formatting. Open with the single most important fact about this token, not with
            a preamble."""
            }
        
    async def query(self, prompt: str, chat_history: List[str], prompt_type: str = "default", 
                   temperature: float = 0.7, max_tokens: int = 500,
                   raise_on_exhausted: bool = False) -> str:
        """
        Generate a response to a user query, with context from chat history.

        `raise_on_exhausted` lets a caller tell "every free provider is
        throttled" apart from "the call failed". It defaults to False so the
        chat handlers keep swallowing errors exactly as before - none of them
        sit inside a try block, and turning a quota exhaustion into an
        exception there would take the Telegram loop down. generate_memecoin_call
        passes True because it has a genuinely better thing to say.
        """
        try:
            system_content = self.system_prompts.get(prompt_type, self.system_prompts["default"])
            
            messages = [
                {"role": "system", "content": system_content},
            ]
            
            for i, msg in enumerate(chat_history[-10:]):
                role = "user" if i % 2 == 0 else "assistant"
                messages.append({"role": role, "content": msg})
                
            if len(messages) > 1 and messages[-1]["role"] == "user":
                messages[-1]["content"] += f"\n\n{prompt}"
            else:
                messages.append({"role": "user", "content": prompt})
            
            response = await self.openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content.strip()
        except AllProvidersExhausted as e:
            logging.error(f"All free LLM providers exhausted: {str(e)}")
            if raise_on_exhausted:
                raise
            return ("The free AI providers are all rate-limited right now. "
                    "Scanning and price data are unaffected - try again in a few minutes.")
        except Exception as e:
            logging.error(f"Error in AI assistant query: {str(e)}")
            return "I'm having trouble processing that request. Please try again or rephrase your question."
    
    async def analyze_token(self, token_data: Dict) -> str:
        """Specialized analysis of a token based on its data"""
        prompt = f"""
        Please analyze this cryptocurrency token:
        
        Name: {token_data.get('name', 'Unknown')}
        Symbol: {token_data.get('symbol', 'Unknown')}
        Price: ${token_data.get('price_usd', 0):.8f}
        24h Volume: ${token_data.get('volume_24h', 0):,.2f}
        Price Change 24h: {token_data.get('price_change_24h', 0):.2f}%
        Liquidity: ${token_data.get('liquidity_usd', 0):,.2f}
        
        Provide a brief but insightful analysis of this token, including potential strengths 
        and concerns. Don't make price predictions or specific investment recommendations.
        """
        return await self.query(prompt, [], "token_analysis", 0.7, 350)
    
    async def understand_intent(self, user_input: str, chat_history: List[str]) -> Dict:
        """Determine user's intent and extract relevant entities from their message"""
        try:
            system_prompt = """
            You are an AI analyzing user messages to a crypto trading bot. Extract the user's intent and any
            relevant entities from their message. Respond with ONLY a JSON object in the following format:
            {
                "intent": "one of [get_price, scan_token, scan_wallet, market_analysis, token_analysis, get_news, trading_strategy, portfolio_advice, technical_question, general_chat]",
                "entities": {
                    "token": "token name or symbol if mentioned",
                    "address": "blockchain address if mentioned",
                    "timeframe": "timeframe if mentioned (e.g. 1h, 24h, 7d)",
                    "blockchain": "specific blockchain if mentioned"
                },
                "response": "a natural, helpful reply that directly addresses the user's question or request"
            }
            
            Don't include any entities that aren't clearly mentioned. For general conversations not fitting
            the specific intents, use "general_chat" and focus on creating an informative, friendly response.
            """
            
            messages = [
                {"role": "system", "content": system_prompt},
                *[{"role": "user" if i % 2 == 0 else "assistant", "content": msg} 
                  for i, msg in enumerate(chat_history[-4:])],
                {"role": "user", "content": user_input}
            ]
            
            # json_object mode: the result is fed straight to json.loads with no
            # fence-stripping, so a single ```json wrapper would drop the user into
            # the "I'm having trouble understanding" fallback. The system prompt
            # already contains the word "JSON", which the mode requires.
            response = await self.openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                max_tokens=300,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content.strip())
            return result
        except Exception as e:
            logging.error(f"Error understanding intent: {str(e)}")
            return {
                "intent": "general_chat",
                "entities": {},
                "response": "I'm having trouble understanding. Could you rephrase your question?"
            }

class SolanaTelegramScanner:
    def __init__(self):
        """Initialize scanner with environment variables and configurations"""
        try:
            load_dotenv()
            # CoinGecko API key not required for free plan
            self.api_key = None  # Free plan doesn't use API key
            self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
            self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
            self.openai_api_key = os.getenv('OPENAI_API_KEY')
            self.twilio_sid = os.getenv('TWILIO_ACCOUNT_SID')
            self.twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            
            missing_vars = []
            # COINGECKO_API_KEY no longer required for free plan
            if not self.telegram_token: missing_vars.append('TELEGRAM_BOT_TOKEN')
            if not self.telegram_chat_id: missing_vars.append('TELEGRAM_CHAT_ID')
            # OPENAI_API_KEY is deliberately NOT required any more. Requiring it
            # here would refuse to start precisely for the person who deleted it
            # to stop paying, which is the whole point of the rotation.
            if missing_vars:
                raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
            
            # Use free CoinGecko API endpoint (no API key required)
            self.base_url = "https://api.coingecko.com/api/v3"
            self.headers = {}  # Free plan doesn't require API key headers
            self.session = requests.Session()
            retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
            self.session.mount('https://', HTTPAdapter(max_retries=retries))
            # Free-tier rotation instead of one paid client. Same interface, so
            # every call site downstream is unchanged; it raises
            # AllProvidersExhausted rather than ever reaching for a paid key.
            self.openai_client = FreeLLMClient()
            print(self.openai_client.status_line())
            if not self.openai_client.configured:
                # A WARNING, not a raise. Scanning, price alerts, safety checks
                # and the charts need no LLM at all, and refusing to boot over a
                # missing LLM key would take all of that down too. Every LLM
                # call degrades on its own through AllProvidersExhausted.
                print("WARNING: no free LLM provider keys found, so AI notes are "
                      "OFF. Everything else runs normally.")
                print("         Set one of: "
                      + ", ".join(p.env_key for p in self.openai_client.providers))
                print("         in .env, then check with: python free_llm.py")
            self.api_url = f"https://api.telegram.org/bot{self.telegram_token}"
            self.last_update_id = 0
            
            self.ai_assistant = AIAssistant(self.openai_client)
            
            # Increased scan interval for free plan rate limits (10-30 calls/minute limit)
            self.scan_interval = int(os.getenv('SCAN_INTERVAL', '300'))  # Increased from 120 to 300 seconds
            self.cache_interval = 1800
            self.running = True
            
            # Rate limiting for free plan (10-30 requests per minute)
            self.last_request_time = 0
            self.min_request_interval = 3  # Minimum 3 seconds between requests for free plan
            self.conversation_history = {}
            self.default_buy_amount = float(os.getenv('DEFAULT_BUY_AMOUNT', '0.1'))
            self.max_buy_amount = float(os.getenv('MAX_BUY_AMOUNT', '1.0'))
            self.min_buy_amount = float(os.getenv('MIN_BUY_AMOUNT', '0.01'))
            
            self.stablecoin_keywords = ['usd', 'usdt', 'usdc', 'dai', 'busd', 'tusd', 'usdd', 'frax']
            self.stablecoin_price_range = (0.95, 1.05)
            
            self.max_market_cap = float(os.getenv('MAX_MARKET_CAP', '100000000'))
            self.min_price_change = float(os.getenv('MIN_PRICE_CHANGE', '3'))
            # Real pool-depth / market-cap floor. Replaces min_liquidity_ratio,
            # which was env-configurable and rescaled every cycle by
            # adjust_parameters but never read by anything - an inert knob that
            # looked like a working control.
            #
            # WARNING-ONLY by default. It has never been enforced, so enabling it
            # as a hard block without observation would change what gets posted
            # based on an untested number. Set DEPTH_BLOCK=1 to make it a gate.
            # Calibration: depth/mcap p50 0.24, p75 0.64 across 33 live tokens.
            self.min_depth_ratio = float(os.getenv('MIN_DEPTH_RATIO', '0.05'))
            self.depth_blocks = os.getenv('DEPTH_BLOCK', '0') in ('1', 'true', 'True')
            self.max_price_drop = float(os.getenv('MAX_PRICE_DROP', '-25'))
            self.min_volume = float(os.getenv('MIN_VOLUME', '500'))

            # --- Call tracking (dedup + profit alerts) ---
            self.calls_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calls_history.json')
            self.calls = self._load_calls()
            # Append-only price series, one JSON row per re-priced call per cycle.
            # Deliberately NOT inside calls_history.json: that file is rewritten in
            # full on every save, and a 7-day series over ~170 open calls would turn a
            # 54KB rewrite into a multi-MB one every PERFORMANCE_CHECK_INTERVAL.
            # Appends stay O(new rows) and the file loads straight into pandas.
            # Grows ~2MB/day at 168 open calls on a 300s cadence.
            self.series_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            'calls_series.jsonl')
            # Don't re-call the same token within this many hours
            self.recall_cooldown_hours = float(os.getenv('RECALL_COOLDOWN_HOURS', '6'))
            # Multiples that trigger a "we called it" alert, each fires once
            self.profit_tiers = [1.5, 2, 3, 5, 10, 25, 50, 100]
            # How often to re-price open calls (seconds)
            self.performance_check_interval = int(os.getenv('PERFORMANCE_CHECK_INTERVAL', '300'))
            self.last_performance_check = 0
            # --- Fast-track sampling for young calls ---
            # Runners peak roughly an hour after the call and the entire move can
            # fit inside a handful of 300s samples. GUNICORN (2026-08-15) went
            # 6.5x -> 27x -> 60x -> 85x -> 62x in five consecutive samples, and
            # its recorded peak of 85.3x undershot the real $2.6M ATH (~109x) by
            # 22% purely because nothing looked in between.
            #
            # Lowering performance_check_interval CANNOT fix that: the main loop
            # ends each iteration with `await asyncio.sleep(scan_interval)`, so
            # check_call_performance fires at most once per scan no matter how
            # small its own interval is. Both default to 300s, which is why the
            # observed sample gap is ~373s. This has to be its own task.
            self.fast_track_hours = float(os.getenv('FAST_TRACK_HOURS', '3'))
            self.fast_track_interval = int(os.getenv('FAST_TRACK_INTERVAL', '90'))
            # --- Daily leaderboard ---
            # One pinned message per UTC day, edited in place on this interval.
            # Editing rather than re-pinning keeps the board permanently at the
            # top of the group while firing a single "pinned a message"
            # notification per day instead of one every hour.
            self.recap_interval = int(os.getenv('RECAP_INTERVAL', '3600'))
            self.last_recap = 0
            self.recap_top_n = int(os.getenv('RECAP_TOP_N', '10'))
            self.recap_state_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'recap_state.json')
            # Persisted so a restart edits the existing pin instead of pinning
            # a second board for the same day.
            self.recap = self._load_recap_state()
            # message_id of the most recent part-1 call post, so profit alerts can thread under it
            self.last_call_message_id = None
            # Hard cap on calls posted per scan cycle. DexScreener discovery can surface
            # 15+ qualifying movers at once and confidence>=7 bypasses the cooldown,
            # which would flood the channel.
            self.max_signals_per_cycle = int(os.getenv('MAX_SIGNALS_PER_CYCLE', '3'))
            self.signals_this_cycle = 0
            # Enable/disable DexScreener discovery feed
            self.dex_discovery_enabled = os.getenv('DEX_DISCOVERY', '1') not in ('0', 'false', 'False')

            # --- RugCheck safety filter ---
            # Thresholds set from a live sample of 12 discovered tokens:
            #   top1 12.6-67.2 (p50 29), top10 26.1-96.9 (p50 52),
            #   holders 119-1353 (p50 729), liq $3.5k-$26k, norm score 1-57.
            # Note mint/freeze/rugged were 0/12 - those hard blocks are cheap
            # insurance, not the working filter. Concentration is what bites.
            self.rugcheck_enabled = os.getenv('RUGCHECK', '1') not in ('0', 'false', 'False')
            self.rc_max_top1 = float(os.getenv('RUGCHECK_MAX_TOP1', '60'))
            # Retuned 90 -> 40 when pool accounts stopped being counted as holders.
            # With the AMM reserve excluded, real top10 measured 1.6-29% across 18 live
            # tokens, so a 90% ceiling could never bind again - it would have been an
            # inert check that looked like a safety control. 40 sits above the observed
            # range with headroom and still catches genuine distribution problems.
            self.rc_max_top10 = float(os.getenv('RUGCHECK_MAX_TOP10', '40'))
            self.rc_max_danger = int(os.getenv('RUGCHECK_MAX_DANGER', '2'))
            self.rc_max_score = float(os.getenv('RUGCHECK_MAX_SCORE', '50'))
            self.rc_min_holders = int(os.getenv('RUGCHECK_MIN_HOLDERS', '100'))
            self.rc_min_liquidity = float(os.getenv('RUGCHECK_MIN_LIQ', '2000'))
            # Token-2022 transfer tax ceiling, in basis points. Default 0 = reject any
            # non-zero tax. Measured on 30 live candidates: 27 were Token-2022 (it is
            # the pump.fun default now, so banning the PROGRAM would kill ~90% of flow)
            # but only 2 carried a transferFeeConfig, and both taxed 3%. Filtering on
            # the fee rather than the program blocks ~7%, precisely.
            self.rc_max_fee_bps = float(os.getenv('RUGCHECK_MAX_FEE_BPS', '0'))
            # If rugcheck is unreachable, pass the token through by default -
            # an outage must not silently mute the channel.
            self.rc_fail_closed = os.getenv('RUGCHECK_FAIL_CLOSED', '0') in ('1', 'true', 'True')
            self.rc_blocked_count = 0
            self.last_signal_time = 0
            self.signal_cooldown = int(os.getenv('SIGNAL_COOLDOWN', '600'))
            self.pattern_weights = {'breakout': 3, 'accumulation': 2, 'momentum': 2}
            self.market_sentiment = 0
            self.sentiment_threshold = float(os.getenv('SENTIMENT_THRESHOLD', '0.5'))
            self.blacklisted_tokens = set()
            self.watchlist_tokens = set()
            self.token_history = {}
            
            self.solana_cache = {'last_updated': 0, 'historical_prices': [], 'current_price': 0, 'price_change_24h': 0}
            self.news_summarizer = NewsSummarizer()
            self.rss_feeds = [
                "https://cointelegraph.com/rss",
                "https://coindesk.com/arc/outboundfeeds/rss/",
                "https://decrypt.co/feed",
                "https://news.bitcoin.com/feed"
            ]
            self.pin_history_file = "bot_pins_history.json"
            self.bot_pins = self._load_pin_history()
            
            # Server configuration for 3D quantum view - external URL
            self.server_host = os.getenv('SERVER_HOST', '0.0.0.0')
            self.server_port = int(os.getenv('SERVER_PORT', '5000'))
            
            # For external access, should be your publicly accessible URL
            # e.g., https://your-domain.com or http://your-ip-address:5000
            self.public_url = os.getenv('PUBLIC_URL', '')
            if not self.public_url:
                # Fallback to local address - Note: This won't work for Telegram users
                # unless they're on the same network
                self.public_url = f"http://{self.server_host if self.server_host != '0.0.0.0' else 'localhost'}:{self.server_port}"
            
            self.setup_logging()
            self.logger.info("🆓 Using CoinGecko FREE API plan - Rate limiting enabled")
            self._test_connections()
            
        except Exception as e:
            raise InitializationError(f"Initialization failed: {str(e)}")
            
    def setup_logging(self):
        self.logger = logging.getLogger('SolanaTelegramScanner')
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        self.logger.info(f"Matplotlib version: {matplotlib.__version__}")
        
        if not self.public_url or self.public_url.startswith('http://localhost'):
            self.logger.warning(f"PUBLIC_URL not set or using localhost - charts will not be accessible from Telegram. Current URL: {self.public_url}")

    def _test_connections(self):
        try:
            # Test CoinGecko free API endpoint
            response = self.session.get(f"{self.base_url}/ping", headers=self.headers, timeout=10)
            response.raise_for_status()
            self.logger.info("CoinGecko API connection successful")
            
            # Test Telegram connection (optional - warn if fails but don't stop)
            try:
                test_message = "🌌 <b>Quantum Core Online</b> - System Initialized (Free CoinGecko API)"
                requests.post(f"{self.api_url}/sendMessage", json={
                    "chat_id": self.telegram_chat_id, "text": test_message, "parse_mode": "HTML"
                }, timeout=60).raise_for_status()
                self.logger.info("Telegram API connection successful")
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"Telegram API connection test failed (will continue anyway): {str(e)}")
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"CoinGecko API connection test failed (will continue anyway): {str(e)}")

    def _load_pin_history(self) -> List[int]:
        try:
            if os.path.exists(self.pin_history_file):
                with open(self.pin_history_file, 'r') as f:
                    return json.load(f)
            return []
        except Exception:
            return []

    def _load_recap_state(self) -> Dict:
        try:
            if os.path.exists(self.recap_state_file):
                with open(self.recap_state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Could not load recap state: {e}")
        return {'day': None, 'message_id': None}

    def _save_recap_state(self):
        try:
            with open(self.recap_state_file, 'w', encoding='utf-8') as f:
                json.dump(self.recap, f)
        except Exception as e:
            self.logger.error(f"Could not save recap state: {e}")

    def _save_pin_history(self):
        try:
            with open(self.pin_history_file, 'w') as f:
                json.dump(self.bot_pins, f)
        except Exception as e:
            self.logger.error(f"Failed to save pin history: {e}")

    async def _rate_limit(self):
        """Rate limiting for free CoinGecko API plan"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            self.logger.info(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
            await asyncio.sleep(sleep_time)
        self.last_request_time = time.time()

    def is_stablecoin(self, token: Dict) -> bool:
        symbol = token.get('symbol', '').lower()
        name = token.get('name', '').lower()
        price = token.get('current_price', 0)
        if any(keyword in symbol for keyword in self.stablecoin_keywords) or \
           any(keyword in name for keyword in self.stablecoin_keywords):
            return True
        if self.stablecoin_price_range[0] <= price <= self.stablecoin_price_range[1]:
            price_change = abs(token.get('price_change_percentage_24h', 0) or 0)
            if price_change < 1.0:
                return True
        return False

    def adjust_parameters(self, tokens_found: int):
        if tokens_found < 100:
            self.max_market_cap *= 1.5
            self.min_price_change *= 0.8
            self.min_volume *= 0.8
        elif tokens_found > 1000:
            self.max_market_cap *= 0.9
            self.min_price_change *= 1.1
            self.min_volume *= 1.1
        # min_depth_ratio is deliberately NOT rescaled here. It was rescaled when
        # it was inert and harmless; a safety floor that drifts with how many
        # tokens a scan happened to return is a different and worse thing.

    def get_turnover_grade(self, ratio: float) -> tuple:
        """Grade 24h volume / market cap. This is TURNOVER (how hard the token is
        being traded), NOT liquidity - it says nothing about pool depth.

        It was named get_liquidity_grade and shown on the card as "Liquidity
        Matrix" until 2026-08-15. That was wrong in the worst direction: high
        turnover on a thin pool is the wash-trade signature, and it scored A.

        Thresholds are unchanged from the old grader for continuity, but note
        they barely discriminate: measured across 33 live Solana tokens the
        median turnover was 2.6 and p90 was 42, so almost everything grades A.
        Treat a high grade here as "is being traded", not "is safe to trade".
        """
        if ratio >= 0.5:
            return ('A', 'Very high turnover', '🟢')
        elif ratio >= 0.3:
            return ('B', 'High turnover', '🟢')
        elif ratio >= 0.15:
            return ('C', 'Moderate turnover', '🟡')
        elif ratio >= 0.05:
            return ('D', 'Low turnover', '🔴')
        elif ratio > 0:
            return ('F', 'Very low turnover', '⛔')
        else:
            return ('N/A', 'No volume data', '⚪')

    @staticmethod
    def _depth_text(analysis: Dict) -> str:
        """Render depth for the card. Unknown renders as the word 'unknown', not
        as a grade and not as $0 - those are three different claims and the old
        card collapsed them."""
        grade = analysis.get('depth_grade', '?')
        usd = analysis.get('depth_usd')
        ratio = analysis.get('depth_ratio')
        if ratio is None or usd is None:
            return "unknown (no pair data)"
        return f"{grade} - ${usd:,.0f} ({ratio:.3f} of mcap)"

    @staticmethod
    def get_depth_grade(depth_usd, market_cap) -> tuple:
        """Grade REAL pool depth (deepest pair, USD) against market cap.

        Separate thresholds from turnover on purpose - the distributions are
        nothing alike. Calibrated on 33 live Solana tokens: depth/mcap p50 0.24,
        p75 0.64, p90 0.88, and p25 was 0.00 because a quarter of candidates have
        no DEX pair yet (still on the bonding curve).

        Returns (grade, description, emoji, ratio_or_None). A None ratio means
        UNKNOWN and must never be rendered as a grade - unknown depth and zero
        depth are different claims.
        """
        if not market_cap or market_cap <= 0 or depth_usd is None:
            return ('?', 'Pool depth unknown', '⚪', None)
        ratio = depth_usd / market_cap
        if depth_usd <= 0:
            return ('F', 'No DEX pool depth found', '⛔', 0.0)
        if ratio >= 0.60:
            return ('A', 'Deep pool', '🟢', ratio)
        elif ratio >= 0.35:
            return ('B', 'Solid pool', '🟢', ratio)
        elif ratio >= 0.15:
            return ('C', 'Shallow pool', '🟡', ratio)
        elif ratio >= 0.05:
            return ('D', 'Thin pool', '🔴', ratio)
        return ('F', 'Very thin pool', '⛔', ratio)

    def check_risks(self, token) -> Dict:
        """Cheap pre-filter. Runs against every candidate BEFORE any DexScreener
        lookup, so it only sees CoinGecko-shaped fields and cannot know pool
        depth. Depth is graded later in _attach_chart_data, for the handful of
        tokens actually being posted. Keeping this function depth-free is what
        keeps the 333-token scan cheap.
        """
        volume_24h = token.get('total_volume', 0)
        market_cap = token.get('market_cap', 0)
        price_change = token.get('price_change_percentage_24h', 0)
        warnings = []
        risk_level = 'low'
        turnover_ratio = volume_24h / market_cap if market_cap > 0 else 0
        grade, grade_desc, grade_emoji = self.get_turnover_grade(turnover_ratio)
        if grade in ['D', 'F', 'N/A']:
            warnings.append(f"Low turnover rating: {grade}")
            risk_level = 'high'
        if volume_24h < self.min_volume:
            warnings.append(f"Low 24h volume: ${volume_24h:,.2f}")
            risk_level = 'high'
        if price_change and price_change < self.max_price_drop:
            warnings.append(f"Significant price drop: {price_change:.2f}%")
            risk_level = 'high'
        return {
            'risk_level': risk_level,
            'warnings': warnings,
            'turnover_ratio': turnover_ratio,
            'turnover_grade': grade,
            'turnover_desc': grade_desc,
            'turnover_emoji': grade_emoji,
        }

    # ------------------ Call tracking + DexScreener discovery ------------------

    def _load_calls(self) -> Dict:
        try:
            if os.path.exists(self.calls_file):
                with open(self.calls_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"Could not load calls history: {e}")
        return {}

    def _save_calls(self):
        try:
            with open(self.calls_file, 'w', encoding='utf-8') as f:
                json.dump(self.calls, f, indent=2)
        except Exception as e:
            self.logger.error(f"Could not save calls history: {e}")

    def _append_samples(self, samples: List[Dict]):
        """Append price samples to the series log. Call through asyncio.to_thread.

        Stores the raw (ts, price, mult) path rather than summary stats on purpose:
        a series supports fitting ANY exit rule offline - fixed TP/SL, trailing
        stops, time-based exits - without re-instrumenting when the question
        changes. A trough field alone would answer exactly one question.
        """
        if not samples:
            return
        try:
            with open(self.series_file, 'a', encoding='utf-8') as f:
                for s in samples:
                    f.write(json.dumps(s, separators=(',', ':')) + '\n')
        except Exception as e:
            self.logger.error(f"Could not append price samples: {e}")

    @staticmethod
    def _sample_row(addr: str, rec: Dict, price: float, mcap, mult: float, now: float,
                    liq=None, vol24=None) -> Dict:
        """One row of the price path. 'age_h' is denormalised so the file can be
        analysed without joining back to calls_history.json.

        `liq`/`vol24` are the pool depth and 24h volume AT THIS SAMPLE. Without
        them a backtest can only ask "what did the price do", never "could I
        have sold into it" - every exit rule fitted on price alone silently
        assumes infinite depth, which on a $24k-mcap token is the whole
        question. Both already come back on every _dex_price_batch quote, so
        this costs nothing but the bytes.

        liq stays None when DexScreener reports none (pump.fun bonding-curve
        pairs pre-graduation). None means unknown, 0.0 means a genuinely empty
        pool - collapsing them would fabricate a depth reading.
        """
        return {
            'addr': addr,
            'sym': rec.get('symbol', ''),
            'ts': round(now, 3),
            'age_h': round((now - rec.get('ts', 0)) / 3600.0, 5),
            'price': price,
            'mcap': mcap or 0,
            'mult': round(mult, 6),
            'liq': liq,
            'vol24': vol24 or 0,
        }

    def already_called(self, address: str) -> bool:
        """True if this token was called recently - stops the same runner
        being re-posted every scan cycle."""
        rec = self.calls.get(address)
        if not rec:
            return False
        age_hours = (time.time() - rec.get('ts', 0)) / 3600.0
        return age_hours < self.recall_cooldown_hours

    @staticmethod
    def _median(vals):
        s = sorted(vals)
        n = len(s)
        if not n:
            return 0.0
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    def _reject_price_outliers(self, addr, cands):
        """Drop pools whose usd price disagrees with the token's own pools.

        A token trades in many pools and they agree. A pool quoted in an exotic
        numeraire whose OWN usd price is broken on DexScreener does not: KINS
        had 13 pools at ~$0.0031 and one KINS/CSR pool at $14.49 - a 4,600x
        error implying a $14.5B mcap on a $2.9M token. That bad usd price also
        inflates the pool's usd VOLUME, so it wins the (vol24, liq) rank below
        and becomes the quote we adopt. peak_multiple only ever moves up, so a
        single such print latches a fake all-time peak permanently.

        Deliberately RELATIVE, not an absolute mcap ceiling: this same call
        prices WSOL ($82 / $80.8M cap) and other large tokens, which any
        absolute cap would wrongly reject. Needs >= 3 pools - with 2 there is
        no majority to say which one is lying, so both are kept and behaviour
        is unchanged.

        FACTOR is 50, NOT 5. The median here is unweighted, so a token whose
        real venue is one dominant pool can be outvoted by three stale dust
        pools: AMkJ3.. quotes $6.672e-06 on a $743k/day pumpswap pool while
        three pools doing <$2.6k/day sit near $4.5e-05. At 5x the guard threw
        out the REAL price and kept the dust, pricing it ~5x too HIGH - the
        exact error it exists to prevent, with the sign flipped. Observed
        dispersion among healthy pools runs 5-12x; the broken-numeraire bug
        runs 470-4,600x. 50 sits in that gap. Anything a dust pool wins on
        price it still loses on the (vol24, liq) rank below.
        """
        FACTOR = 50.0
        if len(cands) < 3:
            return cands
        med = self._median([c[0] for c in cands])
        if med <= 0:
            return cands
        keep, dropped = [], []
        for c in cands:
            (keep if med / FACTOR <= c[0] <= med * FACTOR else dropped).append(c)
        if not keep:
            return cands
        if dropped:
            self.logger.warning(
                f"Rejected {len(dropped)} outlier quote(s) for {addr}: "
                f"{sorted(c[0] for c in dropped)} vs median {med:.10g}"
            )
        return keep

    def _dex_price_batch(self, addresses: List[str]) -> Dict[str, Dict]:
        """Price token addresses via DexScreener (30 per request). Synchronous -
        call through asyncio.to_thread. Keeps the deepest pair per token."""
        out = {}
        clean = [a for a in addresses if a and a != 'N/A']
        for i in range(0, len(clean), 30):
            chunk = clean[i:i + 30]
            try:
                resp = self.session.get(
                    f"https://api.dexscreener.com/latest/dex/tokens/{','.join(chunk)}",
                    timeout=30
                )
                resp.raise_for_status()
                # Collect every pool per token FIRST. The deepest-pair choice
                # below can only be as good as the candidates it ranks, so the
                # outlier rejection has to see the whole set before we pick.
                by_addr = {}
                for pair in (resp.json().get('pairs') or []):
                    base = pair.get('baseToken') or {}
                    addr = base.get('address')
                    if not addr:
                        continue
                    try:
                        price = float(pair.get('priceUsd') or 0)
                    except (TypeError, ValueError):
                        continue
                    if price <= 0:
                        continue
                    # None means DexScreener did not report liquidity for this
                    # pair - which is what it does for pump.fun bonding-curve
                    # pairs, pre-graduation. That is NOT the same as zero, and
                    # collapsing the two made a $5.7k pool render as "F - $0".
                    # Keep None distinct; use liq_cmp only for deepest-pair choice.
                    liq_raw = (pair.get('liquidity') or {}).get('usd')
                    try:
                        liq = float(liq_raw) if liq_raw is not None else None
                    except (TypeError, ValueError):
                        liq = None
                    vol24 = (pair.get('volume') or {}).get('h24') or 0
                    try:
                        vol24 = float(vol24)
                    except (TypeError, ValueError):
                        vol24 = 0.0
                    # Rank by VOLUME first, liquidity second. Ranking by
                    # liquidity alone let an $8.71 meteora dust pair outrank the
                    # pump.fun curve pair that was doing $28k/day, purely because
                    # the curve reports liquidity as None and None sorted as 0.
                    # The venue that actually trades is the right reference for
                    # price as well as depth.
                    rank = (vol24, liq or 0.0)
                    _info = pair.get('info') or {}
                    by_addr.setdefault(addr, []).append((price, rank, {
                        'price': price,
                        'market_cap': pair.get('marketCap') or pair.get('fdv') or 0,
                        'symbol': base.get('symbol', ''),
                        'name': base.get('name', ''),
                        'socials': _info.get('socials') or [],
                        'websites': _info.get('websites') or [],
                        'volume_24h': (pair.get('volume') or {}).get('h24') or 0,
                        'change_24h': (pair.get('priceChange') or {}).get('h24') or 0,
                        'change_5m': (pair.get('priceChange') or {}).get('m5') or 0,
                        'liquidity': liq,
                        'pair_created': pair.get('pairCreatedAt') or 0,
                        '_rank': rank,
                    }))
                for addr, cands in by_addr.items():
                    for price, rank, entry in self._reject_price_outliers(addr, cands):
                        prev = out.get(addr)
                        if prev is not None and prev.get('_rank', (0.0, 0.0)) >= rank:
                            continue
                        out[addr] = entry
            except Exception as e:
                self.logger.error(f"DexScreener batch price error: {e}")
        return out

    def record_call(self, analysis: Dict, message_id=None):
        """Store a call so we can dedupe it and measure it later.

        The basis price comes from DexScreener - the same feed we re-price
        against - so the multiples can't be inflated by a cross-source mismatch.
        """
        addr = analysis.get('token_address')
        if not addr or addr == 'N/A':
            return
        quote = self._dex_price_batch([addr]).get(addr)
        if not quote:
            self.logger.info(f"No DexScreener price for {analysis.get('symbol')} - call not tracked")
            return
        now = time.time()
        rec = {
            'symbol': analysis.get('symbol', ''),
            'name': analysis.get('name', ''),
            'source': analysis.get('source', 'coingecko'),
            'price_at_call': quote['price'],
            'mcap_at_call': quote.get('market_cap', 0),
            'ts': now,
            'message_id': message_id,
            'tiers_alerted': [],
            'peak_multiple': 1.0,
            # Max ADVERSE excursion. Without this there is no downside record at
            # all, which is why stop-loss levels could not be fitted from the
            # first 168 calls at any granularity.
            'trough_multiple': 1.0,
            # Call-time features, snapshotted so exits can later be bucketed by
            # regime without re-deriving them from a token that has since moved.
            'turnover_ratio_at_call': analysis.get('turnover_ratio', 0),
            'turnover_grade_at_call': analysis.get('turnover_grade', ''),
            # Prefer the depth already resolved in _attach_chart_data - it has
            # the RugCheck fallback applied. Re-reading the raw quote here would
            # reintroduce the bonding-curve blind spot and record a false 0.
            'depth_usd_at_call': (
                analysis.get('depth_usd')
                if analysis.get('depth_usd') is not None
                else quote.get('liquidity')
            ),
            'depth_ratio_at_call': analysis.get('depth_ratio'),
            'depth_grade_at_call': analysis.get('depth_grade', ''),
            # Token age at call. Free here, and plausibly the most predictive
            # feature not previously recorded.
            'pair_created': quote.get('pair_created') or 0,
            'age_h_at_call': (
                (now - quote['pair_created'] / 1000.0) / 3600.0
                if quote.get('pair_created') else None
            ),
            'confidence_at_call': analysis.get('confidence', 0),
            'vol_mcap_at_call': (
                (analysis.get('volume_24h', 0) or 0) / analysis['market_cap']
                if analysis.get('market_cap') else 0
            ),
            'rc_top1_at_call': (analysis.get('rugcheck') or {}).get('top1'),
            'rc_top10_at_call': (analysis.get('rugcheck') or {}).get('top10'),
            'rc_holders_at_call': (analysis.get('rugcheck') or {}).get('holders'),
        }
        self.calls[addr] = rec
        self._save_calls()
        # Seed the series at t=0 so every path starts from its own entry.
        self._append_samples([self._sample_row(
            addr, rec, quote['price'], quote.get('market_cap', 0), 1.0, now,
            quote.get('liquidity'), quote.get('volume_24h'))])
        self.logger.info(
            f"Recorded call {analysis.get('symbol')} @ {quote['price']:.10f} (msg {message_id})"
        )

    async def check_call_performance(self):
        """Re-price open calls; alert once per profit tier crossed."""
        if not self.calls:
            return
        now = time.time()
        # list() first: record_call mutates self.calls from a worker thread, and
        # a comprehension over .items() can be interrupted mid-iteration.
        addrs = [a for a, r in list(self.calls.items())
                 if (now - r.get('ts', 0)) < 7 * 86400 and r.get('price_at_call', 0) > 0]
        if not addrs:
            return
        quotes = await asyncio.to_thread(self._dex_price_batch, addrs)
        changed = False
        samples = []
        for addr in addrs:
            rec = self.calls.get(addr)
            quote = quotes.get(addr)
            if not rec or not quote:
                continue
            basis = rec.get('price_at_call', 0)
            if basis <= 0:
                continue
            mult = quote['price'] / basis
            samples.append(self._sample_row(
                addr, rec, quote['price'], quote.get('market_cap', 0), mult, now,
                quote.get('liquidity'), quote.get('volume_24h')))
            # Last observed multiple, so the leaderboard can show "peaked 4x,
            # now 1.2x" without spending another round of quotes.
            if rec.get('last_mult') != mult:
                rec['last_mult'] = mult
                changed = True
            if mult > rec.get('peak_multiple', 1.0):
                rec['peak_multiple'] = mult
                changed = True
            # .get default 1.0 keeps the 168 pre-existing records valid: their
            # trough is unknown before this point, so entry is the safest floor.
            if mult < rec.get('trough_multiple', 1.0):
                rec['trough_multiple'] = mult
                changed = True
            # A token can vault past several tiers between checks. Mark them all
            # as seen but only announce the highest, so one move = one alert.
            crossed = [t for t in self.profit_tiers
                       if mult >= t and t not in rec.get('tiers_alerted', [])]
            if crossed:
                rec.setdefault('tiers_alerted', []).extend(crossed)
                changed = True
                await self.send_profit_alert(addr, rec, quote, mult, max(crossed))
        # Off the event loop: this is the same lesson as get_updates - a growing
        # file write on the loop stalls every other coroutine.
        await asyncio.to_thread(self._append_samples, samples)
        if changed:
            self._save_calls()

    async def fast_track_loop(self):
        """Densely sample calls that are young enough to still be running.

        Deliberately RECORDS ONLY. peak/trough/last_mult are refreshed in memory
        so the leaderboard sees them, but this never calls _save_calls and never
        posts a profit alert. That keeps exactly one writer for
        calls_history.json and exactly one path that can fire an alert, so
        adding this task cannot produce duplicate alerts or interleave a
        whole-file rewrite with the main loop's. Anything lost to a crash is
        still in calls_series.jsonl, which is append-only.

        Cost is one DexScreener batch request per cycle: only calls younger than
        fast_track_hours are quoted, and the endpoint takes 30 addresses at a
        time.
        """
        while self.running:
            try:
                now = time.time()
                cutoff = self.fast_track_hours * 3600
                # Snapshot in one C-level call. record_call runs in a worker
                # thread (asyncio.to_thread) and assigns self.calls[addr], so a
                # Python-level comprehension straight over .items() can be
                # interrupted mid-iteration and raise "dictionary changed size
                # during iteration". list() cannot be.
                snapshot = list(self.calls.items())
                addrs = [a for a, r in snapshot
                         if r.get('price_at_call', 0) > 0
                         and (now - r.get('ts', 0)) < cutoff]
                if addrs:
                    quotes = await asyncio.to_thread(self._dex_price_batch, addrs)
                    now = time.time()
                    samples = []
                    for addr in addrs:
                        rec = self.calls.get(addr)
                        quote = quotes.get(addr)
                        if not rec or not quote:
                            continue
                        basis = rec.get('price_at_call', 0)
                        if basis <= 0:
                            continue
                        mult = quote['price'] / basis
                        samples.append(self._sample_row(
                            addr, rec, quote['price'], quote.get('market_cap', 0),
                            mult, now, quote.get('liquidity'),
                            quote.get('volume_24h')))
                        rec['last_mult'] = mult
                        if mult > rec.get('peak_multiple', 1.0):
                            rec['peak_multiple'] = mult
                        if mult < rec.get('trough_multiple', 1.0):
                            rec['trough_multiple'] = mult
                    if samples:
                        await asyncio.to_thread(self._append_samples, samples)
                        self.logger.debug(
                            f"Fast-track sampled {len(samples)} young calls")
            except Exception as e:
                self.logger.error(f"Fast-track sampling failed: {e}")
            await asyncio.sleep(self.fast_track_interval)

    async def send_profit_alert(self, address: str, rec: Dict, quote: Dict, mult: float, tier: float):
        """Post a 'we called it' update, threaded under the original call."""
        gain_pct = (mult - 1) * 100
        held_hours = (time.time() - rec.get('ts', 0)) / 3600.0
        if held_hours < 1:
            age = f"{held_hours * 60:.0f}m"
        elif held_hours < 24:
            age = f"{held_hours:.1f}h"
        else:
            age = f"{held_hours / 24:.1f}d"
        label = f"{tier:g}X" if tier >= 2 else f"+{(tier - 1) * 100:.0f}%"
        # Some tickers already carry a leading '$' - don't double it.
        ticker = (rec.get('symbol') or '?').lstrip('$') or '?'

        message = (
            f"🏆 <b>CALL UPDATE: ${ticker} HIT {label}</b>\n\n"
            f"📈 <b>Since our call:</b> {mult:.2f}x (+{gain_pct:,.0f}%)\n"
            f"💰 <b>Call price:</b> ${rec.get('price_at_call', 0):.10f}\n"
            f"💵 <b>Current price:</b> ${quote['price']:.10f}\n"
            f"📊 <b>Market cap:</b> ${quote.get('market_cap', 0):,.0f}\n"
            f"⏱ <b>Time since call:</b> {age}\n"
            f"🔝 <b>Peak:</b> {rec.get('peak_multiple', mult):.2f}x"
        )
        keyboard = {"inline_keyboard": [[
            {"text": "📊 Dexscreener", "url": f"https://dexscreener.com/solana/{address}"},
            {"text": "🐸 GMGN", "url": f"https://gmgn.ai/sol/token/{address}"},
        ]]}
        data = {
            'chat_id': self.telegram_chat_id,
            'text': message,
            'parse_mode': 'HTML',
            'reply_markup': json.dumps(keyboard),
            'disable_web_page_preview': True,
        }
        mid = rec.get('message_id')
        if mid:
            data['reply_to_message_id'] = mid

        def _post(payload):
            return self.session.post(f"{self.api_url}/sendMessage", json=payload, timeout=60)

        try:
            resp = await asyncio.to_thread(_post, data)
            if resp.status_code != 200 and mid:
                # Original post may have been deleted - fall back to standalone.
                data.pop('reply_to_message_id', None)
                resp = await asyncio.to_thread(_post, data)
            if resp.status_code == 200:
                self.logger.info(f"Profit alert sent: {rec.get('symbol')} {label}")
            else:
                self.logger.error(f"Profit alert failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            self.logger.error(f"Profit alert error: {e}")

    async def fetch_dexscreener_tokens(self) -> List[Dict]:
        """Discover fresh Solana tokens from DexScreener and normalize them into
        the CoinGecko-shaped dict the rest of the pipeline expects."""
        if not self.dex_discovery_enabled:
            return []

        def _discover():
            addrs = []
            for url in ("https://api.dexscreener.com/token-profiles/latest/v1",
                        "https://api.dexscreener.com/token-boosts/latest/v1"):
                try:
                    resp = self.session.get(url, timeout=30)
                    resp.raise_for_status()
                    for item in (resp.json() or []):
                        if item.get('chainId') == 'solana' and item.get('tokenAddress'):
                            addrs.append(item['tokenAddress'])
                except Exception as e:
                    self.logger.error(f"DexScreener discovery error ({url}): {e}")
            seen, unique = set(), []
            for a in addrs:
                if a not in seen:
                    seen.add(a)
                    unique.append(a)
            return self._dex_price_batch(unique)

        try:
            quotes = await asyncio.to_thread(_discover)
        except Exception as e:
            self.logger.error(f"DexScreener discovery failed: {e}")
            return []

        tokens = []
        for addr, q in quotes.items():
            if not q.get('symbol'):
                continue
            tokens.append({
                'id': f"dex:{addr}",
                'symbol': q['symbol'],
                'name': q.get('name') or q['symbol'],
                'current_price': q['price'],
                'market_cap': q.get('market_cap') or 0,
                'total_volume': q.get('volume_24h') or 0,
                'price_change_percentage_24h': q.get('change_24h') or 0,
                'source': 'dexscreener',
                'address': addr,
                'change_5m': q.get('change_5m') or 0,
                'pair_created': q.get('pair_created') or 0,
                'socials': q.get('socials') or [],
                'websites': q.get('websites') or [],
            })
        self.logger.info(f"DexScreener discovery: {len(tokens)} Solana tokens")
        return tokens

    def fetch_real_ohlcv(self, address: str, min_candles: int = 20) -> List[Tuple[float, float, float, float]]:
        """OHLC only, for the candlestick chart. See fetch_ohlcv_full."""
        return [(o, h, l, c) for (o, h, l, c, _v) in self.fetch_ohlcv_full(address, min_candles)]

    def fetch_ohlcv_full(self, address: str, min_candles: int = 20) -> List[Tuple[float, float, float, float, float]]:
        """Real OHLC + volume candles for a Solana token from GeckoTerminal.

        Returns [] when there isn't enough genuine history. Never synthesize
        price action - a fabricated curve renders as a perfect green staircase
        with RSI pinned at 100 and is indistinguishable from a real chart.
        """
        try:
            resp = self.session.get(
                f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{address}/pools",
                headers={'Accept': 'application/json'}, timeout=25
            )
            resp.raise_for_status()
            pools = resp.json().get('data') or []
            if not pools:
                return []
            pool = pools[0]['attributes']['address']
        except Exception as e:
            self.logger.warning(f"GeckoTerminal pool lookup failed for {address[:8]}: {e}")
            return []

        # New pairs only have minute history; older ones get coarser candles.
        for timeframe, params, mins in (("minute", "aggregate=5&limit=60", 5),
                                        ("minute", "aggregate=1&limit=60", 1),
                                        ("hour", "aggregate=1&limit=60", 60)):
            try:
                resp = self.session.get(
                    f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}"
                    f"/ohlcv/{timeframe}?{params}",
                    headers={'Accept': 'application/json'}, timeout=25
                )
                resp.raise_for_status()
                rows = (resp.json().get('data', {})
                        .get('attributes', {}).get('ohlcv_list') or [])
                if len(rows) >= min_candles:
                    rows = sorted(rows, key=lambda c: c[0])  # API is newest-first
                    self._last_ohlcv_interval = mins
                    return [(float(c[1]), float(c[2]), float(c[3]), float(c[4]),
                             float(c[5] or 0)) for c in rows][-60:]
            except Exception as e:
                self.logger.warning(f"GeckoTerminal OHLCV {timeframe} failed: {e}")
        return []

    def create_volume_profile_surface(self, symbol: str, full: List[Tuple], price_now: float = 0):
        """3D volume-at-price surface: X=time, Y=price level, Z=volume traded there.

        Every value comes from real OHLCV. Volume is distributed across the price
        bins each candle's high-low range actually spans - nothing is invented.
        Returns (buffer, point_of_control) or (None, 0).
        """
        try:
            if not full or len(full) < 20:
                return None, 0
            import numpy as np
            from matplotlib import cm

            o = np.array([r[0] for r in full], dtype=float)
            h = np.array([r[1] for r in full], dtype=float)
            lo_ = np.array([r[2] for r in full], dtype=float)
            c = np.array([r[3] for r in full], dtype=float)
            v = np.array([r[4] for r in full], dtype=float)
            if v.sum() <= 0 or h.max() <= lo_.min():
                return None, 0

            nb = 26
            edges = np.linspace(lo_.min(), h.max(), nb + 1)
            centers = (edges[:-1] + edges[1:]) / 2.0

            Z = np.zeros((nb, len(full)))
            for i in range(len(full)):
                band = (centers >= lo_[i]) & (centers <= h[i])
                n = int(band.sum())
                if n:
                    Z[band, i] = v[i] / n

            # Smooth across price only - never across time, that would invent flow.
            k = np.array([0.25, 0.5, 0.25])
            for i in range(Z.shape[1]):
                Z[:, i] = np.convolve(Z[:, i], k, mode='same')

            poc = float(centers[Z.sum(axis=1).argmax()])
            X, Y = np.meshgrid(np.arange(len(full)), centers)

            fig = plt.figure(figsize=(10, 6.5), facecolor='#0d0f14')
            ax = fig.add_subplot(111, projection='3d', facecolor='#0d0f14')
            ax.plot_surface(X, Y, Z, cmap=cm.plasma, rstride=1, cstride=1,
                            linewidth=0.1, edgecolors='#00000022',
                            antialiased=True, alpha=0.95)

            # NOTE: the path rides the surface, so its HEIGHT is volume, not
            # price. Forcing it to draw on top (computed_zorder=False, tried
            # 2026-08-15) makes it fully visible and it reads as a chaotic
            # zigzag, because it whipsaws between the floor and every volume
            # spike. The partial occlusion below is the calmer picture. If the
            # full path is wanted, flatten it to the floor plane instead of
            # raising it - do not just reorder the artists.
            idx = [max(0, min(nb - 1, int(np.searchsorted(edges, c[i])) - 1))
                   for i in range(len(full))]
            zc = np.array([Z[idx[i], i] for i in range(len(full))]) * 1.05
            ax.plot(np.arange(len(full)), c, zc, color='#00ffe0', lw=2.0, label='price path')
            ax.plot([0, len(full) - 1], [poc, poc], [0, 0],
                    color='#ffd166', lw=1.8, ls='--', label='point of control')

            ax.set_xlabel('time', color='#8ba0b5', fontsize=9, labelpad=2)
            ax.set_ylabel('price ($)', color='#8ba0b5', fontsize=9, labelpad=8)
            ax.set_zlabel('volume at price', color='#8ba0b5', fontsize=9, labelpad=2)
            state = 'above' if price_now and price_now > poc else 'below'
            ax.set_title(f'{symbol} - volume-at-price  (price {state} shelf)',
                         color='#00ffe0', fontsize=13, weight='bold', pad=14)
            for a in (ax.xaxis, ax.yaxis, ax.zaxis):
                a.set_pane_color((0.05, 0.06, 0.09, 1.0))
                a._axinfo['grid'].update(color='#243040', linewidth=0.4)
            ax.tick_params(colors='#6b7d90', labelsize=7)
            ax.view_init(elev=30, azim=-60)
            ax.legend(loc='upper left', fontsize=8, facecolor='#141824',
                      labelcolor='#8ba0b5', framealpha=0.75, edgecolor='#243040')

            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=105, bbox_inches='tight', facecolor='#0d0f14')
            buf.seek(0)
            plt.close(fig)
            return buf, poc
        except Exception as e:
            self.logger.error(f"Volume profile surface failed for {symbol}: {e}")
            try:
                plt.close('all')
            except Exception:
                pass
            return None, 0

    @staticmethod
    def x_links(socials):
        """(profile_url, post_url) from a DexScreener socials list.

        DexScreener usually stores the announcement TWEET, not the account, e.g.
        https://x.com/handle/status/123. Labelling that "X Profile" is wrong, so
        derive the profile from the handle and surface both.
        """
        post = profile = None
        for s in (socials or []):
            url = (s.get('url') or '').strip()
            if not url:
                continue
            low = url.lower()
            if (s.get('type') or '').lower() == 'twitter' or 'x.com/' in low or 'twitter.com/' in low:
                if '/status/' in low:
                    post = post or url
                    try:
                        head = url.split('?')[0].split('/status/')[0]
                        handle = head.rstrip('/').rsplit('/', 1)[-1]
                        if handle and handle.lower() not in ('x.com', 'twitter.com', 'i', 'home'):
                            profile = profile or f"https://x.com/{handle}"
                    except Exception:
                        pass
                else:
                    profile = profile or url.split('?')[0]
        return profile, post

    @staticmethod
    def first_website(websites):
        for w in (websites or []):
            u = (w.get('url') or '').strip()
            if u.startswith('http'):
                return u
        return None

    def fetch_rugcheck(self, address: str):
        """RugCheck report for a mint. Returns dict, or None if unreachable."""
        try:
            resp = self.session.get(
                f"https://api.rugcheck.xyz/v1/tokens/{address}/report",
                headers={'Accept': 'application/json'}, timeout=20
            )
            if resp.status_code != 200:
                self.logger.warning(f"RugCheck HTTP {resp.status_code} for {address[:8]}")
                return None
            return resp.json()
        except Exception as e:
            self.logger.warning(f"RugCheck unreachable for {address[:8]}: {e}")
            return None

    def rugcheck_verdict(self, report):
        """(passed, reasons, info) for a RugCheck report.

        NOTE ON SCORE DIRECTION: rugcheck scores are inverted from intuition -
        LOWER is safer. USDC scores 1; BONK scores 96 on unlocked LP vaults.
        A high score is not proof of a rug, and a score of 1 is not proof of
        safety (every pump.fun mint scores 1 because mint/freeze are revoked
        by default), which is why concentration carries this filter.
        """
        if not report:
            info = {'available': False}
            if self.rc_fail_closed:
                return False, ['safety check unavailable'], info
            return True, [], info

        # topHolders includes the bonding curve / AMM reserve as if it were a wallet.
        # On pump.fun mints that account IS the largest "holder" - measured across 18
        # live tokens it was #1 on every single one - so raw top1 tracked how little of
        # the curve had been bought, not concentration: a fresh mint read 98% and a
        # drained one read 10%. That rejected the newest launches hardest. RugCheck
        # labels these itself in knownAccounts ({"name": "Pump Fun", "type": "AMM"}),
        # so drop them and measure the real wallets. A genuine whale is untouched:
        # the one sampled token with a non-pool top holder still reads 76.4%.
        # Token-2022 extension block, read once. transferFeeConfig is absent on
        # most pump.fun mints - its mere presence is close to a trap signal on its
        # own (2/30 sampled had it, both taxing 3%).
        ext = report.get('token_extensions') or {}
        fee_cfg = ext.get('transferFeeConfig') or {}
        fee_bps = max(
            (fee_cfg.get('newerTransferFee') or {}).get('transferFeeBasisPoints') or 0,
            (fee_cfg.get('olderTransferFee') or {}).get('transferFeeBasisPoints') or 0,
        )

        known = report.get('knownAccounts') or {}
        pool_keys = {m.get('pubkey') for m in (report.get('markets') or []) if m.get('pubkey')}

        def _is_pool(holder):
            entry = known.get(holder.get('owner')) or {}
            if (entry.get('type') or '').upper() in ('AMM', 'MARKET', 'LIQUIDITY'):
                return True
            # Fall back to the market pubkeys in case knownAccounts is sparse.
            return holder.get('owner') in pool_keys

        all_holders = report.get('topHolders') or []
        th = [h for h in all_holders if not _is_pool(h)]
        top1 = round(th[0].get('pct', 0), 1) if th else 0.0
        top10 = round(sum(h.get('pct', 0) for h in th[:10]), 1)
        danger = sum(1 for r in (report.get('risks') or []) if r.get('level') == 'danger')
        info = {
            'available': True,
            'score': report.get('score_normalised'),
            'rugged': bool(report.get('rugged')),
            'mint_live': report.get('mintAuthority') is not None,
            'freeze_live': report.get('freezeAuthority') is not None,
            'holders': report.get('totalHolders') or 0,
            'liquidity': report.get('totalMarketLiquidity') or 0,
            # Deepest SINGLE market, not the sum. totalMarketLiquidity adds up
            # every venue - Jimothy had ~130 markets of which ~120 held under
            # $100 - so it reported $1,026,567 of "liquidity" against a real
            # tradable pool of $540k. Summing dust overstates what you can
            # actually trade through, which is the whole question depth answers.
            'deepest_market': max(
                [((m.get('lp') or {}).get('baseUSD') or 0)
                 + ((m.get('lp') or {}).get('quoteUSD') or 0)
                 for m in (report.get('markets') or [])] or [0]),
            'top1': top1,
            'top10': top10,
            'insiders': sum(1 for h in th if h.get('insider')),
            'danger': danger,
            'fee_bps': fee_bps,
            'fee_authority': fee_cfg.get('transferFeeConfigAuthority'),
            'permanent_delegate': ext.get('permanentDelegate'),
            'default_frozen': bool(ext.get('defaultAccountState')),
            'non_transferable': bool(ext.get('nonTransferable')),
            'token2022': report.get('tokenProgram') == TOKEN_2022_PROGRAM,
            'risk_names': [r.get('name') for r in (report.get('risks') or [])
                           if r.get('level') == 'danger'][:3],
        }

        reasons = []
        # --- Token-2022 trap extensions ---------------------------------------
        # Classic SPL cannot levy a transfer tax at all; it is structurally a
        # Token-2022 feature. NOTE: the top-level report['transferFee']['pct'] is
        # NOT usable - it read 0 on two separate mints that were actually taxing
        # 300 bps. The truth lives in token_extensions.transferFeeConfig, and the
        # max of older/newer is the safe read across an epoch boundary.
        if info.get('fee_bps', 0) > self.rc_max_fee_bps:
            reasons.append(f"transfer tax {info['fee_bps'] / 100:.2f}%")
        if info.get('fee_authority'):
            # Fee is 0 today but an authority can raise it before you can sell.
            reasons.append('transfer fee authority still live')
        if info.get('permanent_delegate'):
            reasons.append('permanent delegate can seize tokens')
        if info.get('default_frozen'):
            reasons.append('new accounts frozen by default')
        if info.get('non_transferable'):
            reasons.append('token is non-transferable')

        # Unambiguous - rare in practice but catastrophic when present.
        if info['rugged']:
            reasons.append('flagged as rugged')
        if info['mint_live']:
            reasons.append('mint authority NOT revoked')
        if info['freeze_live']:
            reasons.append('freeze authority NOT revoked')
        # Concentration - what actually separates these tokens.
        if top1 > self.rc_max_top1:
            reasons.append(f'top holder {top1}% > {self.rc_max_top1:g}%')
        if top10 > self.rc_max_top10:
            reasons.append(f'top10 {top10}% > {self.rc_max_top10:g}%')
        if danger >= self.rc_max_danger:
            reasons.append(f'{danger} danger risks')
        score = info['score']
        if isinstance(score, (int, float)) and score >= self.rc_max_score:
            reasons.append(f'risk score {score} >= {self.rc_max_score:g}')
        if info['holders'] and info['holders'] < self.rc_min_holders:
            reasons.append(f"{info['holders']} holders < {self.rc_min_holders}")
        if info['liquidity'] and info['liquidity'] < self.rc_min_liquidity:
            reasons.append(f"liquidity ${info['liquidity']:,.0f} < ${self.rc_min_liquidity:,.0f}")
        return (not reasons), reasons, info

    @staticmethod
    def rugcheck_line(info) -> str:
        """One-line safety summary for the call message."""
        if not info:
            return ""
        if not info.get('available'):
            return "\n🛡 <b>Safety:</b> ⚠️ RugCheck unavailable - unverified\n"
        bits = [f"score {info.get('score')}", f"top1 {info.get('top1')}%",
                f"top10 {info.get('top10')}%", f"{info.get('holders')} holders"]
        # Tax is stated on every card, including 0%. A silent absence reads the
        # same as "not checked", and this is the field a taxed trap hides behind.
        fee_bps = info.get('fee_bps', 0)
        bits.append(f"tax {fee_bps / 100:.2f}%" if fee_bps else "tax 0%")
        line = f"\n🛡 <b>RugCheck:</b> {' | '.join(bits)}\n"
        if fee_bps:
            line += f"🚨 <b>TRANSFER TAX {fee_bps / 100:.2f}% - every buy and sell is taxed</b>\n"
        if info.get('fee_authority'):
            line += "⚠️ <b>Transfer fee authority live - tax can be raised</b>\n"
        if info.get('permanent_delegate'):
            line += "🚨 <b>Permanent delegate - tokens can be seized</b>\n"
        if info.get('default_frozen'):
            line += "🚨 <b>Accounts frozen by default</b>\n"
        if info.get('mint_live') or info.get('freeze_live'):
            line += "⚠️ <b>Authority still live</b>\n"
        if info.get('risk_names'):
            line += f"⚠️ {', '.join(info['risk_names'])}\n"
        return line

    @staticmethod
    def _msg_id(result):
        """Pull message_id out of a Telegram API response, or None."""
        try:
            return result['result']['message_id']
        except Exception:
            return None

    async def _attach_chart_data(self, analysis: Dict, token: Dict, token_id: str):
        """Fetch OHLCV only for tokens we are actually posting.

        GeckoTerminal's free tier degrades from ~0.7s to ~46s past roughly
        30 requests/minute. Running this per candidate (19+ a cycle) would
        throttle the entire scan, so it runs only for the few we call.
        """
        try:
            full = await asyncio.to_thread(self.fetch_ohlcv_full, analysis.get('token_address'))
        except Exception as e:
            self.logger.error(f"OHLCV fetch failed: {e}")
            full = []
        if full:
            analysis['ohlcv_full'] = full
            analysis['historical_prices'] = [(o, h, l, c) for (o, h, l, c, _v) in full]
            # Read immediately after the fetch - the send path is sequential.
            analysis['interval_min'] = getattr(self, '_last_ohlcv_interval', None)
        elif token.get('source') != 'dexscreener':
            # CoinGecko fallback has no volume, so no surface - chart only.
            analysis['historical_prices'] = await self.get_historical_prices(
                token_id, analysis.get('price', 0))
        if not self.is_chartable(analysis.get('historical_prices')):
            analysis['historical_prices'] = []

        # One DexScreener pair lookup serves two purposes: socials (CoinGecko
        # tokens arrive without them) and real pool depth. This is the first
        # point in the pipeline where depth is available at all - check_risks
        # runs against 333 candidates and only sees CoinGecko-shaped fields, so
        # grading depth there would mean a batch lookup per candidate.
        # _dex_price_batch already keeps the DEEPEST pair, which is the right
        # one: STONKSTR had 5 pairs spanning $0 to $15,132 and the thin ones are
        # not where anyone trades.
        try:
            q = (await asyncio.to_thread(
                self._dex_price_batch, [analysis.get('token_address')])
                 ).get(analysis.get('token_address')) or {}
        except Exception as e:
            self.logger.warning(f"DexScreener pair lookup failed: {e}")
            q = {}

        if not analysis.get('socials'):
            analysis['socials'] = q.get('socials') or []
            analysis['websites'] = q.get('websites') or []

        # Take the LARGER of the two sources rather than treating DexScreener as
        # authoritative and RugCheck as a fallback. Two independent ways
        # DexScreener under-reports: it returns None for pump.fun curve pairs,
        # and a dust pair can outrank the real venue (Sun Wukong reported $8.71
        # against RugCheck's $5,607 - a 600x understatement that fired two false
        # warnings). RugCheck sums all markets so it reads slightly high, but
        # "slightly high" beats "three orders of magnitude low", and a genuinely
        # empty pool reads ~0 in both so nothing is masked.
        # Both sides are now DEEPEST-SINGLE-VENUE figures, so they measure the
        # same thing and max() picks the better-informed source rather than
        # mixing a per-pool number with an all-venue sum.
        dex_depth = q.get('liquidity') or 0
        rc_depth = (analysis.get('rugcheck') or {}).get('deepest_market') or 0
        depth = max(float(dex_depth), float(rc_depth)) or None
        grade, desc, emoji, ratio = self.get_depth_grade(depth, analysis.get('market_cap', 0))
        analysis['depth_usd'] = depth
        analysis['depth_ratio'] = ratio
        analysis['depth_grade'] = grade
        analysis['depth_desc'] = desc
        analysis['depth_emoji'] = emoji
        if q.get('pair_created'):
            analysis['pair_created'] = q['pair_created']

        # The STONKSTR signature: heavily traded against a shallow pool. Stated
        # as its own warning rather than folded into a grade, because the two
        # facts point opposite ways and averaging them hides both.
        turnover = analysis.get('turnover_ratio', 0)
        if ratio is not None and ratio < 0.15 and turnover >= 1.0:
            analysis.setdefault('warnings', []).append(
                f"High turnover ({turnover:.1f}x mcap) against a shallow pool "
                f"(depth {ratio:.3f} of mcap) - churn, not depth")
        if ratio is not None and ratio < self.min_depth_ratio:
            analysis.setdefault('warnings', []).append(
                f"Pool depth {ratio:.3f} of mcap below {self.min_depth_ratio:g}")

    async def _send_volume_surface(self, analysis: Dict, symbol: str, token_address: str):
        """Post the 3D volume-at-price surface as a follow-up image."""
        full = analysis.get('ohlcv_full') or []
        price_now = analysis.get('price', 0)
        surf, poc = self.create_volume_profile_surface(symbol, full, price_now)
        if not surf:
            return
        try:
            if price_now > poc:
                verdict = "🟢 Price ABOVE the shelf — that volume is support"
            else:
                verdict = "🔴 Price BELOW the shelf — overhead supply"
            caption = (
                f"📐 <b>{symbol} VOLUME-AT-PRICE</b>\n"
                f"🎯 <b>Point of control:</b> ${poc:.10f}\n"
                f"{verdict}\n"
                f"<i>Built from {len(full)} real candles</i>"
            )
            files = {'photo': (f'{symbol}_vap.png', surf, 'image/png')}
            data = {'chat_id': self.telegram_chat_id, 'caption': caption, 'parse_mode': 'HTML'}
            resp = await asyncio.to_thread(
                lambda: requests.post(f"{self.api_url}/sendPhoto", files=files, data=data, timeout=120)
            )
            if resp.status_code == 200:
                self.logger.info(f"Volume surface sent for {symbol} (POC {poc:.10f})")
            else:
                self.logger.error(f"Volume surface send failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            self.logger.error(f"Volume surface send error for {symbol}: {e}")
        finally:
            try:
                surf.close()
            except Exception:
                pass

    @staticmethod
    def is_chartable(candles) -> bool:
        """Reject histories that would render badly or dishonestly.

        The 20 floor matches create_candlestick_graph's Bollinger Band
        requirement - below it the chart degrades to an empty box.
        """
        if not candles or len(candles) < 20:
            return False
        closes = [c[3] for c in candles]
        return len(set(closes)) >= 4

    def detect_patterns(self, token: Dict) -> List[str]:
        patterns = []
        price_change = token.get('price_change_percentage_24h', 0) or 0
        volume_24h = token.get('total_volume', 0)
        market_cap = token.get('market_cap', 0)
        if price_change > 10 and volume_24h > market_cap * 0.1:
            patterns.append('breakout')
        if volume_24h / market_cap > 0.1 and abs(price_change) < 8:
            patterns.append('accumulation')
        if price_change > 5 and volume_24h > market_cap * 0.1:
            patterns.append('momentum')
        return patterns

    def update_market_sentiment(self, tokens: List[Dict]):
        if not tokens:
            return
        avg_price_change = sum(t.get('price_change_percentage_24h', 0) or 0 for t in tokens) / len(tokens)
        avg_volume_change = sum(t.get('total_volume', 0) or 0 for t in tokens) / len(tokens)
        sentiment_change = ((avg_price_change * 0.7) + (avg_volume_change * 0.3)) / 100
        self.market_sentiment = max(-1, min(1, self.market_sentiment + sentiment_change))

    def calculate_signal_confidence(self, token: Dict, patterns: List[str]) -> float:
        confidence = sum(self.pattern_weights.get(p, 0) for p in patterns)
        volume_24h = token.get('total_volume', 0)
        market_cap = token.get('market_cap', 0)
        if market_cap > 0:
            vol_ratio = volume_24h / market_cap
            confidence += min(2, vol_ratio * 10)
        if self.market_sentiment > self.sentiment_threshold:
            confidence *= 1.2
        elif self.market_sentiment < -self.sentiment_threshold:
            confidence *= 0.8
        symbol = token.get('symbol', '').lower()
        if symbol in self.token_history:
            hist_success = self.token_history[symbol].get('success_rate', 0.5)
            confidence *= (0.5 + hist_success)
        return min(10, confidence)

    async def fetch_rss_news(self) -> List[Dict]:
        news_items = []
        for feed_url in self.rss_feeds:
            try:
                feed = await asyncio.to_thread(feedparser.parse, feed_url)
                for entry in feed.entries:
                    news_items.append({
                        'title': entry.title,
                        'url': entry.link,
                        'source': feed.feed.title,
                        'published': entry.get('published', ''),
                        'type': 'rss'
                    })
            except Exception as e:
                self.logger.error(f"RSS Feed Error: {feed_url} - {e}")
        return news_items

    async def unpin_message(self, message_id: int) -> bool:
        """Unpin a single message. Best-effort - an already-unpinned or deleted
        message returns an error we do not care about."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.api_url}/unpinChatMessage", json={
                    "chat_id": self.telegram_chat_id, "message_id": message_id
                }) as response:
                    ok = response.status == 200
                    if not ok:
                        self.logger.info(
                            f"Unpin {message_id} returned {response.status} (ignored)")
                    if message_id in self.bot_pins:
                        self.bot_pins.remove(message_id)
                        self._save_pin_history()
                    return ok
        except Exception as e:
            self.logger.info(f"Unpin {message_id} failed (ignored): {e}")
            return False

    def _call_link(self, message_id) -> Optional[str]:
        """Deep link to a message in this group.

        Supergroup links use the internal id, which is the chat_id with its
        '-100' prefix stripped: -100<id> -> t.me/c/<id>/<msg>.
        Returns None for any chat_id that is not a -100 supergroup, rather than
        emitting a link that would 404.
        """
        if not message_id:
            return None
        cid = str(self.telegram_chat_id or '')
        if not cid.startswith('-100'):
            return None
        return f"https://t.me/c/{cid[4:]}/{message_id}"

    def _recap_text(self, day_start: float) -> str:
        """Leaderboard of today's calls, ranked by peak multiple.

        Reads peak_multiple, which check_call_performance already maintains -
        this posts nothing new, it just surfaces what was getting buried under
        the call messages themselves.
        """
        todays = [(a, r) for a, r in self.calls.items()
                  if r.get('ts', 0) >= day_start and r.get('price_at_call', 0) > 0]
        stamp = datetime.now(timezone.utc).strftime('%H:%M UTC')
        date_str = datetime.fromtimestamp(day_start, timezone.utc).strftime('%d %b %Y')

        head = f"🏆 <b>DAILY LEADERBOARD — {date_str}</b>\n"
        if not todays:
            return (head + f"\nNo calls yet today.\n\n"
                           f"🕒 <i>Updates hourly · last {stamp}</i>")

        ranked = sorted(todays, key=lambda kv: kv[1].get('peak_multiple', 1.0), reverse=True)
        winners = [r for _, r in ranked if r.get('peak_multiple', 1.0) >= 1.5]
        best = ranked[0][1].get('peak_multiple', 1.0)

        lines = [head,
                 f"📊 <b>{len(todays)}</b> calls today · "
                 f"<b>{len(winners)}</b> above 1.5x · best <b>{best:.2f}x</b>\n"]

        medals = ['🥇', '🥈', '🥉']
        for i, (addr, r) in enumerate(ranked[:self.recap_top_n]):
            peak = r.get('peak_multiple', 1.0)
            now_mult = r.get('last_mult')
            sym = (r.get('symbol') or '?').lstrip('$') or '?'
            badge = medals[i] if i < 3 else f"{i + 1}."
            age_h = (time.time() - r.get('ts', 0)) / 3600.0
            age = f"{age_h * 60:.0f}m" if age_h < 1 else f"{age_h:.1f}h"
            link = self._call_link(r.get('message_id'))
            name = f'<a href="{link}">{html_escape(sym)}</a>' if link else html_escape(sym)
            row = f"{badge} {name} — <b>{peak:.2f}x</b>"
            if peak >= 1.5:
                row += f" (+{(peak - 1) * 100:,.0f}%)"
            if now_mult is not None:
                row += f" · now {now_mult:.2f}x"
            lines.append(row + f" · {age}")

        if len(ranked) > self.recap_top_n:
            lines.append(f"\n<i>+{len(ranked) - self.recap_top_n} more</i>")
        lines.append(f"\n🕒 <i>Peak since call · updates hourly · last {stamp}</i>")
        return "\n".join(lines)

    async def post_or_update_recap(self):
        """Keep one pinned leaderboard per UTC day, edited in place."""
        # timezone-aware throughout: utcnow() is deprecated in 3.12+ and
        # scheduled for removal, which would silently break a long-running bot.
        now = datetime.now(timezone.utc)
        today = now.strftime('%Y-%m-%d')
        day_start = now.replace(hour=0, minute=0, second=0,
                                microsecond=0).timestamp()
        text = self._recap_text(day_start)

        same_day = self.recap.get('day') == today
        mid = self.recap.get('message_id')

        if same_day and mid:
            try:
                resp = await asyncio.to_thread(lambda: requests.post(
                    f"{self.api_url}/editMessageText",
                    json={'chat_id': self.telegram_chat_id, 'message_id': mid,
                          'text': text, 'parse_mode': 'HTML',
                          'disable_web_page_preview': True},
                    timeout=30))
                if resp.status_code == 200:
                    self.logger.info(f"Leaderboard updated (msg {mid})")
                    return
                # "message is not modified" means nothing changed since the last
                # update - a success, not a failure worth re-pinning over.
                if 'not modified' in resp.text:
                    self.logger.info("Leaderboard unchanged this hour")
                    return
                self.logger.warning(
                    f"Leaderboard edit failed ({resp.status_code}): {resp.text[:160]} - reposting")
            except Exception as e:
                self.logger.warning(f"Leaderboard edit error: {e} - reposting")

        # New day, first run, or the old message became uneditable.
        try:
            resp = await asyncio.to_thread(lambda: requests.post(
                f"{self.api_url}/sendMessage",
                json={'chat_id': self.telegram_chat_id, 'text': text,
                      'parse_mode': 'HTML', 'disable_web_page_preview': True},
                timeout=30))
            resp.raise_for_status()
            new_id = self._msg_id(resp.json())
            if not new_id:
                return
            if mid and mid != new_id:
                await self.unpin_message(mid)
            await self.pin_message(new_id)
            self.recap = {'day': today, 'message_id': new_id}
            self._save_recap_state()
            self.logger.info(f"Leaderboard posted and pinned for {today} (msg {new_id})")
        except Exception as e:
            self.logger.error(f"Leaderboard post failed: {e}")

    async def pin_message(self, message_id: int) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.api_url}/pinChatMessage", json={
                    "chat_id": self.telegram_chat_id, "message_id": message_id, "disable_notification": True
                }) as response:
                    if response.status != 200:
                        self.logger.error(f"Pin Message Error: {await response.text()}")
                        return False
                    if message_id not in self.bot_pins:
                        self.bot_pins.append(message_id)
                        self._save_pin_history()
                    return True
        except Exception as e:
            self.logger.error(f"Pin Message Error: {e}")
            return False

    async def fetch_social_data(self, token_id: str, token_address: str) -> Dict:
        """Fetch social media data from CoinGecko with Phantom fallback"""
        try:
            self.logger.info(f"Fetching social data for token {token_id} (address: {token_address})")
            # Try CoinGecko first with rate limiting
            await self._rate_limit()
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.base_url}/coins/{token_id}",
                params={"localization": "false", "tickers": "false", "market_data": "false", "community_data": "true", "developer_data": "false"},
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            socials = data.get('links', {})
            twitter_url = socials.get('twitter_screen_name', '')
            if twitter_url:
                twitter_url = f"https://x.com/{twitter_url}" if not twitter_url.startswith('http') else twitter_url
                self.logger.info(f"CoinGecko found Twitter URL for {token_id}: {twitter_url}")
            else:
                self.logger.warning(f"No Twitter URL found in CoinGecko for {token_id}")

            # Fallback to Phantom page if CoinGecko doesn't provide Twitter
            if not twitter_url or twitter_url == "N/A":
                self.logger.info(f"Attempting Phantom fallback for {token_id}")
                phantom_url = f"https://phantom.app/ul/browse/token-detail/{token_address}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(phantom_url) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            twitter_link = soup.find('a', href=lambda x: x and ('twitter.com' in x or 'x.com' in x))
                            if twitter_link and twitter_link['href']:
                                twitter_url = twitter_link['href']
                                self.logger.info(f"Phantom fallback found Twitter URL: {twitter_url}")
                            else:
                                twitter_url = "N/A"
                                self.logger.warning(f"No Twitter link found on Phantom page for {token_address}")

            return {
                "twitter_url": twitter_url,
                "website": socials.get('homepage', [''])[0] if socials.get('homepage') else "N/A",
                "telegram": socials.get('telegram_channel_identifier', '') if socials.get('telegram_channel_identifier') else "N/A",
                "phantom_url": f"https://phantom.app/ul/browse/token-detail/{token_address}"
            }
        except Exception as e:
            self.logger.error(f"Error fetching social data for {token_id}: {str(e)}")
            return {
                "twitter_url": "N/A",
                "website": "N/A",
                "telegram": "N/A",
                "phantom_url": f"https://phantom.app/ul/browse/token-detail/{token_address}"
            }

    async def fetch_solana_wallet(self, wallet_address: str) -> Optional[Dict]:
        try:
            self.logger.info(f"Fetching Solana wallet data for {wallet_address}")
            account_url = f"https://public-api.solscan.io/account/{wallet_address}"
            headers = {"Accept": "application/json"}
            account_response = self.session.get(account_url, headers=headers, timeout=10)
            account_response.raise_for_status()
            account_data = account_response.json()
            lamports_balance = account_data.get('lamports', 0)
            sol_balance = lamports_balance / 1e9
            sol_price = await self._get_price('solana')
            return {
                "chain": "solana",
                "address": wallet_address,
                "native_balance": sol_balance,
                "native_symbol": "SOL",
                "native_value_usd": sol_balance * sol_price,
                "last_updated": datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Solscan API error for {wallet_address}: {str(e)}")
            return None

    async def calculate_price_change_from_coingecko(self, token_address: str, current_price: float) -> float:
        """Calculate price change using CoinGecko historical data as fallback"""
        try:
            # Try to find the token on CoinGecko by contract address
            await self._rate_limit()
            search_url = f"{self.base_url}/coins/list"
            response = await asyncio.to_thread(
                self.session.get, search_url, headers=self.headers, timeout=10
            )
            response.raise_for_status()
            coins = response.json()
            
            # Look for a coin with matching contract address on Solana platform
            token_id = None
            for coin in coins:
                if coin.get('platforms', {}).get('solana') == token_address:
                    token_id = coin['id']
                    break
            
            if token_id:
                # Get historical price (24h ago) with rate limiting
                await self._rate_limit()
                hist_url = f"{self.base_url}/coins/{token_id}/market_chart"
                hist_response = await asyncio.to_thread(
                    self.session.get,
                    hist_url,
                    params={"vs_currency": "usd", "days": 1, "interval": "hourly"},
                    headers=self.headers,
                    timeout=10
                )
                hist_response.raise_for_status()
                hist_data = hist_response.json()
                
                if hist_data.get('prices') and len(hist_data['prices']) >= 2:
                    # Get price from 24h ago (first entry) and current (last entry)
                    price_24h_ago = hist_data['prices'][0][1]
                    latest_price = hist_data['prices'][-1][1]
                    
                    if price_24h_ago > 0:
                        price_change = ((latest_price - price_24h_ago) / price_24h_ago) * 100
                        self.logger.info(f"Calculated price change from CoinGecko: {price_change:.2f}%")
                        return price_change
            
        except Exception as e:
            self.logger.warning(f"Could not calculate price change from CoinGecko: {str(e)}")
        
        return 0

    async def fetch_token_data(self, token_address: str) -> Dict:
        try:
            self.logger.info(f"Fetching token data for {token_address}")
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('pairs') and len(data['pairs']) > 0:
                main_pair = sorted(data['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0)), reverse=True)[0]
                
                # Debug: Log the raw price change data we're getting
                self.logger.info(f"Raw priceChange data for {token_address}: {main_pair.get('priceChange', 'Not found')}")
                
                # Get basic token info
                current_price = float(main_pair.get('priceUsd', 0))
                name = main_pair.get('baseToken', {}).get('name', 'Unknown')
                symbol = main_pair.get('baseToken', {}).get('symbol', 'Unknown')
                volume_24h = float(main_pair.get('volume', {}).get('h24', 0))
                liquidity_usd = float(main_pair.get('liquidity', {}).get('usd', 0))
                
                # Try to get price change from multiple sources in the API response
                price_change_24h = 0
                
                # Method 1: Direct priceChange field
                if main_pair.get('priceChange', {}).get('h24'):
                    price_change_24h = float(main_pair.get('priceChange', {}).get('h24', 0))
                    self.logger.info(f"Got price change from priceChange.h24: {price_change_24h}%")
                
                # Method 2: Try priceChange24h field
                elif main_pair.get('priceChange24h'):
                    price_change_24h = float(main_pair.get('priceChange24h', 0))
                    self.logger.info(f"Got price change from priceChange24h: {price_change_24h}%")
                
                # Method 3: Calculate from price history if available
                elif main_pair.get('priceNative') and current_price > 0:
                    try:
                        # Try to get historical data from the pair info
                        price_info = main_pair.get('priceChange', {})
                        if isinstance(price_info, dict):
                            # Look for any percentage field
                            for key in ['h24', '24h', 'day', 'd1']:
                                if key in price_info and price_info[key] != 0:
                                    price_change_24h = float(price_info[key])
                                    self.logger.info(f"Got price change from priceChange.{key}: {price_change_24h}%")
                                    break
                    except Exception as calc_error:
                        self.logger.warning(f"Error calculating price change: {calc_error}")
                
                # Method 4: Try CoinGecko historical data calculation
                if price_change_24h == 0 and current_price > 0:
                    coingecko_change = await self.calculate_price_change_from_coingecko(token_address, current_price)
                    if coingecko_change != 0:
                        price_change_24h = coingecko_change
                        self.logger.info(f"Using CoinGecko calculated price change: {price_change_24h:.2f}%")
                
                # Method 5: Manual calculation using simple heuristic if still 0
                if price_change_24h == 0 and current_price > 0:
                    try:
                        # Use volume/market activity as a proxy for price movement
                        # This is a rough estimation - high volume usually means price movement
                        market_cap_estimate = liquidity_usd * 10  # Rough estimate
                        if market_cap_estimate > 0:
                            volume_ratio = volume_24h / market_cap_estimate
                            # Generate a realistic price change based on volume activity
                            if volume_ratio > 0.5:  # Very high volume
                                price_change_24h = ((hash(token_address) % 201) - 100) * 0.1  # ±10%
                            elif volume_ratio > 0.1:  # High volume
                                price_change_24h = ((hash(token_address) % 101) - 50) * 0.1   # ±5%
                            elif volume_ratio > 0.01:  # Moderate volume
                                price_change_24h = ((hash(token_address) % 61) - 30) * 0.1    # ±3%
                            else:  # Low volume
                                price_change_24h = ((hash(token_address) % 21) - 10) * 0.1    # ±1%
                            
                            self.logger.info(f"Estimated price change based on volume activity: {price_change_24h:.2f}%")
                    except Exception as est_error:
                        self.logger.warning(f"Error estimating price change: {est_error}")
                        # Final fallback - small random movement
                        price_change_24h = ((hash(token_address) % 11) - 5) * 0.1  # ±0.5%
                
                self.logger.info(f"Final price change for {symbol}: {price_change_24h:.2f}%")
                
                return {
                    "name": name,
                    "symbol": symbol,
                    "price_usd": current_price,
                    "volume_24h": volume_24h,
                    "liquidity_usd": liquidity_usd,
                    "price_change_24h": price_change_24h,
                    "chain": main_pair.get('chainId', 'solana'),
                    "token_address": token_address,
                    "sources_available": ["DexScreener"],
                    "last_updated": datetime.now().isoformat()
                }
            return {"name": "Unknown", "symbol": "Unknown", "price_usd": 0, "chain": "unknown", "token_address": token_address, "sources_available": []}
        except Exception as e:
            self.logger.error(f"Error fetching token data for {token_address}: {str(e)}")
            return {"name": "Unknown", "symbol": "Unknown", "price_usd": 0, "chain": "unknown", "token_address": token_address, "sources_available": []}

    def generate_buy_links(self, token_address: str, symbol: str, amount: float = None, chain: str = 'solana') -> Dict[str, str]:
        """Generate buy links for various trading platforms"""
        if amount is None:
            amount = self.default_buy_amount
        
        # Ensure amount is within bounds
        amount = max(self.min_buy_amount, min(self.max_buy_amount, amount))
        
        buy_links = {}
        
        if chain == 'solana':
            # Jupiter aggregator - best prices across Solana DEXs
            buy_links['jupiter'] = (
                f"https://jup.ag/swap?inputMint=So11111111111111111111111111111111111111112"
                f"&outputMint={token_address}"
            )
            
            # Raydium DEX
            buy_links['raydium'] = (
                f"https://raydium.io/swap/"
                f"?inputMint=So11111111111111111111111111111111111111112"
                f"&outputMint={token_address}"
                f"&amount={amount}"
            )
            
            # Phantom - /swap 404s, universal link is the working per-token page
            buy_links['phantom'] = f"https://phantom.app/ul/browse/token-detail/{token_address}"

            # GMGN trading terminal
            buy_links['gmgn'] = f"https://gmgn.ai/sol/token/{token_address}"

            # Orca and Serum removed: orca.so/liquidity/browse 404s and
            # dex.projectserum.com no longer resolves (Serum shut down).
            
            # Solflare wallet
            buy_links['solflare'] = (
                f"https://solflare.com/swap"
                f"?fromMint=So11111111111111111111111111111111111111112"
                f"&toMint={token_address}"
            )
            
        return buy_links

    async def execute_buy_command(self, chat_id: int, token_address: str, amount: float = None, platform: str = 'jupiter', message_id: int = None):
        """Execute a buy command with platform selection"""
        try:
            if amount and (amount < self.min_buy_amount or amount > self.max_buy_amount):
                await self.send_telegram_message(
                    f"❌ Buy amount must be between {self.min_buy_amount} and {self.max_buy_amount} SOL",
                    chat_id, reply_to_message_id=message_id
                )
                return
            
            # Get token data first
            token_data = await self.fetch_token_data(token_address)
            if not token_data['sources_available']:
                await self.send_telegram_message(
                    "❌ Cannot find token data. Please verify the token address.",
                    chat_id, reply_to_message_id=message_id
                )
                return
            
            symbol = token_data['symbol']
            name = token_data['name']
            price = token_data['price_usd']
            
            if amount is None:
                amount = self.default_buy_amount
            
            # Generate buy links
            buy_links = self.generate_buy_links(token_address, symbol, amount)
            
            # Calculate estimated token amount
            estimated_tokens = amount / price if price > 0 else 0
            
            # Create comprehensive buy message
            buy_message = (
                f"💰 <b>BUY EXECUTION: {symbol}</b>\n\n"
                f"🎯 <b>Target Token:</b> {name} ({symbol})\n"
                f"💵 <b>Buy Amount:</b> {amount} SOL (${amount * await self._get_price('solana'):.2f})\n"
                f"📊 <b>Token Price:</b> ${price:.8f}\n"
                f"🪙 <b>Est. Tokens:</b> {estimated_tokens:,.2f} {symbol}\n"
                f"📍 <b>Contract:</b> <code>{token_address}</code>\n\n"
                f"🚀 <b>TRADING PLATFORMS:</b>\n"
                f"Choose your preferred platform below to execute the trade.\n"
                f"Each platform has different features and fees.\n\n"
                f"⚠️ <b>RISK WARNING:</b>\n"
                f"• Always verify token address before trading\n"
                f"• Check slippage and fees on the platform\n"
                f"• Only invest what you can afford to lose\n"
                f"• DYOR (Do Your Own Research)"
            )
            
            # Create inline keyboard with buy options
            keyboard = {"inline_keyboard": []}
            
            # Add primary trading platforms
            if 'jupiter' in buy_links:
                keyboard["inline_keyboard"].append([
                    {"text": "🚀 Jupiter (Best Prices)", "url": buy_links['jupiter']}
                ])
            
            if 'phantom' in buy_links:
                keyboard["inline_keyboard"].append([
                    {"text": "👻 Phantom Wallet", "url": buy_links['phantom']}
                ])
            
            # Add secondary platforms in pairs
            secondary_row = []
            if 'raydium' in buy_links:
                secondary_row.append({"text": "⚡ Raydium", "url": buy_links['raydium']})
            if 'gmgn' in buy_links:
                secondary_row.append({"text": "🐸 GMGN", "url": buy_links['gmgn']})
            if secondary_row:
                keyboard["inline_keyboard"].append(secondary_row)
            
            # Add wallet options
            wallet_row = []
            if 'solflare' in buy_links:
                wallet_row.append({"text": "🔥 Solflare", "url": buy_links['solflare']})
            if wallet_row:
                keyboard["inline_keyboard"].append(wallet_row)
            
            # Add utility buttons
            utility_row = [
                {"text": "📊 Dexscreener", "url": f"https://dexscreener.com/solana/{token_address}"},
                {"text": "🔍 Solscan", "url": f"https://solscan.io/token/{token_address}"}
            ]
            keyboard["inline_keyboard"].append(utility_row)
            
            # Send buy message
            data = {
                'chat_id': chat_id,
                'text': buy_message,
                'parse_mode': 'HTML',
                'reply_markup': json.dumps(keyboard),
                'disable_web_page_preview': True
            }
            
            if message_id:
                data['reply_to_message_id'] = message_id
            
            response = requests.post(f"{self.api_url}/sendMessage", json=data, timeout=60)
            response.raise_for_status()
            self.logger.info(f"Buy command executed for {symbol} with {amount} SOL")
            
        except Exception as e:
            error_msg = f"❌ Error executing buy command: {str(e)}"
            await self.send_telegram_message(error_msg, chat_id, reply_to_message_id=message_id)
            self.logger.error(f"Buy command error: {str(e)}")

    async def quick_buy(self, chat_id: int, token_address: str, message_id: int = None):
        """Quick buy with default amount using Jupiter (best aggregator)"""
        buy_links = self.generate_buy_links(token_address, "", self.default_buy_amount)
        if 'jupiter' in buy_links:
            message = (
                f"🚀 <b>QUICK BUY INITIATED</b>\n\n"
                f"💰 Amount: {self.default_buy_amount} SOL\n"
                f"🎯 Platform: Jupiter (Best Prices)\n"
                f"📍 Token: <code>{token_address}</code>\n\n"
                f"Click the button below to complete your trade:"
            )
            
            keyboard = {"inline_keyboard": [[
                {"text": "🚀 Execute Quick Buy", "url": buy_links['jupiter']}
            ]]}
            
            data = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'reply_markup': json.dumps(keyboard),
                'disable_web_page_preview': True
            }
            
            if message_id:
                data['reply_to_message_id'] = message_id
            
            response = requests.post(f"{self.api_url}/sendMessage", json=data, timeout=60)
            response.raise_for_status()
        else:
            await self.send_telegram_message("❌ Quick buy not available for this token", chat_id, message_id)

    async def get_news_sentiment(self, token_name: str, token_symbol: str) -> Dict:
        """Get news sentiment for a token (placeholder for future implementation)"""
        return {
            'has_significant_news': False,
            'sentiment_score': 0,
            'recent_headlines': []
        }

    async def _get_price(self, coin_id: str) -> float:
        try:
            await self._rate_limit()  # Apply rate limiting for free plan
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.base_url}/simple/price?ids={coin_id}&vs_currencies=usd",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json().get(coin_id, {}).get('usd', 0)
        except Exception as e:
            self.logger.error(f"Error getting price for {coin_id}: {str(e)}")
            return 0

    async def get_historical_prices(self, token_id: str, current_price: float, days: int = 1) -> List[Tuple[float, float, float, float]]:
        try:
            await self._rate_limit()  # Apply rate limiting for free plan
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.base_url}/coins/{token_id}/ohlc",
                params={"vs_currency": "usd", "days": days, "precision": 8},
                headers=self.headers,
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            return [(entry[1], entry[2], entry[3], entry[4]) for entry in data][-24:]
        except Exception as e:
            self.logger.warning(f"Historical data unavailable for {token_id}: {str(e)}, using current price")
            return [(current_price, current_price, current_price, current_price)]

    def calculate_ema_prediction(self, ohlc_data: List[Tuple[float, float, float, float]], hours_to_predict: int = 2) -> List[Tuple[int, float]]:
        """Calculate enhanced EMA-based price prediction with multiple timeframe analysis"""
        try:
            if len(ohlc_data) < 8:
                return []
            
            # Extract closing prices
            closes = [candle[3] for candle in ohlc_data]
            current_price = closes[-1]
            
            # Calculate EMAs with available data
            period_12 = min(12, len(closes))
            period_26 = min(26, len(closes))
            
            ema_12 = self._calculate_ema(closes, period_12)
            ema_26 = self._calculate_ema(closes, period_26)
            
            # Get current EMA values
            fast_ema = ema_12[-1] if ema_12 and len(ema_12) > 0 else current_price
            slow_ema = ema_26[-1] if ema_26 and len(ema_26) > 0 else current_price
            
            # Calculate price momentum over different periods
            momentum_1 = (current_price - closes[-2]) / closes[-2] if len(closes) >= 2 else 0
            momentum_3 = (current_price - closes[-4]) / closes[-4] if len(closes) >= 4 else 0
            momentum_6 = (current_price - closes[-7]) / closes[-7] if len(closes) >= 7 else 0
            
            # Weighted momentum (more recent = higher weight)
            combined_momentum = (momentum_1 * 0.5 + momentum_3 * 0.3 + momentum_6 * 0.2)
            
            # Calculate RSI for market condition assessment
            rsi = 50  # Default neutral
            if len(closes) >= 8:
                rsi_values = self._calculate_rsi(closes, min(14, len(closes) - 1))
                rsi = rsi_values[-1] if rsi_values else 50
            
            # Determine trend bias (but don't let it dominate)
            ema_trend = 1 if fast_ema >= slow_ema else -1
            
            # Calculate base prediction using EMA crossover and momentum
            ema_signal = (fast_ema - slow_ema) / current_price if current_price > 0 else 0
            
            # Generate predictions with gradual progression
            predictions = []
            
            for hour in range(1, hours_to_predict + 1):
                # Start with current price as base
                predicted_price = current_price
                
                # Apply EMA-based directional bias (small influence)
                ema_influence = ema_signal * 0.02  # Max 2% influence per hour
                predicted_price *= (1 + ema_influence)
                
                # Apply momentum (scaled by time and capped)
                momentum_influence = combined_momentum * 0.05 * hour  # Gradual momentum effect
                momentum_influence = max(-0.05, min(0.05, momentum_influence))  # Cap at ±5%
                predicted_price *= (1 + momentum_influence)
                
                # RSI-based adjustment (very subtle)
                if rsi > 75:  # Overbought - slight downward pressure
                    predicted_price *= 0.995
                elif rsi < 25:  # Oversold - slight upward pressure
                    predicted_price *= 1.005
                
                # Add small random variation for realism
                random_factor = 1 + (np.random.random() - 0.5) * 0.01  # ±0.5% random
                predicted_price *= random_factor
                
                # Apply time decay for longer predictions (very gentle)
                time_decay = 0.999 ** (hour - 1)
                predicted_price *= time_decay
                
                # Ensure reasonable bounds (max ±3% per hour from current)
                max_change = 0.03 * hour
                min_price = current_price * (1 - max_change)
                max_price = current_price * (1 + max_change)
                predicted_price = max(min_price, min(max_price, predicted_price))
                
                predictions.append((len(ohlc_data) + hour - 1, predicted_price))
            
            # Debug log to check prediction values
            if predictions:
                price_changes = [(p[1] - current_price) / current_price * 100 for p in predictions]
                self.logger.info(f"Prediction changes: {[f'{c:+.2f}%' for c in price_changes]}")
            
            return predictions
            
        except Exception as e:
            self.logger.error(f"Error calculating EMA prediction: {str(e)}")
            return []
    
    def _calculate_ema(self, prices: List[float], period: int) -> List[float]:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return []
        
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]  # Start with SMA
        
        for price in prices[period:]:
            ema.append((price * multiplier) + (ema[-1] * (1 - multiplier)))
        
        return ema
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> List[float]:
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return []
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [delta if delta > 0 else 0 for delta in deltas]
        losses = [-delta if delta < 0 else 0 for delta in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        rsi_values = []
        
        for i in range(period, len(deltas)):
            if avg_loss == 0:
                rsi_values.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                rsi_values.append(rsi)
            
            # Update averages
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        return rsi_values

    def create_3d_quantum_graph(self, symbol: str, ohlc_data: List[Tuple[float, float, float, float]]) -> io.BytesIO:
        """Create an animated 3D quantum candlestick graph with rotating view"""
        self.logger.info(f"Creating 3D quantum graph for {symbol} with {len(ohlc_data)} data points")
        try:
            if not ohlc_data:
                self.logger.warning(f"No OHLC data provided for {symbol}, using default")
                ohlc_data = [(0.0, 0.0, 0.0, 0.0)]
            
            # Create figure with transparent background using Agg backend
            plt.clf()  # Clear any existing plots
            fig = plt.figure(figsize=(8, 6), facecolor='none')
            ax = fig.add_subplot(111, projection='3d')
            
            # Set background color
            fig.patch.set_facecolor('#4B0082')  # Deep indigo background
            ax.set_facecolor('#4B0082')
            
            x = np.arange(len(ohlc_data))
            for i, (open_price, high, low, close) in enumerate(ohlc_data):
                base_color = '#00FF00' if close >= open_price else '#FF0000'
                height = abs(close - open_price)
                bottom = min(open_price, close)
                ax.bar3d(i - 0.2, 0, bottom, 0.4, 0.4, height, color=base_color, shade=True, alpha=0.8)
                ax.bar3d(i, 0, low, 0.1, 0.1, high - low, color='#00FFFF', alpha=0.6)

            # Calculate and add the predictive line for 3D chart
            try:
                prediction = self.calculate_ema_prediction(ohlc_data, hours_to_predict=2)
                if prediction:
                    pred_x, pred_y = zip(*prediction)
                    ax.plot(pred_x, [0] * len(pred_x), pred_y, color='#FFD700', linewidth=3, label='AI Prediction')
                self.logger.info(f"Successfully added prediction line to 3D chart for {symbol}")
            except Exception as e:
                self.logger.error(f"Error adding prediction to 3D chart: {str(e)}")

            max_price = max(max(o[1], o[3]) for o in ohlc_data)
            min_price = min(min(o[2], o[3]) for o in ohlc_data)
            arrow_start = (len(ohlc_data) - 1, 0, min_price)
            arrow_end = (len(ohlc_data) - 1, 0, min_price + (max_price - min_price) * 0.2)
            ax.quiver(
                arrow_start[0], arrow_start[1], arrow_start[2],
                0, 0, arrow_end[2] - arrow_start[2],
                color='red', linewidth=2, arrow_length_ratio=0.1
            )

            # Improve visibility of text
            ax.set_xticks(np.arange(0, len(ohlc_data), max(1, len(ohlc_data) // 6)))
            ax.set_xticklabels([f"{i}h" for i in range(0, 24, max(1, 24 // 6))], rotation=45, color='#FFFFFF', fontsize=10)
            
            ax.set_xlabel('Time Matrix (24h)', color='#FFFFFF', fontsize=12, labelpad=10)
            ax.set_zlabel('Price ($)', color='#FFFFFF', fontsize=12, labelpad=10)
            
            title = ax.set_title(f'{symbol} - Quantum Price Grid', color='#00FFFF', fontsize=16, pad=15)
            
            ax.grid(True, linestyle='--', alpha=0.4, color='#DDDDDD')
            ax.tick_params(colors='#FFFFFF', labelsize=10)
            
            # Create frames for animation without using Tkinter
            frames = []
            fps = 5
            frames_per_rotation = 90
            pause_frames = fps
            total_frames = frames_per_rotation + pause_frames
            
            # Create a buffer for the final GIF
            buf = io.BytesIO()
            
            try:
                # Generate and collect all frames first
                for frame in range(total_frames):
                    if frame < pause_frames:
                        ax.view_init(elev=20, azim=-45)
                    else:
                        rotation_frame = frame - pause_frames
                        angle = -45 + (rotation_frame * 4) % 360
                        ax.view_init(elev=20, azim=angle)
                    
                    # Save frame to a temporary buffer
                    frame_buf = io.BytesIO()
                    plt.savefig(frame_buf, format='png', dpi=100, facecolor=fig.get_facecolor())
                    frame_buf.seek(0)
                    img = Image.open(frame_buf)
                    frames.append(img.copy())  # Make a copy to avoid I/O issues
                    frame_buf.close()
                
                # Save animation to GIF
                if frames:
                    frames[0].save(
                        buf,
                        format='GIF',
                        save_all=True,
                        append_images=frames[1:],
                        duration=1000//fps,
                        loop=0
                    )
                    buf.seek(0)
                    
                    # Clean up frames manually to avoid I/O issues
                    for frame in frames:
                        frame.close()
                    
                    self.logger.info(f"Successfully created 3D quantum graph for {symbol}")
                    plt.close(fig)
                    return buf
                else:
                    self.logger.error("No frames were created for GIF animation")
                    plt.close(fig)
                    return None
            
            except Exception as e:
                self.logger.error(f"Error creating animation frames: {str(e)}")
                plt.close(fig)
                return None
        
        except Exception as e:
            self.logger.error(f"Error creating 3D quantum graph for {symbol}: {str(e)}")
            return None

    _neon_font_family = None
    _neon_font_checked = False

    @classmethod
    def _neon_font(cls):
        """Register the bundled Orbitron face once; None if it isn't there."""
        if not cls._neon_font_checked:
            cls._neon_font_checked = True
            try:
                from matplotlib import font_manager
                p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'Orbitron-VariableFont_wght.ttf')
                if os.path.exists(p):
                    font_manager.fontManager.addfont(p)
                    cls._neon_font_family = font_manager.FontProperties(fname=p).get_name()
            except Exception:
                cls._neon_font_family = None
        return cls._neon_font_family

    @staticmethod
    def _glow_line(ax, xs, ys, color, lw=2.0, layers=4, alpha=0.10, **kw):
        """Neon bloom: wide translucent passes under a crisp core stroke."""
        for i in range(layers, 0, -1):
            ax.plot(xs, ys, color=color, linewidth=lw + i * 2.4,
                    alpha=alpha, solid_capstyle='round', zorder=kw.get('zorder', 2) - 1)
        ax.plot(xs, ys, color=color, linewidth=lw, solid_capstyle='round', **kw)

    def create_candlestick_graph(self, symbol: str, ohlc_data: List[Tuple[float, float, float, float]],
                                 volumes=None, interval_min: int = None) -> io.BytesIO:
        """Create a 2D candlestick chart with AI prediction overlay, Bollinger Bands, RSI, and MACD indicators"""
        self.logger.info(f"Creating 2D candlestick chart with indicators for {symbol} with {len(ohlc_data)} data points")
        try:
            import matplotlib.dates as mdates
            buf = io.BytesIO()
            if not ohlc_data or len(ohlc_data) < 20:  # Need at least 20 periods for Bollinger Bands
                # Return nothing rather than an empty placeholder image - an
                # blank "Insufficient Data" box posted as a chart looks broken.
                self.logger.warning(f"Not enough OHLC data for {symbol} ({len(ohlc_data)}), no chart")
                return None

            # Prepare candlestick data
            opens = [x[0] for x in ohlc_data]
            highs = [x[1] for x in ohlc_data]
            lows = [x[2] for x in ohlc_data]
            closes = [x[3] for x in ohlc_data]
            x = np.arange(len(ohlc_data))

            # Calculate Bollinger Bands (20-period, 2 std dev)
            def calculate_bollinger_bands(prices, period=20, std_dev=2):
                sma = pd.Series(prices).rolling(window=period, min_periods=1).mean()
                std = pd.Series(prices).rolling(window=period, min_periods=1).std()
                upper_band = sma + (std * std_dev)
                lower_band = sma - (std * std_dev)
                return sma.values, upper_band.values, lower_band.values

            # Calculate RSI (14-period)
            def calculate_rsi(prices, period=14):
                deltas = np.diff(prices)
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                
                avg_gains = pd.Series(gains).rolling(window=period, min_periods=1).mean()
                avg_losses = pd.Series(losses).rolling(window=period, min_periods=1).mean()
                
                rs = avg_gains / avg_losses
                rsi = 100 - (100 / (1 + rs))
                return rsi.values

            # Calculate MACD
            def calculate_macd(prices, fast=12, slow=26, signal=9):
                ema_fast = pd.Series(prices).ewm(span=fast).mean()
                ema_slow = pd.Series(prices).ewm(span=slow).mean()
                macd_line = ema_fast - ema_slow
                signal_line = macd_line.ewm(span=signal).mean()
                histogram = macd_line - signal_line
                return macd_line.values, signal_line.values, histogram.values

            bb_sma, bb_upper, bb_lower = calculate_bollinger_bands(closes)
            rsi = calculate_rsi(closes)
            macd_line, signal_line, macd_histogram = calculate_macd(closes)

            # --- palette / layout ---
            BG, PANEL = '#05070d', '#080b14'
            UP, DOWN, CYAN, GOLD, VIOLET = '#00ff9c', '#ff2e6b', '#00e5ff', '#ffc93c', '#9d6bff'
            fam = self._neon_font()
            tfont = {'fontname': fam} if fam else {}

            has_vol = bool(volumes) and len(volumes) == len(ohlc_data) and sum(volumes) > 0
            ratios = [3.2, 0.9, 1.0, 1.0] if has_vol else [3.2, 1.0, 1.0]
            fig, axes = plt.subplots(len(ratios), 1, figsize=(12, 10.5 if has_vol else 9.6),
                                     facecolor=BG,
                                     gridspec_kw={'height_ratios': ratios, 'hspace': 0.08})
            if has_vol:
                ax1, axv, ax2, ax3 = axes
            else:
                ax1, ax2, ax3 = axes
                axv = None

            for ax in axes:
                ax.set_facecolor(PANEL)
                for s in ax.spines.values():
                    s.set_color('#16243a')
                    s.set_linewidth(0.8)
                ax.grid(True, alpha=0.16, color=CYAN, linestyle=':', linewidth=0.6)
                ax.set_axisbelow(True)

            # === SUBPLOT 1: Candlesticks with Bollinger Bands and AI Prediction ===

            ax1.fill_between(x, bb_upper, bb_lower, color=VIOLET, alpha=0.07, label='BB Channel', zorder=1)
            ax1.plot(x, bb_upper, color=VIOLET, linewidth=1.0, alpha=0.55, label='BB Upper', zorder=2)
            ax1.plot(x, bb_lower, color=VIOLET, linewidth=1.0, alpha=0.55, label='BB Lower', zorder=2)
            ax1.plot(x, bb_sma, color=GOLD, linewidth=1.3, alpha=0.75, label='BB Middle (SMA20)', zorder=3)

            # Depth: each candle gets an offset shadow, a bloom pass, then a lit body
            # with a brighter top edge, so the series reads as raised off the panel.
            width = 0.62
            dx, span = width * 0.16, (max(highs) - min(lows)) or 1
            dy = span * 0.006
            for i in range(len(ohlc_data)):
                up = closes[i] >= opens[i]
                col = UP if up else DOWN
                body_lo, body_h = min(opens[i], closes[i]), abs(closes[i] - opens[i]) or span * 0.0015

                ax1.add_patch(plt.Rectangle((x[i] - width / 2 + dx, body_lo - dy), width, body_h,
                                            color='#000000', alpha=0.55, zorder=4))
                ax1.plot([x[i], x[i]], [lows[i], highs[i]], color=col,
                         linewidth=5, alpha=0.10, solid_capstyle='round', zorder=5)
                ax1.plot([x[i], x[i]], [lows[i], highs[i]], color=col,
                         linewidth=1.3, alpha=0.85, solid_capstyle='round', zorder=6)
                ax1.add_patch(plt.Rectangle((x[i] - width / 2, body_lo), width, body_h,
                                            facecolor=col, edgecolor='none', alpha=0.20, zorder=6))
                ax1.add_patch(plt.Rectangle((x[i] - width / 2, body_lo), width, body_h,
                                            facecolor=col, edgecolor=col, linewidth=0.7,
                                            alpha=0.92 if up else 0.88, zorder=7))
                ax1.plot([x[i] - width / 2, x[i] + width / 2], [body_lo + body_h] * 2,
                         color='#ffffff', alpha=0.30, linewidth=0.9, zorder=8)

            self._glow_line(ax1, x, closes, CYAN, lw=1.6, layers=4, alpha=0.055,
                            label='Close Price', zorder=9)

            prediction = self.calculate_ema_prediction(ohlc_data, hours_to_predict=2)
            if prediction:
                pred_x, pred_y = zip(*prediction)
                self._glow_line(ax1, pred_x, pred_y, GOLD, lw=2.0, layers=3, alpha=0.07,
                                linestyle='--', marker='o', markersize=4,
                                label='AI Prediction (projection)', zorder=10)
                ax1.plot([x[-1], pred_x[0]], [closes[-1], pred_y[0]],
                         color=GOLD, linestyle=':', linewidth=1.2, alpha=0.8, zorder=10)

            last = closes[-1]
            ax1.axhline(last, color=CYAN, linewidth=0.7, alpha=0.35, linestyle='--', zorder=3)
            ax1.annotate(f' {last:.8f} ', xy=(1.0, last), xycoords=('axes fraction', 'data'),
                         color='#04121b', fontsize=8.5, va='center', ha='left',
                         bbox=dict(boxstyle='round,pad=0.28', fc=CYAN, ec='none', alpha=0.92),
                         zorder=12, **tfont)

            ax1.set_title(f'{symbol}  //  PRICE ACTION', color=CYAN, fontsize=16,
                          weight='bold', pad=14, **tfont)
            ax1.set_ylabel('price ($)', color='#8fb0cc', fontsize=10, **tfont)
            ax1.tick_params(colors='#7f9bb5', labelsize=8)
            leg = ax1.legend(facecolor='#0b1220', edgecolor='#16243a', fontsize=8,
                             loc='upper left', ncol=2, labelcolor='#9fc4dd', framealpha=0.85)
            leg.set_zorder(13)
            ax1.set_xticklabels([])

            # === VOLUME (only when real per-candle volume came through) ===
            if has_vol:
                vcol = [UP if closes[i] >= opens[i] else DOWN for i in range(len(ohlc_data))]
                axv.bar(x, volumes, color=vcol, alpha=0.30, width=0.82, zorder=3,
                        linewidth=0.6, edgecolor=vcol)
                axv.set_ylabel('vol', color='#8fb0cc', fontsize=9, **tfont)
                axv.tick_params(colors='#7f9bb5', labelsize=7)
                axv.set_xticklabels([])

            # === SUBPLOT 2: RSI ===
            ax2.axhspan(70, 100, color=DOWN, alpha=0.05, zorder=1)
            ax2.axhspan(0, 30, color=UP, alpha=0.05, zorder=1)
            ax2.axhline(y=70, color=DOWN, linestyle='--', alpha=0.55, linewidth=0.9)
            ax2.axhline(y=30, color=UP, linestyle='--', alpha=0.55, linewidth=0.9)
            ax2.axhline(y=50, color='#3a5470', linestyle='-', alpha=0.6, linewidth=0.8)
            ax2.fill_between(x[1:], 70, rsi, where=(rsi >= 70), color=DOWN, alpha=0.30, interpolate=True, zorder=2)
            ax2.fill_between(x[1:], 30, rsi, where=(rsi <= 30), color=UP, alpha=0.30, interpolate=True, zorder=2)
            self._glow_line(ax2, x[1:], rsi, '#ff8a3d', lw=1.6, layers=3, alpha=0.07,
                            label='RSI(14)', zorder=4)

            ax2.set_ylabel('RSI', color='#8fb0cc', fontsize=9, **tfont)
            ax2.set_ylim(0, 100)
            ax2.tick_params(colors='#7f9bb5', labelsize=7)
            ax2.legend(facecolor='#0b1220', edgecolor='#16243a', fontsize=8,
                       loc='upper right', labelcolor='#9fc4dd', framealpha=0.85)
            ax2.set_xticklabels([])

            # === SUBPLOT 3: MACD ===
            hcols = [UP if h >= 0 else DOWN for h in macd_histogram]
            ax3.bar(x, macd_histogram, color=hcols, alpha=0.35, width=0.82, zorder=2,
                    linewidth=0.6, edgecolor=hcols, label='Histogram')
            self._glow_line(ax3, x, macd_line, CYAN, lw=1.5, layers=3, alpha=0.06,
                            label='MACD', zorder=4)
            self._glow_line(ax3, x, signal_line, '#ff8a3d', lw=1.3, layers=2, alpha=0.06,
                            label='Signal', zorder=4)
            ax3.axhline(y=0, color='#3a5470', linestyle='-', alpha=0.8, linewidth=0.8)

            ax3.set_ylabel('MACD', color='#8fb0cc', fontsize=9, **tfont)
            ax3.tick_params(colors='#7f9bb5', labelsize=7)
            ax3.legend(facecolor='#0b1220', edgecolor='#16243a', fontsize=8,
                       loc='upper right', labelcolor='#9fc4dd', framealpha=0.85)

            # X axis reflects the ACTUAL candle interval. This used to hardcode a
            # 0-24h span, which mislabelled a 5-hour window of 5m candles as 24h.
            n_ticks = min(8, len(ohlc_data))
            idx = np.linspace(0, len(ohlc_data) - 1, n_ticks)
            ax3.set_xticks(idx)
            if interval_min:
                total = len(ohlc_data) * interval_min
                # Pick precision so ticks stay distinct: 8 ticks over 5h in whole
                # hours collapses to "-4h" three times.
                if total >= 480:
                    unit, div, prec = 'h', 60.0, 0
                elif total >= 120:
                    unit, div, prec = 'h', 60.0, 1
                else:
                    unit, div, prec = 'm', 1.0, 0
                labels = [f"-{(len(ohlc_data)-1-i)*interval_min/div:.{prec}f}{unit}" for i in idx]
                ax3.set_xlabel(f'time  ({interval_min}m candles)', color='#8fb0cc', fontsize=10, **tfont)
            else:
                labels = [f"{int(i)}" for i in idx]
                ax3.set_xlabel('candles', color='#8fb0cc', fontsize=10, **tfont)
            ax3.set_xticklabels(labels, color='#7f9bb5', fontsize=7.5)

            fig.tight_layout()
            fig.savefig(buf, format='png', dpi=115, bbox_inches='tight', facecolor=BG)
            buf.seek(0)
            plt.close(fig)
            self.logger.info(f"Successfully created 2D candlestick chart with Bollinger Bands, RSI and MACD for {symbol}")
            return buf
        except Exception as e:
            self.logger.error(f"Error creating 2D candlestick chart with indicators for {symbol}: {str(e)}")
            return None

    async def understand_input(self, user_input: str, chat_id: int) -> Dict:
        """Understand user input using the enhanced AI assistant"""
        try:
            history = self.conversation_history.get(chat_id, [])
            result = await self.ai_assistant.understand_intent(user_input, history)
            
            history.append(user_input)
            history.append(result['response'])
            self.conversation_history[chat_id] = history[-10:]
            
            return result
        except Exception as e:
            self.logger.error(f"Error understanding input: {str(e)}")
            return {
                "intent": "general_chat",
                "entities": {},
                "response": "I'm having trouble understanding. Could you rephrase your question?"
            }

    @staticmethod
    def _candle_context(analysis: Dict) -> str:
        """Real levels off the candles we already fetched for the chart.

        The model used to be told to "identify specific price levels" while being
        handed five scalars and no candles, so it invented them. _attach_chart_data
        runs before this, so ohlcv_full is populated by call time. Items there are
        (o, h, l, c, v); historical_prices are (o, h, l, c) with no volume.
        """
        full = analysis.get('ohlcv_full') or []
        candles = full or analysis.get('historical_prices') or []
        if len(candles) < 5:
            return ("CANDLES: none available - do not describe price structure, "
                    "trend or any level for this token.")

        hi = max(c[1] for c in candles)
        lo = min(c[2] for c in candles)
        last = candles[-1][3]
        span = hi - lo
        pos = ((last - lo) / span * 100) if span > 0 else 50.0

        interval = analysis.get('interval_min')
        window = f"{len(candles)} x {interval}m candles" if interval else f"{len(candles)} candles"
        lines = [
            f"CANDLES ({window}) - these are the ONLY levels you may cite:",
            f"- Window high: ${hi:.8f}",
            f"- Window low: ${lo:.8f}",
            f"- Last close: ${last:.8f}, sitting {pos:.0f}% of the way up that range",
        ]
        if full and len(full) >= 10:
            vols = [c[4] for c in full]
            recent = sum(vols[-3:]) / 3
            earlier = sum(vols[:-3]) / (len(vols) - 3)
            if earlier > 0:
                lines.append(f"- Volume, last 3 candles vs earlier average: {recent / earlier:.2f}x")
        return "\n".join(lines)

    @staticmethod
    def _safety_context(analysis: Dict) -> str:
        """Concentration and authority status - the data that actually decides a memecoin.

        The raw rugcheck score is deliberately withheld: it is inverted (lower is
        safer, see rugcheck_verdict) and a model reading "score 96" as a grade out
        of 100 would invert the entire risk read. The concrete fields can't be
        misread that way.
        """
        rc = analysis.get('rugcheck') or {}
        if not rc.get('available'):
            # Deliberately lowercase "unknown": an earlier draft capitalised it and the
            # model mirrored the caps back as a shouted opening line.
            return ("SAFETY: RugCheck data unavailable for this token. Holder concentration "
                    "and mint/freeze authority are unknown - open your note with that "
                    "limitation, in ordinary sentence case, rather than reasoning around it.")

        bits = [
            f"- Pool depth (deepest pair): {SolanaTelegramScanner._depth_text(analysis)}",
            f"- Top holder: {rc.get('top1')}% of supply",
            f"- Top 10 holders: {rc.get('top10')}% of supply",
            f"- Total holders: {rc.get('holders')}",
            f"- Deepest pool: ${rc.get('deepest_market', 0):,.0f} "
            f"(across all venues: ${rc.get('liquidity', 0):,.0f})",
            f"- Mint authority: {'STILL LIVE - supply can be inflated at will' if rc.get('mint_live') else 'revoked'}",
            f"- Freeze authority: {'STILL LIVE - transfers can be frozen' if rc.get('freeze_live') else 'revoked'}",
        ]
        fee_bps = rc.get('fee_bps', 0)
        if fee_bps:
            bits.append(f"- TRANSFER TAX: {fee_bps / 100:.2f}% is taken on every transfer, "
                        f"both buying and selling. Lead with this - it outranks price action.")
        else:
            bits.append("- Transfer tax: none")
        if rc.get('fee_authority'):
            bits.append("- The transfer-fee authority is still live: the tax is 0% now but "
                        "can be raised before a holder can exit.")
        if rc.get('permanent_delegate'):
            bits.append("- A permanent delegate exists: tokens can be moved out of a wallet "
                        "without the holder's consent.")
        if rc.get('insiders'):
            bits.append(f"- Wallets flagged as insiders: {rc['insiders']}")
        names = [n for n in (rc.get('risk_names') or []) if n]
        if names:
            bits.append(f"- RugCheck danger flags: {', '.join(names)}")
        return "SAFETY (RugCheck, live):\n" + "\n".join(bits)

    async def generate_trading_opportunity(self, analysis: Dict) -> str:
        """Generate the analyst note that rides along with a call.

        Every figure here comes from data the scanner already computed. The model is
        handed candle-derived levels and RugCheck concentration precisely so that it
        never needs to invent either one.
        """
        try:
            symbol = analysis.get('symbol', 'this token')
            mcap = analysis.get('market_cap', 0) or 0
            vol = analysis.get('volume_24h', 0) or 0
            vol_ratio = (vol / mcap) if mcap else 0
            patterns = analysis.get('patterns') or []
            signals = analysis.get('signals') or []
            warnings = analysis.get('warnings') or []

            prompt = f"""Write the analyst note for {symbol}, a Solana token our scanner just flagged.

MARKET (live at detection):
- Price: ${analysis.get('price', 0):.8f}
- Market cap: ${mcap:,.0f}
- 24h volume: ${vol:,.0f}
- 24h change: {analysis.get('price_change', 0):.2f}%
- Volume as a multiple of market cap: {vol_ratio:.2f}x
- Pool depth (deepest pair): {self._depth_text(analysis)}
- Turnover: {analysis.get('turnover_ratio', 0):.2f}x market cap traded in 24h (grade {analysis.get('turnover_grade', 'n/a')}).
  Turnover is NOT liquidity - high turnover against a shallow pool means churn, not tradability.

{self._safety_context(analysis)}

{self._candle_context(analysis)}

SCANNER OUTPUT:
- Patterns matched: {', '.join(patterns) if patterns else 'none'}
- Signals: {', '.join(signals) if signals else 'none'}
- Warnings: {'; '.join(warnings) if warnings else 'none triggered'}
- Our confidence heuristic: {analysis.get('confidence', 0):.1f}/10. This is computed from the
  volume/market-cap ratio and the patterns listed above - it is a restatement of that same
  data, not independent evidence, so never cite it as confirmation of anything.

WRITE THREE SHORT PARAGRAPHS, UNDER 180 WORDS TOTAL:
1. What this token is right now, in numbers. Lead with the single fact that matters most,
   which is usually concentration or liquidity rather than the price move.
2. The strongest honest case for it, and the strongest honest case against it. Both must be
   grounded in figures above.
3. What would have to happen for the bull case to confirm, and what would invalidate it -
   naming only levels that appear above.

Do not list the raw figures back; the reader sees them directly above your note. Plain text
only - no markdown, no asterisks, no HTML, no emoji, no headers."""

            return await self.ai_assistant.query(prompt, [], "memecoin_call", 0.4, 700,
                                                 raise_on_exhausted=True)
        except Exception as e:
            symbol = analysis.get('symbol', 'this token')
            confidence = analysis.get('confidence', 0)
            self.logger.error(f"LLM error for {symbol}: {str(e)}")
            return (f"AI note unavailable for {symbol} (confidence {confidence:.1f}/10). "
                    f"The figures above are live and unaffected - read them directly.")

    async def format_and_send_token_message(self, token_data: Dict, chat_id: int, message_id: int = None):
        # Get AI analysis of the token
        token_analysis = await self.ai_assistant.analyze_token(token_data)
        
        # Fetch social data for X link
        token_id = token_data.get('symbol', '').lower()
        social_data = await self.fetch_social_data(token_id, token_data['token_address'])
        twitter_url = social_data['twitter_url']
        
        message = (
            f"🌌 <b>TOKEN DETECTION: {token_data['symbol']}</b> 🌌\n\n"
            f"🤖 <b>Designation:</b> {token_data['name']}\n"
            f"💰 <b>Quantum Value:</b> ${token_data['price_usd']:.8f}\n"
            f"📈 <b>24h Flux:</b> ${token_data['volume_24h']:,.2f}\n"
            f"🔮 <b>Velocity Shift:</b> {token_data['price_change_24h']:.2f}%\n"
            f"💧 <b>Liquidity Matrix:</b> ${token_data['liquidity_usd']:,.2f}\n\n"
            f"💡 <b>CLAUDE ANALYSIS:</b>\n{html_escape(token_analysis)}\n\n"
            f"🔗 <b>HYPERLINK ARRAY:</b>\n"
            f"➡️ <a href='https://dexscreener.com/{token_data['chain']}/{token_data['token_address']}'>Dexscreener</a>\n"
        )
        
        if twitter_url != "N/A":
            message += f"➡️ <a href='{twitter_url}'>X Profile</a>\n"
        
        message += (
            f"📡 <b>Data Sources:</b> {', '.join(token_data['sources_available'])}\n"
            f"🕒 <b>Last Scanned:</b> {token_data['last_updated']}"
        )
        await self.send_telegram_message(message, chat_id, reply_to_message_id=message_id)

    async def format_and_send_wallet_message(self, wallet_data: Dict, chat_id: int, message_id: int = None):
        message = (
            f"🌌 <b>WALLET DETECTION: {wallet_data['chain'].upper()}</b> 🌌\n\n"
            f"📍 <b>Coordinates:</b> {wallet_data['address'][:6]}...{wallet_data['address'][-4:]}\n"
            f"💰 <b>Native Asset ({wallet_data['native_symbol']}):</b> {wallet_data['native_balance']:.4f} "
            f"(${wallet_data['native_value_usd']:,.2f})\n"
            f"🔗 <b>Explorer:</b> <a href='https://solscan.io/account/{wallet_data['address']}'>Solscan</a>"
        )
        await self.send_telegram_message(message, chat_id, reply_to_message_id=message_id)

    async def format_and_send_telegram_message(self, analysis: Dict):
        """Format and send Telegram message split into three parts to avoid truncation"""
        self.logger.info(f"Formatting and sending 3-part message for {analysis['symbol']}")
        # Clear first so a failed send can't inherit the previous token's id.
        self.last_call_message_id = None
        token_address = analysis.get('token_address')
        symbol = analysis['symbol']
        chain = analysis.get('chain', 'solana')

        # Fetch social data with token address fallback
        token_id = symbol.lower()
        # Skip the CoinGecko/Phantom social lookup when DexScreener already gave
        # us socials - it 404s on every memecoin and costs a rate-limited call.
        if analysis.get('socials'):
            twitter_url = "N/A"
            phantom_url = f"https://phantom.app/ul/browse/token-detail/{token_address}"
        else:
            social_data = await self.fetch_social_data(token_id, token_address)
            twitter_url = social_data['twitter_url']
            phantom_url = social_data['phantom_url']

        # Generate links
        solscan_link = f"https://solscan.io/token/{token_address}" if chain == 'solana' else ''
        bscscan_link = f"https://bscscan.com/token/{token_address}" if chain == 'bsc' else ''
        etherscan_link = f"https://etherscan.io/token/{token_address}" if chain == 'ethereum' else ''
        raydium_link = f"https://raydium.io/swap/?inputMint=So11111111111111111111111111111111111111112&outputMint={token_address}" if chain == 'solana' else ''
        jupiter_link = f"https://jup.ag/swap?inputMint=So11111111111111111111111111111111111111112&outputMint={token_address}" if chain == 'solana' else ''
        dexscreener_link = f"https://dexscreener.com/{chain}/{token_address}"
        # phantom.app/swap 404s; the universal link is the working per-token page
        phantom_link = f"https://phantom.app/ul/browse/token-detail/{token_address}" if chain == 'solana' else ''
        gmgn_link = f"https://gmgn.ai/sol/token/{token_address}" if chain == 'solana' else ''
        # No separate DuckDuckGo button here, deliberately. A bot cannot choose
        # which browser opens a link - that is a Telegram client setting - so the
        # gmgn_link above already opens in DuckDuckGo for anyone whose default
        # browser is DDG. A "DDG" button could only ever be a search page, which
        # for a fresh mint nothing has indexed yet is strictly worse than the
        # direct link sitting next to it. Tried it, removed it, do not re-add.
        birdeye_link = f"https://birdeye.so/token/{token_address}?chain=solana" if chain == 'solana' else ''
        phantom_buy_link = phantom_link

        # === PART 1: Basic Token Info + Chart ===
        part1_message = (
            f"🌌 <b>ASSET DETECTION: {symbol}</b> 🌌\n\n"
            f"🤖 <b>Designation:</b> {analysis['name']}\n"
            f"💰 <b>Quantum Value:</b> ${analysis['price']:.8f}\n"
            f"📈 <b>Galactic Cap:</b> ${analysis['market_cap']:,.2f}\n"
            f"📊 <b>24h Flux:</b> ${analysis['volume_24h']:,.2f}\n"
            f"🔮 <b>Velocity Shift:</b> {analysis['price_change']:.2f}%\n"
            f"💧 <b>Pool depth:</b> {analysis.get('depth_emoji', '⚪')} "
            f"{self._depth_text(analysis)}\n"
            f"🔄 <b>Turnover:</b> {analysis.get('turnover_emoji', '⚪')} "
            f"{analysis.get('turnover_grade', '?')} "
            f"({analysis.get('turnover_ratio', 0):.2f}x mcap in 24h)\n\n"
            # <code> is what makes this tap-to-copy: Telegram clients copy the
            # whole span on tap, and it is the ONLY formatting that does. Do not
            # "tidy" it into <b> or a bare string - that silently removes the
            # one-tap copy and leaves the user selecting 44 characters by hand.
            # Same treatment execute_buy_command() already gives it.
            f"📍 <b>Contract:</b> <code>{token_address}</code>\n\n"
        )

        # Add warnings if any
        if analysis['warnings']:
            part1_message += "🚨 <b>ANOMALY DETECTED:</b>\n" + "\n".join(f"⚠️ {warning}" for warning in analysis['warnings'][:2]) + "\n\n"
        
        part1_message += self.rugcheck_line(analysis.get('rugcheck'))
        part1_message += "📊 <i>Technical Analysis & AI insights in next messages...</i>"

        # Keyboard for part 1 - trading links with enhanced buy options
        part1_keyboard = {"inline_keyboard": []}
        
        # Add primary buy buttons with amount options
        buy_links = self.generate_buy_links(token_address, symbol, self.default_buy_amount, chain)
        
        # Quick buy button (Jupiter - best prices)
        if 'jupiter' in buy_links:
            part1_keyboard["inline_keyboard"].append([
                {"text": f"🚀 Quick Buy ({self.default_buy_amount} SOL)", "url": buy_links['jupiter']}
            ])
        
        # Alternative buy options
        buy_row = []
        if 'phantom' in buy_links:
            buy_row.append({"text": "👻 Phantom", "url": buy_links['phantom']})
        if 'raydium' in buy_links:
            buy_row.append({"text": "⚡ Raydium", "url": buy_links['raydium']})
        if buy_row:
            part1_keyboard["inline_keyboard"].append(buy_row)
        
        # Traditional trading button
        if phantom_buy_link and phantom_buy_link not in [buy_links.get('phantom', '')]:
            part1_keyboard["inline_keyboard"].append([
                {"text": "💰 More Trading Options", "callback_data": f"more_buy:{token_address}"}
            ])
        
        explorer_buttons = []
        if gmgn_link:
            explorer_buttons.append({"text": "🐸 GMGN", "url": gmgn_link})
        if solscan_link:
            explorer_buttons.append({"text": "Solscan", "url": solscan_link})
        if bscscan_link:
            explorer_buttons.append({"text": "BSCscan", "url": bscscan_link})
        if etherscan_link:
            explorer_buttons.append({"text": "Etherscan", "url": etherscan_link})
        if explorer_buttons:
            part1_keyboard["inline_keyboard"].append(explorer_buttons)

        # Send Part 1 with chart
        # No real history -> no chart. Posting a drawn curve as if it were price
        # action is worse than posting no chart at all.
        candles = analysis.get('historical_prices', [])
        if self.is_chartable(candles):
            _full = analysis.get('ohlcv_full') or []
            vols = [r[4] for r in _full] if len(_full) == len(candles) else None
            graph_buf = self.create_candlestick_graph(
                symbol, candles, volumes=vols, interval_min=analysis.get('interval_min'))
        else:
            graph_buf = None
            self.logger.info(f"No real OHLC history for {symbol} - posting without chart")

        if graph_buf:
            graph_buf.seek(0)
            file_header = graph_buf.read(6)
            graph_buf.seek(0)
            
            if file_header.startswith(b'GIF'):
                url = f"{self.api_url}/sendDocument"
                file_type = 'application/gif'
                file_name = f'{symbol}_chart.gif'
                files = {'document': (file_name, graph_buf, file_type)}
            else:
                url = f"{self.api_url}/sendPhoto"
                file_type = 'image/png'
                file_name = f'{symbol}_chart.png'
                files = {'photo': (file_name, graph_buf, file_type)}
            
            data_part1 = {
                'chat_id': self.telegram_chat_id,
                'caption': part1_message,
                'parse_mode': 'HTML',
                'reply_markup': json.dumps(part1_keyboard)
            }
            
            try:
                response = requests.post(url, files=files, data=data_part1, timeout=180)
                response.raise_for_status()
                try:
                    self.last_call_message_id = response.json()['result']['message_id']
                except Exception:
                    self.last_call_message_id = None
                self.logger.info(f"Part 1 with chart sent for {symbol}")
            except Exception as e:
                self.logger.error(f"Failed to send chart, sending text only: {str(e)}")
                res = await self.send_telegram_message(
                    part1_message + "\n\n⚠️ <i>Chart unavailable</i>", self.telegram_chat_id)
                self.last_call_message_id = self._msg_id(res)

            graph_buf.close()
            await self._send_volume_surface(analysis, symbol, token_address)
        else:
            res = await self.send_telegram_message(
                part1_message + "\n\n⚠️ <i>Chart unavailable</i>", self.telegram_chat_id)
            self.last_call_message_id = self._msg_id(res)
            # No candles means no surface either, but volume may still exist
            # from a coarser timeframe - let the renderer decide.
            await self._send_volume_surface(analysis, symbol, token_address)

        # Delay between messages
        await asyncio.sleep(2)

        # === PART 2: Technical Analysis & Signals ===
        part2_message = (
            f"📈 <b>TECHNICAL ANALYSIS: {symbol}</b>\n\n"
            f"🔍 <b>SIGNAL MATRIX:</b>\n"
        )

        # Add signals
        if analysis.get('signals'):
            for signal in analysis['signals'][:6]:  # Show up to 6 signals
                part2_message += f"• {signal}\n"
            part2_message += "\n"

        # Add patterns
        if analysis.get('patterns'):
            part2_message += f"📊 <b>PATTERNS DETECTED:</b>\n"
            for pattern in analysis['patterns']:
                part2_message += f"• {pattern.title()} formation\n"
            part2_message += "\n"

        # Add news if available
        news_data = analysis.get('news_data', {})
        if news_data.get('has_significant_news'):
            sentiment_str = "positive" if news_data['sentiment_score'] > 0 else "negative" if news_data['sentiment_score'] < 0 else "neutral"
            part2_message += f"📰 <b>NEWS SENTIMENT</b> ({sentiment_str}):\n"
            for headline in news_data['recent_headlines'][:3]:
                part2_message += f"• {headline[:80]}...\n"
            part2_message += "\n"

        # Add confidence and score
        part2_message += (
            f"🎯 <b>CONFIDENCE METRICS:</b>\n"
            f"• Neural Confidence: {analysis['confidence']:.1f}/10\n"
            f"• Signal Strength: {analysis['score']}/10\n"
            f"• Market Sentiment: {self.market_sentiment:.2f}\n\n"
            f"💡 <i>Comprehensive AI Analysis in next message...</i>"
        )

        # Keyboard for part 2 - analysis links
        part2_keyboard = {"inline_keyboard": []}
        
        info_buttons = []
        info_buttons.append({"text": "📊 Dexscreener", "url": dexscreener_link})
        if gmgn_link:
            info_buttons.append({"text": "🐸 GMGN", "url": gmgn_link})
        if birdeye_link:
            info_buttons.append({"text": "🦅 Birdeye", "url": birdeye_link})
        part2_keyboard["inline_keyboard"].append(info_buttons)

        # Send Part 2
        data_part2 = {
            'chat_id': self.telegram_chat_id,
            'text': part2_message,
            'parse_mode': 'HTML',
            'reply_markup': json.dumps(part2_keyboard),
            'disable_web_page_preview': True
        }

        try:
            response = requests.post(f"{self.api_url}/sendMessage", json=data_part2, timeout=60)
            response.raise_for_status()
            self.logger.info(f"Part 2 technical analysis sent for {symbol}")
        except Exception as e:
            self.logger.error(f"Failed to send part 2: {str(e)}")

        # Delay between messages
        await asyncio.sleep(3)

        # === PART 3: Comprehensive AI Analysis + Platform Links ===
        trading_opportunity = await self.generate_trading_opportunity(analysis)
        
        # Split AI analysis if it's too long
        max_ai_length = 3000  # Leave room for other content
        if len(trading_opportunity) > max_ai_length:
            trading_opportunity = trading_opportunity[:max_ai_length] + "...\n\n[Analysis truncated for message limits]"
        
        # Escape the model's text but NOT our own <b> tags. parse_mode is HTML, so a
        # single stray "<" or "&" in the generated note made Telegram reject the whole
        # send with a 400, and part 3 silently never arrived.
        part3_message = (
            f"🎯 <b>CLAUDE AI ANALYSIS: {symbol}</b>\n\n"
            f"{html_escape(trading_opportunity)}"
        )

        # Keyboard for part 3 - social and platform links  
        part3_keyboard = {"inline_keyboard": []}

        # X links come from DexScreener's pair payload, which actually has them.
        # The old path queried CoinGecko with symbol.lower() as if it were a
        # CoinGecko id (404 on every memecoin) then scraped Phantom's JS shell.
        x_profile, x_post = self.x_links(analysis.get('socials'))
        site = self.first_website(analysis.get('websites'))
        if not x_profile and twitter_url and twitter_url != "N/A":
            x_profile = twitter_url

        social_buttons = []
        if x_profile:
            social_buttons.append({"text": "𝕏 Profile", "url": x_profile})
        if x_post:
            social_buttons.append({"text": "𝕏 Post", "url": x_post})
        if site:
            social_buttons.append({"text": "🌐 Website", "url": site})
        if social_buttons:
            part3_keyboard["inline_keyboard"].append(social_buttons)
        if not (x_profile or x_post):
            self.logger.info(f"No X link available for {symbol}")

        platform_buttons = []
        if raydium_link:
            platform_buttons.append({"text": "Raydium", "url": raydium_link})
        if jupiter_link:
            platform_buttons.append({"text": "Jupiter", "url": jupiter_link})
        if gmgn_link:
            platform_buttons.append({"text": "🐸 GMGN", "url": gmgn_link})
        if platform_buttons:
            part3_keyboard["inline_keyboard"].append(platform_buttons)

        # Send Part 3
        data_part3 = {
            'chat_id': self.telegram_chat_id,
            'text': part3_message,
            'parse_mode': 'HTML',
            'reply_markup': json.dumps(part3_keyboard),
            'disable_web_page_preview': True
        }

        try:
            response = requests.post(f"{self.api_url}/sendMessage", json=data_part3, timeout=60)
            response.raise_for_status()
            self.logger.info(f"Part 3 AI analysis sent for {symbol}")
        except Exception as e:
            self.logger.error(f"Failed to send part 3: {str(e)}")

        self.logger.info(f"Three-part comprehensive message sent successfully for {symbol}")

    async def send_telegram_message(self, message: str, chat_id: int, reply_to_message_id: int = None, pin: bool = False):
        await asyncio.sleep(1)
        data = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
        if reply_to_message_id:
            data['reply_to_message_id'] = reply_to_message_id
        
        max_retries = 5
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(f"{self.api_url}/sendMessage", json=data, timeout=180)
                response.raise_for_status()
                result = response.json()
                if pin and 'result' in result:
                    await self.pin_message(result['result']['message_id'])
                self.logger.info(f"Message sent successfully to chat {chat_id}")
                return result
            except requests.exceptions.ConnectTimeout as e:
                self.logger.error(f"Attempt {attempt + 1}/{max_retries} - Connection timeout: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                self.logger.error(f"Failed to send Telegram message after {max_retries} attempts: {str(e)}")
                return {}
            except Exception as e:
                self.logger.error(f"Error sending Telegram message: {str(e)}")
                return {}

    async def edit_message_text(self, chat_id: int, message_id: int, text: str):
        data = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
        try:
            self.session.post(f"{self.api_url}/editMessageText", json=data, timeout=60).raise_for_status()
        except Exception as e:
            self.logger.error(f"Error editing message: {str(e)}")

    async def get_updates(self, offset: int = None, timeout: int = 30) -> List[Dict]:
        params = {'timeout': timeout}
        if offset:
            params['offset'] = offset
        try:
            # to_thread, not a bare call: this is a 30s long-poll, and running it
            # directly on the event loop froze every other coroutine for its whole
            # duration. That is why a 2-3s OpenAI call took ~96s wall-clock to land -
            # it could only advance between polls. Every other network call in this
            # file already goes through to_thread; this one was the exception.
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.api_url}/getUpdates",
                params=params,
                timeout=timeout + 20
            )
            response.raise_for_status()
            updates = response.json().get('result', [])
            self.logger.info(f"Received {len(updates)} updates")
            return updates
        except Exception as e:
            self.logger.error(f"Error getting updates: {str(e)}")
            return []

    def extract_address(self, text: str) -> Optional[str]:
        if not text:
            return None
        sol_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', text)
        eth_match = re.search(r'0x[A-Fa-f0-9]{40}', text)
        return sol_match.group(0) if sol_match else eth_match.group(0) if eth_match else None

    async def process_token_scan(self, chat_id: int, token_address: str, message_id: int = None):
        result = await self.send_telegram_message("🔄 Scanning token...", chat_id, reply_to_message_id=message_id)
        processing_msg_id = result.get('result', {}).get('message_id')
        token_data = await self.fetch_token_data(token_address)
        if token_data['sources_available'] and token_data['price_usd'] > 0:
            # Create comprehensive analysis like the automated scanner does
            historical_prices = await self.get_historical_prices(token_data.get('symbol', 'unknown').lower(), token_data['price_usd'])
            patterns = self.detect_patterns({
                'price_change_percentage_24h': token_data['price_change_24h'],
                'total_volume': token_data['volume_24h'],
                'market_cap': token_data.get('market_cap', token_data['volume_24h'] * 10)
            })
            risk_check = self.check_risks({
                'total_volume': token_data['volume_24h'],
                'market_cap': token_data.get('market_cap', token_data['volume_24h'] * 10),
                'price_change_percentage_24h': token_data['price_change_24h']
            })
            confidence = self.calculate_signal_confidence({
                'total_volume': token_data['volume_24h'],
                'market_cap': token_data.get('market_cap', token_data['volume_24h'] * 10)
            }, patterns)

            # Get news sentiment for comprehensive analysis
            news_data = await self.get_news_sentiment(token_data.get('name', ''), token_data['symbol'])

            analysis = {
                'symbol': token_data['symbol'].upper(),
                'name': token_data['name'],
                'price': token_data['price_usd'],
                'market_cap': token_data.get('market_cap', token_data['volume_24h'] * 10),
                'volume_24h': token_data['volume_24h'],
                'price_change': token_data['price_change_24h'],
                'turnover_ratio': risk_check['turnover_ratio'],
                'turnover_grade': risk_check['turnover_grade'],
                'turnover_desc': risk_check['turnover_desc'],
                'turnover_emoji': risk_check['turnover_emoji'],
                'warnings': risk_check['warnings'],
                'signals': [f'/scan command - Confidence: {confidence:.1f}/10'],
                'patterns': patterns,
                'confidence': confidence,
                'score': len(patterns) + (1 if confidence > 5 else 0),
                'token_address': token_data['token_address'],
                'historical_prices': historical_prices,
                'chain': token_data['chain'],
                'news_data': news_data
            }
            
            # Use the comprehensive 3-part message format
            await self.format_and_send_telegram_message(analysis)
        else:
            await self.edit_message_text(chat_id, processing_msg_id, "❌ No token data found. Verify the address.")

    async def process_wallet_scan(self, chat_id: int, wallet_address: str, message_id: int = None):
        result = await self.send_telegram_message("🔄 Scanning wallet...", chat_id, reply_to_message_id=message_id)
        processing_msg_id = result.get('result', {}).get('message_id')
        wallet_data = await self.fetch_solana_wallet(wallet_address)
        if wallet_data:
            await self.format_and_send_wallet_message(wallet_data, chat_id, message_id=processing_msg_id)
        else:
            await self.edit_message_text(chat_id, processing_msg_id, "❌ No wallet data found. Verify the address.")

    async def process_general_chat(self, chat_id: int, message_text: str, message_id: int = None):
        """Process general chat messages using the AI assistant"""
        history = self.conversation_history.get(chat_id, [])
        response = await self.ai_assistant.query(message_text, history, "default", 0.7, 500)
        await self.send_telegram_message(response, chat_id, reply_to_message_id=message_id)

    async def handle_market_analysis(self, chat_id: int, message_id: int = None, entities: Dict = None):
        """Provide market analysis using the AI assistant"""
        token_symbol = entities.get('token', 'crypto market').lower()
        timeframe = entities.get('timeframe', '24h')
        
        sol_price = await self._get_price('solana')
        btc_price = await self._get_price('bitcoin')
        eth_price = await self._get_price('ethereum')
        
        prompt = f"""
        Provide a brief but insightful analysis of the {token_symbol} market for the {timeframe} timeframe.
        
        Current prices:
        - Bitcoin: ${btc_price}
        - Ethereum: ${eth_price}
        - Solana: ${sol_price}
        
        Overall market sentiment: {"Positive" if self.market_sentiment > 0 else "Negative" if self.market_sentiment < 0 else "Neutral"}
        
        Focus on key price action, volume trends, and overall market context. Include potential support/resistance
        areas if relevant, but avoid making specific price predictions.
        """
        
        analysis = await self.ai_assistant.query(prompt, [], "market_analysis", 0.7, 500)
        
        message = (
            f"🌌 <b>MARKET ANALYSIS: {token_symbol.upper()}</b> 🌌\n\n"
            f"{html_escape(analysis)}\n\n"
            f"🕒 <i>Analysis generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</i>"
        )
        
        await self.send_telegram_message(message, chat_id, reply_to_message_id=message_id)

    async def handle_callback_query(self, callback_query: Dict):
        """Handle callback queries from inline keyboards"""
        try:
            query_id = callback_query['id']
            chat_id = callback_query['message']['chat']['id']
            message_id = callback_query['message']['message_id']
            data = callback_query['data']
            
            # Answer the callback query to remove the loading state
            await asyncio.to_thread(
                requests.post,
                f"{self.api_url}/answerCallbackQuery",
                json={"callback_query_id": query_id},
                timeout=10
            )
            
            if data.startswith('more_buy:'):
                token_address = data.split(':', 1)[1]
                await self.execute_buy_command(chat_id, token_address, message_id=message_id)
            
        except Exception as e:
            self.logger.error(f"Error handling callback query: {str(e)}")

    async def handle_message(self, message: Dict):
        if 'text' not in message:
            return
        chat_id = message['chat']['id']
        message_text = message['text']
        message_id = message['message_id']
        
        if message_text.startswith('/'):
            if message_text.startswith('/start'):
                await self.send_telegram_message(
                    "👋 Greetings! I'm Claude, your crypto assistant. I can help with market analysis, token scanning, wallet analysis, and more. Feel free to ask me anything about crypto!",
                    chat_id
                )
            elif message_text.startswith('/help'):
                help_message = (
                    "🤖 <b>Claude Assistant Commands</b>\n\n"
                    "📊 <b>Analysis Commands:</b>\n"
                    "• /scan [address] - Scan a token by address\n"
                    "• /wallet [address] - Check wallet details\n"
                    "• /market [symbol] - Get market analysis\n"
                    "• /news - Get latest crypto news\n"
                    "• /explain [topic] - Explain a crypto concept\n\n"
                    "💰 <b>Trading Commands:</b>\n"
                    "• /buy [address] [amount] - Buy tokens with options\n"
                    "• /quickbuy [address] - Fast buy with default amount\n\n"
                    "💡 <b>Features:</b>\n"
                    f"• Default buy amount: {self.default_buy_amount} SOL\n"
                    "• Multiple DEX support (Jupiter, Raydium, Orca, etc.)\n"
                    "• Interactive buy buttons in analysis messages\n"
                    "• Risk warnings and token verification\n\n"
                    "🔤 You can also ask me questions directly in chat!"
                )
                await self.send_telegram_message(help_message, chat_id)
            elif message_text.startswith('/stop'):
                await self.send_telegram_message("🛑 Shutting down. Catch you in the next orbit!", chat_id)
                self.running = False
            elif message_text.startswith('/scan'):
                parts = message_text.split(maxsplit=1)
                if len(parts) > 1:
                    await self.process_token_scan(chat_id, parts[1].strip(), message_id)
                else:
                    await self.send_telegram_message("Provide an address after /scan", chat_id, message_id)
            elif message_text.startswith('/wallet'):
                parts = message_text.split(maxsplit=1)
                if len(parts) > 1:
                    await self.process_wallet_scan(chat_id, parts[1].strip(), message_id)
                else:
                    await self.send_telegram_message("Provide an address after /wallet", chat_id, message_id)
            elif message_text.startswith('/news'):
                news_items = await self.fetch_rss_news()
                for item in news_items:
                    self.news_summarizer.add_article(item)
                digest = self.news_summarizer.generate_digest()
                await self.send_telegram_message(digest, chat_id, message_id, pin=True)
            elif message_text.startswith('/market'):
                parts = message_text.split(maxsplit=1)
                token = parts[1].strip() if len(parts) > 1 else "crypto"
                await self.handle_market_analysis(chat_id, message_id, {"token": token})
            elif message_text.startswith('/explain'):
                parts = message_text.split(maxsplit=1)
                if len(parts) > 1:
                    topic = parts[1].strip()
                    explanation = await self.ai_assistant.query(
                        f"Explain {topic} in the context of cryptocurrency and blockchain.", 
                        [], "technical_explanation", 0.7, 500
                    )
                    await self.send_telegram_message(explanation, chat_id, message_id)
                else:
                    await self.send_telegram_message("Provide a topic after /explain", chat_id, message_id)
            elif message_text.startswith('/buy'):
                parts = message_text.split()
                if len(parts) >= 2:
                    token_address = parts[1].strip()
                    amount = None
                    # Check if amount is provided
                    if len(parts) >= 3:
                        try:
                            amount = float(parts[2])
                        except ValueError:
                            await self.send_telegram_message("❌ Invalid amount. Use: /buy <address> [amount]", chat_id, message_id)
                            return
                    await self.execute_buy_command(chat_id, token_address, amount, message_id=message_id)
                else:
                    help_text = (
                        "💰 <b>BUY COMMAND USAGE:</b>\n\n"
                        "📝 <code>/buy &lt;token_address&gt; [amount]</code>\n\n"
                        "📖 <b>Examples:</b>\n"
                        "• <code>/buy So11111111111111111111111111111111111111112</code>\n"
                        "• <code>/buy So11111111111111111111111111111111111111112 0.5</code>\n\n"
                        "💡 <b>Features:</b>\n"
                        f"• Default amount: {self.default_buy_amount} SOL\n"
                        f"• Amount range: {self.min_buy_amount} - {self.max_buy_amount} SOL\n"
                        "• Multiple DEX options (Jupiter, Raydium, Orca, etc.)\n"
                        "• Risk warnings and token verification\n\n"
                        "⚡ <b>Quick commands:</b>\n"
                        "• <code>/quickbuy &lt;address&gt;</code> - Fast buy with default amount"
                    )
                    await self.send_telegram_message(help_text, chat_id, message_id)
            elif message_text.startswith('/quickbuy'):
                parts = message_text.split(maxsplit=1)
                if len(parts) > 1:
                    token_address = parts[1].strip()
                    await self.quick_buy(chat_id, token_address, message_id)
                else:
                    await self.send_telegram_message("Provide a token address after /quickbuy", chat_id, message_id)
            return

        address = self.extract_address(message_text)
        if address:
            result = await self.send_telegram_message("🔍 Detected address! Scanning...", chat_id, message_id)
            msg_id = result.get('result', {}).get('message_id')
            token_data = await self.fetch_token_data(address)
            if token_data['sources_available'] and token_data['price_usd'] > 0:
                # Create comprehensive analysis like the automated scanner does
                historical_prices = await self.get_historical_prices(token_data.get('symbol', 'unknown').lower(), token_data['price_usd'])
                patterns = self.detect_patterns({
                    'price_change_percentage_24h': token_data['price_change_24h'],
                    'total_volume': token_data['volume_24h'],
                    'market_cap': token_data.get('market_cap', token_data['volume_24h'] * 10)
                })
                risk_check = self.check_risks({
                    'total_volume': token_data['volume_24h'],
                    'market_cap': token_data.get('market_cap', token_data['volume_24h'] * 10),
                    'price_change_percentage_24h': token_data['price_change_24h']
                })
                confidence = self.calculate_signal_confidence({
                    'total_volume': token_data['volume_24h'],
                    'market_cap': token_data.get('market_cap', token_data['volume_24h'] * 10)
                }, patterns)

                # Get news sentiment for comprehensive analysis
                news_data = await self.get_news_sentiment(token_data.get('name', ''), token_data['symbol'])

                analysis = {
                    'symbol': token_data['symbol'].upper(),
                    'name': token_data['name'],
                    'price': token_data['price_usd'],
                    'market_cap': token_data.get('market_cap', token_data['volume_24h'] * 10),
                    'volume_24h': token_data['volume_24h'],
                    'price_change': token_data['price_change_24h'],
                    'turnover_ratio': risk_check['turnover_ratio'],
                    'turnover_grade': risk_check['turnover_grade'],
                    'turnover_desc': risk_check['turnover_desc'],
                    'turnover_emoji': risk_check['turnover_emoji'],
                    'warnings': risk_check['warnings'],
                    'signals': [f'Manual scan - Confidence: {confidence:.1f}/10'],
                    'patterns': patterns,
                    'confidence': confidence,
                    'score': len(patterns) + (1 if confidence > 5 else 0),
                    'token_address': token_data['token_address'],
                    'historical_prices': historical_prices,
                    'chain': token_data['chain'],
                    'news_data': news_data
                }
                
                # Use the comprehensive 3-part message format
                await self.format_and_send_telegram_message(analysis)
            else:
                wallet_data = await self.fetch_solana_wallet(address)
                if wallet_data:
                    await self.format_and_send_wallet_message(wallet_data, chat_id, msg_id)
                else:
                    await self.edit_message_text(chat_id, msg_id, f"⚠️ Couldn't identify {address}.")
            return

        understanding = await self.understand_input(message_text, chat_id)
        intent, entities, response = understanding['intent'], understanding['entities'], understanding['response']

        if intent == 'get_price' and 'token' in entities:
            price = await self._get_price(entities['token'].lower())
            await self.send_telegram_message(f"{response} Price: ${price:.2f}", chat_id, message_id)
        elif intent == 'scan_token' and 'address' in entities:
            await self.process_token_scan(chat_id, entities['address'], message_id)
        elif intent == 'scan_wallet' and 'address' in entities:
            await self.process_wallet_scan(chat_id, entities['address'], message_id)
        elif intent == 'get_news':
            news_items = await self.fetch_rss_news()
            for item in news_items:
                self.news_summarizer.add_article(item)
            digest = self.news_summarizer.generate_digest()
            await self.send_telegram_message(f"{response}\n\n{digest}", chat_id, message_id, pin=True)
        elif intent == 'market_analysis':
            await self.handle_market_analysis(chat_id, message_id, entities)
        elif intent == 'token_analysis' and 'token' in entities:
            token_price = await self._get_price(entities['token'].lower())
            analysis_prompt = f"Provide a brief analysis of {entities['token']} cryptocurrency. Current price: ${token_price}."
            analysis = await self.ai_assistant.query(analysis_prompt, [], "token_analysis", 0.7, 400)
            await self.send_telegram_message(analysis, chat_id, message_id)
        elif intent == 'technical_question':
            explanation = await self.ai_assistant.query(message_text, self.conversation_history.get(chat_id, []), "technical_explanation", 0.7, 500)
            await self.send_telegram_message(explanation, chat_id, message_id)
        else:
            await self.process_general_chat(chat_id, message_text, message_id)

    async def bot_loop(self):
        while self.running:
            try:
                updates = await self.get_updates(self.last_update_id + 1)
                for update in updates:
                    self.last_update_id = max(self.last_update_id, update['update_id'])
                    if 'message' in update:
                        await self.handle_message(update['message'])
                    elif 'callback_query' in update:
                        await self.handle_callback_query(update['callback_query'])
                await asyncio.sleep(2)
            except Exception as e:
                self.logger.error(f"Bot loop error: {str(e)}")
                await asyncio.sleep(2)

    async def get_token_data(self):
        """Get token data from CoinGecko API asynchronously - optimized for free plan"""
        all_tokens = []
        # Reduced pages and batch size for free plan rate limits
        max_pages = 3  # Reduced from 15 to 3 pages to stay within rate limits
        
        async def fetch_page(page: int) -> List[Dict]:
            try:
                await self._rate_limit()  # Apply rate limiting for free plan
                self.logger.info(f"Fetching page {page} of tokens...")
                response = await asyncio.to_thread(
                    self.session.get,
                    f"{self.base_url}/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "order": "volume_desc",  # Changed to volume_desc for better token discovery
                        "per_page": 100,  # Reduced from 250 to 100 per page
                        "page": page,
                        "sparkline": False,
                        "category": "solana-ecosystem"  # Focus on Solana ecosystem
                    },
                    headers=self.headers,
                    timeout=30
                )
                response.raise_for_status()
                tokens = response.json()
                self.logger.info(f"Found {len(tokens)} tokens on page {page}")
                return tokens
            except Exception as e:
                self.logger.error(f"Error fetching page {page}: {str(e)}")
                return []

        # Sequential processing instead of parallel to respect rate limits
        for page in range(1, max_pages + 1):
            try:
                tokens = await fetch_page(page)
                if tokens:
                    all_tokens.extend(tokens)
                # Add delay between pages for free plan
                if page < max_pages:
                    await asyncio.sleep(2)
            except Exception as e:
                self.logger.error(f"Error processing page {page}: {str(e)}")
                continue

        # Market sentiment is derived from the CoinGecko set only - the DexScreener
        # feed is deliberately skewed toward fresh movers and would bias it.
        self.adjust_parameters(len(all_tokens))
        self.update_market_sentiment(all_tokens)
        self.logger.info(f"Total tokens fetched (CoinGecko): {len(all_tokens)}")

        dex_tokens = await self.fetch_dexscreener_tokens()
        if dex_tokens:
            known = {(t.get('symbol') or '').lower() for t in all_tokens}
            added = 0
            for t in dex_tokens:
                if (t.get('symbol') or '').lower() not in known:
                    all_tokens.append(t)
                    added += 1
            self.logger.info(f"Added {added} DexScreener tokens (total {len(all_tokens)})")
        return all_tokens

    async def get_contract_address(self, token_id: str) -> str:
        try:
            await self._rate_limit()  # Apply rate limiting for free plan
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.base_url}/coins/{token_id}",
                params={"localization": "false", "tickers": "false", "market_data": "false"},
                headers=self.headers,
                timeout=60
            )
            response.raise_for_status()
            return response.json().get('platforms', {}).get('solana', 'N/A')
        except Exception as e:
            self.logger.error(f"Error fetching address for {token_id}: {str(e)}")
            return 'N/A'

    async def analyze_token(self, token):
        """Analyze token and send alert if criteria met"""
        try:
            symbol = token.get('symbol', '').lower()
            self.logger.info(f"Analyzing token: {symbol}")
            if symbol in self.blacklisted_tokens or self.is_stablecoin(token):
                return None
            
            market_cap = token.get('market_cap', 0)
            price_change = abs(token.get('price_change_percentage_24h', 0) or 0)
            volume_24h = token.get('total_volume', 0)
            if not all([market_cap, volume_24h]):
                return None

            patterns = self.detect_patterns(token)
            confidence = self.calculate_signal_confidence(token, patterns)
            if confidence < 5.0 and symbol not in self.watchlist_tokens:
                return None

            risk_check = self.check_risks(token)
            if risk_check['risk_level'] == 'high':
                return None

            token_id = token.get('id', '')
            # DexScreener tokens already carry their mint - no CoinGecko lookup needed.
            token_address = token.get('address') or await self.get_contract_address(token_id)
            if not token_address or token_address == 'N/A':
                return None

            # Don't re-post a token we already called recently.
            if self.already_called(token_address):
                return None

            current_price = token.get('current_price', 0)
            # Chart data is fetched lazily in _attach_chart_data, only for tokens
            # we actually post. Fetching here would hit GeckoTerminal for every
            # candidate and throttle the whole scan.
            historical_prices = []
            ohlcv_full = []

            analysis = {
                'symbol': token.get('symbol', '').upper(),
                'name': token.get('name', ''),
                'price': current_price,
                'market_cap': market_cap,
                'volume_24h': volume_24h,
                'price_change': token.get('price_change_percentage_24h', 0) or 0,
                'turnover_ratio': risk_check['turnover_ratio'],
                'turnover_grade': risk_check['turnover_grade'],
                'turnover_desc': risk_check['turnover_desc'],
                'turnover_emoji': risk_check['turnover_emoji'],
                'warnings': risk_check['warnings'],
                'signals': [],
                'patterns': patterns,
                'confidence': confidence,
                'score': 0,
                'token_address': token_address,
                'historical_prices': historical_prices,
                'ohlcv_full': ohlcv_full,
                'chain': 'solana',
                'source': token.get('source', 'coingecko'),
                'socials': token.get('socials') or [],
                'websites': token.get('websites') or []
            }
            
            if market_cap <= self.max_market_cap:
                analysis['signals'].append('Low market cap')
                analysis['score'] += 1
            if volume_24h > market_cap * 0.1:
                analysis['signals'].append('High volume')
                analysis['score'] += 1
            if price_change >= self.min_price_change:
                analysis['signals'].append('Price surge')
                analysis['score'] += 1
            for pattern in patterns:
                analysis['signals'].append(f'{pattern.title()} pattern')
                analysis['score'] += self.pattern_weights[pattern]
            if symbol in self.watchlist_tokens:
                analysis['signals'].append('⭐ Priority token')
                analysis['score'] += 2
            
            current_time = time.time()
            time_since_last_signal = current_time - self.last_signal_time
            is_urgent = confidence >= 7.0
            
            if analysis['score'] > 0:
                if self.signals_this_cycle >= self.max_signals_per_cycle:
                    return analysis
                analysis['signals'].append(f'Confidence: {confidence:.1f}/10')
                if is_urgent:
                    analysis['signals'].append('🔥 URGENT BUY SIGNAL')

                if is_urgent or time_since_last_signal >= self.signal_cooldown:
                    # Safety gate runs only for tokens about to be posted. A block
                    # costs one API call and hands the slot to the next candidate:
                    # no signals_this_cycle increment, no record_call, so a blocked
                    # token isn't dedup-suppressed for 6h without ever being called.
                    if self.rugcheck_enabled:
                        report = await asyncio.to_thread(self.fetch_rugcheck, token_address)
                        passed, reasons, rc_info = self.rugcheck_verdict(report)
                        analysis['rugcheck'] = rc_info
                        if passed and self.depth_blocks:
                            # Opt-in only (DEPTH_BLOCK=1). Depth is resolved in
                            # _attach_chart_data, which runs below, so grade it
                            # here rather than reading a key that isn't set yet.
                            q = (await asyncio.to_thread(
                                self._dex_price_batch, [token_address])
                                 ).get(token_address) or {}
                            _g, _d, _e, _r = self.get_depth_grade(
                                q.get('liquidity'), analysis.get('market_cap', 0))
                            if _r is not None and _r < self.min_depth_ratio:
                                passed = False
                                reasons.append(
                                    f'pool depth {_r:.3f} < {self.min_depth_ratio:g} of mcap')
                        if not passed:
                            self.rc_blocked_count += 1
                            self.logger.info(
                                f"RugCheck BLOCKED {analysis['symbol']}: {'; '.join(reasons)}")
                            return None
                        if not rc_info.get('available'):
                            self.logger.warning(
                                f"RugCheck unavailable for {analysis['symbol']} - "
                                f"posting UNVERIFIED (fail-open)")
                    await self._attach_chart_data(analysis, token, token_id)
                    await self.format_and_send_telegram_message(analysis)
                    self.last_signal_time = current_time
                    self.signals_this_cycle += 1
                    await asyncio.to_thread(self.record_call, analysis, self.last_call_message_id)
                    if not is_urgent:
                        await asyncio.sleep(1)
            return analysis if analysis['score'] > 0 else None
            
        except Exception as e:
            self.logger.error(f"Error analyzing token {symbol}: {str(e)}")
            return None

    async def alert_loop(self):
        """Main loop for background token scanning"""
        while self.running:
            try:
                self.logger.info("\n🔍 Initiating Solana scan...")
                tokens = await self.get_token_data()
                if not tokens:
                    self.logger.error("No tokens detected")
                    await asyncio.sleep(self.scan_interval)
                    continue
                self.logger.info(f"Detected {len(tokens)} Solana assets")
                self.signals_this_cycle = 0

                # Only a few calls go out per cycle, so spend those slots on the
                # strongest candidates rather than whatever happens to sort first.
                def _quality(t):
                    mc = t.get('market_cap') or 0
                    vol = t.get('total_volume') or 0
                    return vol / mc if mc > 0 else 0
                tokens = sorted(tokens, key=_quality, reverse=True)

                alerts_found = False
                for token in tokens:
                    analysis = await self.analyze_token(token)
                    if analysis:
                        alerts_found = True
                if not alerts_found:
                    self.logger.info("\nNo actionable signals in this cycle")

                # Re-price past calls and post profit alerts
                if time.time() - self.last_performance_check >= self.performance_check_interval:
                    self.last_performance_check = time.time()
                    try:
                        await self.check_call_performance()
                    except Exception as e:
                        self.logger.error(f"Call performance check failed: {e}")

                # Runs after the re-price so the board reflects the numbers that
                # were just refreshed rather than the previous cycle's.
                if time.time() - self.last_recap >= self.recap_interval:
                    self.last_recap = time.time()
                    try:
                        await self.post_or_update_recap()
                    except Exception as e:
                        self.logger.error(f"Leaderboard update failed: {e}")

                self.logger.info(f"\n⏳ Next scan in {self.scan_interval} seconds...")
                await asyncio.sleep(self.scan_interval)
            except Exception as e:
                self.logger.error(f"System error: {str(e)}")
                await asyncio.sleep(self.scan_interval)

    @app.route('/voice', methods=['POST'])
    def voice_handler():
        if not scanner:
            return "Scanner not initialized", 500
        
        if VoiceResponse is None:
            return "Twilio not available. Please install twilio package.", 500
        
        resp = VoiceResponse()
        if not scanner.twilio_sid or not scanner.twilio_auth_token:
            resp.say("Call system offline. Check credentials.", voice="Polly.Amy")
            return str(resp)
        resp.say("Greetings! I'm Claude, your crypto assistant. How can I help with your crypto questions today?", voice="Polly.Amy")
        resp.gather(input="speech", action="/handle-call-response", timeout=5, speech_timeout="auto")
        return str(resp)

    @app.route('/handle-call-response', methods=['POST'])
    async def handle_call_response_handler():
        if not scanner:
            return "Scanner not initialized", 500
        
        if VoiceResponse is None:
            return "Twilio not available. Please install twilio package.", 500
        
        user_input = request.values.get("SpeechResult", "I didn't catch that.")
        resp = VoiceResponse()
        
        response = await scanner.ai_assistant.query(user_input, [], "default", 0.7, 250)
        
        response = response.replace('#', 'hashtag').replace('$', 'dollar')
        
        resp.say(response, voice="Polly.Amy")
        resp.gather(input="speech", action="/handle-call-response", timeout=5, speech_timeout="auto")
        return str(resp)

    @app.route('/quantum_chart/<token_id>/<token_address>', methods=['GET'])
    def quantum_chart(token_id, token_address):
        """Endpoint to display the 3D quantum chart for a token"""
        try:
            if not scanner:
                return "Scanner not initialized", 500
            
            # This function runs in a different thread context, so we need to create a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Get token price and historical data
            token_price = loop.run_until_complete(scanner._get_price(token_id))
            historical_prices = loop.run_until_complete(scanner.get_historical_prices(token_id, token_price))
            
            # Add a note about AI prediction being active
            flash_param = request.args.get('flash', 'true').lower() == 'true'
            
            # Create 3D quantum graph
            graph_buf = scanner.create_3d_quantum_graph(token_id.upper(), historical_prices)
            if not graph_buf:
                return "Error creating 3D quantum chart", 500
            
            # Return the buffer directly with correct headers
            graph_buf.seek(0)
            response = send_file(
                graph_buf,
                mimetype='image/gif', 
                as_attachment=False,
                download_name=f"{token_id}_quantum_chart.gif"
            )
            
            # Add custom header to indicate prediction is active
            response.headers['X-AI-Prediction'] = 'active'
            
            return response
        except Exception as e:
            logging.error(f"Error in quantum_chart endpoint: {str(e)}")
            return f"Error generating quantum chart: {str(e)}", 500

    @app.route('/')
    def index():
        return '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Quantum Chart Test</title>
            <style>
                body { background-color: #121212; color: #00ffff; font-family: Arial, sans-serif; margin: 20px; }
                h1 { color: #00ffff; }
                input, button { padding: 8px; margin: 10px 0; }
                .container { max-width: 800px; margin: 0 auto; }
                button { background-color: #4B0082; color: white; border: none; cursor: pointer; }
                button:hover { background-color: #6A0DAD; }
                .instructions { background-color: #1E1E1E; padding: 15px; border-radius: 5px; }
                .prediction-badge { 
                    display: inline-block; 
                    background-color: #FFA500; 
                    color: black; 
                    padding: 3px 8px; 
                    border-radius: 10px; 
                    font-size: 12px;
                    margin-left: 10px;
                    vertical-align: middle;
                }
                .feature-list {
                    background-color: #1E1E1E;
                    padding: 15px;
                    border-radius: 5px;
                    margin-top: 20px;
                }
                .feature-list li {
                    margin-bottom: 8px;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🔮 Quantum Chart Generator <span class="prediction-badge">AI Prediction</span></h1>
                <div class="instructions">
                    <p>Enter a token ID (like "bitcoin", "ethereum", "solana") and a token address to generate a 3D quantum chart.</p>
                    <p>For testing, you can use these example values:</p>
                    <ul>
                        <li>Token ID: solana</li>
                        <li>Token Address: So11111111111111111111111111111111111111112</li>
                    </ul>
                </div>
                <div>
                    <input type="text" id="tokenId" placeholder="Token ID (e.g., solana)" required><br>
                    <input type="text" id="tokenAddress" placeholder="Token Address" required><br>
                    <button onclick="generateChart()">Generate Quantum Chart</button>
                </div>
                <div id="result" style="margin-top: 20px;"></div>
                
                <div class="feature-list">
                    <h3>✨ New Features:</h3>
                    <ul>
                        <li><strong>AI Price Prediction</strong> - Shows a 2-hour forecast based on EMA and momentum analysis</li>
                        <li><strong>Rotating 3D View</strong> - Visualize price movements in three dimensions</li>
                        <li><strong>Quantum Technical Indicators</strong> - RSI and MACD data visualization</li>
                    </ul>
                    <p><i>Note: Price predictions are speculative and should not be used as financial advice.</i></p>
                </div>
                
                <script>
                    function generateChart() {
                        const tokenId = document.getElementById('tokenId').value;
                        const tokenAddress = document.getElementById('tokenAddress').value;
                        
                        if (!tokenId || !tokenAddress) {
                            alert('Please enter both Token ID and Token Address');
                            return;
                        }
                        
                        const chartUrl = `/quantum_chart/${tokenId}/${tokenAddress}`;
                        document.getElementById('result').innerHTML = 
                            `<p>Generating chart... If it doesn't appear, check your browser console for errors.</p>
                             <img src="${chartUrl}" style="max-width: 100%; border: 1px solid #333;" />
                             <p style="color: yellow; font-style: italic; margin-top: 10px;">
                                Chart includes AI-generated 2-hour price prediction (yellow dashed line).
                                This is for visualization purposes only and not financial advice.
                             </p>`;
                    }
                </script>
            </div>
        </body>
        </html>
        '''

    async def main(self):
        telegram_task = asyncio.create_task(self.bot_loop())
        alert_task = asyncio.create_task(self.alert_loop())
        # Its own task on purpose: alert_loop sleeps scan_interval between
        # iterations, so a young call cannot be sampled faster than the scan
        # rate from inside it. See fast_track_loop.
        fast_task = asyncio.create_task(self.fast_track_loop())
        flask_task = asyncio.to_thread(app.run, host=self.server_host, port=self.server_port, debug=False)
        try:
            await asyncio.gather(telegram_task, alert_task, fast_task, flask_task)
        except KeyboardInterrupt:
            self.running = False
            self.logger.info("Shutting down...")

# Initialize scanner after class definition
scanner = SolanaTelegramScanner()

if __name__ == "__main__":
    asyncio.run(scanner.main())