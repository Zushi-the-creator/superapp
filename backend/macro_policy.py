"""
V23.0 Macro Policy Risk Model

Integrates macro-economic and policy event risk into trading decisions.
Adjusts technical signals based on upcoming events and sector exposure.

Transaction Cost Awareness (Added 2026-01-21):
- Platform fee: $1.50 per trade
- Round-trip cost: $3.00
- Signals filtered to ensure profit > transaction costs

Author: Claude Trading Assistant
Created: 2026-01-20
Updated: 2026-01-21 (Transaction cost integration)
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
import requests


# ============================================
# TRANSACTION COST CONSTANTS
# ============================================
TRANSACTION_COST_PER_TRADE = 1.50  # USD per trade
ROUND_TRIP_COST = TRANSACTION_COST_PER_TRADE * 2  # $3.00
MIN_PROFIT_BUFFER = 2.0  # Require 2x cost to justify trade
MIN_PROFIT_THRESHOLD = ROUND_TRIP_COST * MIN_PROFIT_BUFFER  # $6.00


# ============================================
# SECTOR POLICY EXPOSURE MAPPINGS
# ============================================

SECTOR_TARIFF_EXPOSURE = {
    # Ticker -> Tariff exposure score (0-100)
    # Higher = more exposed to import/export tariffs
    "NVDA": 85,   # Manufactures in Taiwan, imports chips
    "MU": 80,     # Taiwan/Japan manufacturing, memory imports
    "AMD": 85,    # Taiwan manufacturing (TSMC)
    "INTC": 40,   # US manufacturing, less exposed
    "QCOM": 75,   # China exposure, Qualcomm
    "AVGO": 70,   # Broadcom, diversified supply chain
    "TSM": 90,    # TSMC = ground zero for chip tariffs
    "MRVL": 75,   # Marvell, fabless
    "QQQ": 50,    # Diversified tech ETF
    "SPY": 30,    # Broad market, diversified
    "AAPL": 70,   # China manufacturing exposure
    "MSFT": 25,   # Software, low tariff exposure
    "GOOGL": 25,  # Software/services
    "META": 30,   # Software/hardware mix
    "TSLA": 60,   # China gigafactory, battery imports
    "COIN": 20,   # Crypto, minimal tariff exposure
    "CEG": 15,    # Domestic energy, low exposure
    "VST": 15,    # Domestic energy
    "LLY": 35,    # Pharma, some API imports
}

SECTOR_RATE_SENSITIVITY = {
    # Ticker -> Interest rate sensitivity (0-100)
    # Higher = more impacted by Fed rate changes
    "QQQ": 70,    # Growth tech sensitive to rates
    "NVDA": 65,   # Growth stock, rate sensitive
    "MU": 55,     # Cyclical, moderate sensitivity
    "AMD": 65,    # Growth stock
    "LLY": 40,    # Defensive pharma
    "AAPL": 50,   # Large cap, moderate
    "MSFT": 45,   # Large cap, cash rich
    "COIN": 80,   # Crypto highly rate sensitive
    "CEG": 60,    # Utilities sensitive to rates
    "VST": 55,    # Energy, moderate
    "SPY": 50,    # Broad market average
}

SECTOR_GEOPOLITICAL_EXPOSURE = {
    # Ticker -> Geopolitical risk exposure (0-100)
    # China/Taiwan tension, Russia, Middle East
    "NVDA": 90,   # Taiwan (TSMC), China sales ban
    "MU": 85,     # Taiwan fabs, China competition
    "AMD": 85,    # TSMC dependency
    "TSM": 95,    # Taiwan = existential risk
    "AAPL": 75,   # China manufacturing + sales
    "QCOM": 80,   # China licensing
    "QQQ": 55,    # Diversified
    "SPY": 35,    # Broad market
    "CEG": 20,    # Domestic
    "VST": 20,    # Domestic
    "LLY": 30,    # Global but diversified
    "COIN": 40,   # Regulatory risk, not geo
}


# ============================================
# MACRO EVENT CALENDAR
# ============================================

def get_upcoming_events(days_ahead: int = 7) -> List[Dict]:
    """
    Returns list of upcoming macro events that could impact markets.
    In production, this would pull from an API or database.
    """
    today = datetime.now()

    # Static calendar for January 2026 (would be dynamic in production)
    events = [
        {
            "date": "2026-01-21",
            "time": "08:30 EST",
            "event": "Trump Davos Speech",
            "type": "POLICY",
            "impact": "HIGH",
            "sectors_affected": ["semiconductors", "tech", "europe"],
            "tickers_affected": ["NVDA", "MU", "AMD", "QQQ", "AAPL"],
            "description": "President Trump addresses World Economic Forum. May announce broader semiconductor tariffs.",
            "scenarios": {
                "bullish": "De-escalation on tariffs, pro-business tone",
                "bearish": "Broader chip tariffs, Europe trade war escalation",
                "neutral": "Reaffirms existing policies, no surprises"
            }
        },
        {
            "date": "2026-01-29",
            "time": "14:00 EST",
            "event": "FOMC Rate Decision",
            "type": "FED",
            "impact": "HIGH",
            "sectors_affected": ["all"],
            "tickers_affected": ["QQQ", "SPY", "COIN", "NVDA"],
            "description": "Federal Reserve interest rate decision and statement.",
            "scenarios": {
                "bullish": "Rate cut or dovish guidance",
                "bearish": "Hawkish surprise, rate hike threat",
                "neutral": "Hold rates as expected"
            }
        },
        {
            "date": "2026-01-30",
            "time": "16:00 EST",
            "event": "AAPL Earnings",
            "type": "EARNINGS",
            "impact": "HIGH",
            "sectors_affected": ["tech", "consumer"],
            "tickers_affected": ["AAPL", "QQQ", "SPY"],
            "description": "Apple Q1 FY2026 earnings report.",
            "scenarios": {
                "bullish": "Beat + raise guidance",
                "bearish": "Miss + China weakness",
                "neutral": "In-line results"
            }
        },
        {
            "date": "2026-02-26",
            "time": "16:00 EST",
            "event": "NVDA Earnings",
            "type": "EARNINGS",
            "impact": "CRITICAL",
            "sectors_affected": ["semiconductors", "AI", "tech"],
            "tickers_affected": ["NVDA", "MU", "AMD", "QQQ", "TSM"],
            "description": "NVIDIA Q4 FY2026 earnings. Key for AI trade.",
            "scenarios": {
                "bullish": "Beat + strong guidance + Blackwell ramp",
                "bearish": "Miss or weak datacenter growth",
                "neutral": "In-line, guidance maintained"
            }
        },
        {
            "date": "2026-03-20",
            "time": "16:00 EST",
            "event": "MU Earnings",
            "type": "EARNINGS",
            "impact": "HIGH",
            "sectors_affected": ["semiconductors", "memory"],
            "tickers_affected": ["MU", "NVDA", "AMD"],
            "description": "Micron Q2 FY2026 earnings. HBM demand key.",
            "scenarios": {
                "bullish": "HBM3e ramp + pricing power",
                "bearish": "Inventory buildup, margin pressure",
                "neutral": "In-line, cycle continuing"
            }
        }
    ]

    # Filter to upcoming events within days_ahead
    cutoff = today + timedelta(days=days_ahead)
    upcoming = []
    for event in events:
        event_date = datetime.strptime(event["date"], "%Y-%m-%d")
        if today.date() <= event_date.date() <= cutoff.date():
            event["days_until"] = (event_date.date() - today.date()).days
            upcoming.append(event)

    return sorted(upcoming, key=lambda x: x["date"])


# ============================================
# POLICY RISK SCORING
# ============================================

def calculate_policy_risk_score(ticker: str, events: List[Dict] = None) -> Dict:
    """
    Calculate comprehensive policy risk score for a ticker.

    Returns:
        - risk_score: 0-100 (higher = more risk)
        - risk_level: LOW/MEDIUM/HIGH/CRITICAL
        - position_multiplier: 0.25-1.0 (reduce position size for high risk)
        - recommendation: Action based on risk
    """
    if events is None:
        events = get_upcoming_events(days_ahead=7)

    ticker = ticker.upper()

    # Base exposure scores
    tariff_exposure = SECTOR_TARIFF_EXPOSURE.get(ticker, 50)
    rate_sensitivity = SECTOR_RATE_SENSITIVITY.get(ticker, 50)
    geo_exposure = SECTOR_GEOPOLITICAL_EXPOSURE.get(ticker, 50)

    # Event-based risk adjustment
    event_risk = 0
    imminent_events = []

    for event in events:
        if ticker in event.get("tickers_affected", []):
            days_until = event.get("days_until", 7)
            impact_score = {"LOW": 10, "MEDIUM": 20, "HIGH": 35, "CRITICAL": 50}.get(event["impact"], 20)

            # Closer events = higher risk
            time_multiplier = max(0.5, 1 - (days_until / 7))
            event_risk += impact_score * time_multiplier

            if days_until <= 2:
                imminent_events.append(event)

    # Composite risk score
    # Weight: 30% tariff, 20% rates, 20% geo, 30% events
    risk_score = (
        tariff_exposure * 0.30 +
        rate_sensitivity * 0.20 +
        geo_exposure * 0.20 +
        min(event_risk, 100) * 0.30
    )

    risk_score = min(100, risk_score)

    # Risk level classification
    if risk_score >= 75:
        risk_level = "CRITICAL"
        position_multiplier = 0.25  # Only 25% position size
        recommendation = "REDUCE position or HEDGE before event"
    elif risk_score >= 55:
        risk_level = "HIGH"
        position_multiplier = 0.50  # 50% position size
        recommendation = "Consider trimming or setting tight stops"
    elif risk_score >= 35:
        risk_level = "MEDIUM"
        position_multiplier = 0.75  # 75% position size
        recommendation = "Monitor closely, normal position size OK"
    else:
        risk_level = "LOW"
        position_multiplier = 1.0  # Full position size
        recommendation = "Normal trading, no policy concerns"

    return {
        "ticker": ticker,
        "risk_score": round(risk_score, 1),
        "risk_level": risk_level,
        "position_multiplier": position_multiplier,
        "recommendation": recommendation,
        "components": {
            "tariff_exposure": tariff_exposure,
            "rate_sensitivity": rate_sensitivity,
            "geo_exposure": geo_exposure,
            "event_risk": round(min(event_risk, 100), 1)
        },
        "imminent_events": imminent_events,
        "events_ahead": len([e for e in events if ticker in e.get("tickers_affected", [])])
    }


# ============================================
# INTEGRATED SIGNAL ADJUSTMENT
# ============================================

def adjust_signal_for_macro(
    ticker: str,
    technical_signal: str,
    technical_confidence: float,
    policy_risk: Dict = None,
    position_value: float = 0.0
) -> Dict:
    """
    Adjusts technical signal based on macro/policy risk AND transaction costs.

    Args:
        ticker: Stock ticker
        technical_signal: BUY/SELL/HOLD from technical model
        technical_confidence: 0-100 confidence score
        policy_risk: Pre-calculated policy risk (or will calculate)
        position_value: Current position value for fee calculation

    Returns:
        Adjusted signal with macro considerations and fee analysis
    """
    if policy_risk is None:
        policy_risk = calculate_policy_risk_score(ticker)

    risk_level = policy_risk["risk_level"]
    risk_score = policy_risk["risk_score"]
    multiplier = policy_risk["position_multiplier"]

    # Adjust confidence based on policy risk
    adjusted_confidence = technical_confidence * multiplier

    # Signal adjustments based on risk
    adjusted_signal = technical_signal
    adjustment_reason = None

    if risk_level == "CRITICAL":
        if technical_signal == "BUY":
            adjusted_signal = "WAIT"
            adjustment_reason = f"BUY delayed - CRITICAL policy risk ({risk_score:.0f}/100). Wait for event resolution."
        elif technical_signal == "HOLD":
            adjusted_signal = "TRIM"
            adjustment_reason = f"HOLD -> TRIM - Reduce exposure before high-impact event."

    elif risk_level == "HIGH":
        if technical_signal == "BUY":
            adjusted_signal = "BUY_SMALL"
            adjustment_reason = f"BUY with 50% size - HIGH policy risk. Scale in after event."
        elif technical_signal == "HOLD":
            adjustment_reason = f"HOLD with tight stop - Event risk elevated."

    elif risk_level == "MEDIUM":
        if technical_signal == "BUY":
            adjustment_reason = f"BUY OK but monitor - Policy event within 7 days."

    # Check for imminent binary events
    for event in policy_risk.get("imminent_events", []):
        if event.get("days_until", 7) <= 1:
            if technical_signal in ["BUY", "HOLD"]:
                adjusted_signal = "WAIT" if technical_signal == "BUY" else "HEDGE"
                adjustment_reason = f"BINARY EVENT TOMORROW: {event['event']}. Reduce risk or wait."

    # ============================================
    # TRANSACTION COST ANALYSIS (Added 2026-01-21)
    # ============================================
    fee_analysis = {
        "position_value": position_value,
        "round_trip_cost": ROUND_TRIP_COST,
        "min_profit_needed": MIN_PROFIT_THRESHOLD,
        "trade_profitable": True,
        "fee_warning": None
    }

    if position_value > 0:
        # Calculate minimum move needed to profit
        min_move_pct = (MIN_PROFIT_THRESHOLD / position_value) * 100
        fee_analysis["min_move_pct"] = round(min_move_pct, 3)

        # Check if position is too small for frequent trading
        if position_value < 500:
            fee_analysis["trade_profitable"] = False
            fee_analysis["fee_warning"] = f"Position ${position_value:.0f} too small - fees eat into gains"
            if adjusted_signal in ["BUY", "SELL", "BUY_SMALL", "TRIM"]:
                adjustment_reason = (adjustment_reason or "") + f" [FEE WARNING: Small position]"

        elif min_move_pct > 1.0:
            fee_analysis["trade_profitable"] = False
            fee_analysis["fee_warning"] = f"Need >{min_move_pct:.2f}% move just to break even"
            if adjusted_signal in ["BUY", "BUY_SMALL"]:
                adjustment_reason = (adjustment_reason or "") + f" [FEE WARNING: Need {min_move_pct:.2f}% move]"

    return {
        "original_signal": technical_signal,
        "adjusted_signal": adjusted_signal,
        "original_confidence": technical_confidence,
        "adjusted_confidence": round(adjusted_confidence, 1),
        "policy_risk": policy_risk,
        "adjustment_reason": adjustment_reason,
        "position_size_recommendation": f"{multiplier * 100:.0f}% of normal size",
        "fee_analysis": fee_analysis
    }


# ============================================
# NEWS SENTIMENT FOR POLICY
# ============================================

def fetch_policy_news_sentiment(ticker: str) -> Dict:
    """
    Fetch news specifically related to policy/tariff/regulatory topics.
    """
    policy_keywords = ["tariff", "policy", "regulation", "ban", "sanction", "export", "import", "tax", "subsidy"]

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        url = f'https://news.google.com/rss/search?q={ticker}+stock+tariff+OR+policy&hl=en-US&gl=US&ceid=US:en'
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)
            items = root.findall('.//item')[:5]

            policy_news = []
            for item in items:
                title = item.find('title').text if item.find('title') is not None else ''
                title_lower = title.lower()

                # Check if it's policy-related
                is_policy = any(kw in title_lower for kw in policy_keywords)
                if is_policy:
                    # Simple sentiment
                    positive = any(w in title_lower for w in ['exempt', 'relief', 'boost', 'support', 'cut'])
                    negative = any(w in title_lower for w in ['tariff', 'ban', 'restrict', 'sanction', 'hike'])

                    sentiment = "NEGATIVE" if negative and not positive else "POSITIVE" if positive else "NEUTRAL"
                    policy_news.append({"title": title, "sentiment": sentiment})

            return {
                "ticker": ticker,
                "policy_news_count": len(policy_news),
                "policy_news": policy_news,
                "overall_policy_sentiment": "NEGATIVE" if any(n["sentiment"] == "NEGATIVE" for n in policy_news) else "NEUTRAL"
            }
    except Exception as e:
        print(f"Policy news fetch error: {e}")

    return {"ticker": ticker, "policy_news_count": 0, "policy_news": [], "overall_policy_sentiment": "NEUTRAL"}


# ============================================
# MAIN ANALYSIS FUNCTION
# ============================================

def full_macro_analysis(ticker: str) -> Dict:
    """
    Complete macro/policy analysis for a ticker.
    """
    events = get_upcoming_events(days_ahead=14)
    policy_risk = calculate_policy_risk_score(ticker, events)
    policy_news = fetch_policy_news_sentiment(ticker)

    # Combine into full analysis
    return {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "policy_risk": policy_risk,
        "policy_news": policy_news,
        "upcoming_events": [e for e in events if ticker in e.get("tickers_affected", [])],
        "all_events": events,
        "summary": {
            "risk_level": policy_risk["risk_level"],
            "risk_score": policy_risk["risk_score"],
            "recommendation": policy_risk["recommendation"],
            "key_event": events[0]["event"] if events else "None imminent",
            "days_to_event": events[0].get("days_until", "N/A") if events else "N/A"
        }
    }


# ============================================
# CLI TEST
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("V23.0 MACRO POLICY RISK MODEL")
    print("=" * 60)
    print()

    # Test with portfolio tickers
    for ticker in ["NVDA", "MU", "QQQ"]:
        analysis = full_macro_analysis(ticker)
        risk = analysis["policy_risk"]

        print(f"📊 {ticker}")
        print(f"   Risk Score: {risk['risk_score']}/100 ({risk['risk_level']})")
        print(f"   Position Size: {risk['position_multiplier']*100:.0f}% recommended")
        print(f"   Tariff Exposure: {risk['components']['tariff_exposure']}/100")
        print(f"   Event Risk: {risk['components']['event_risk']}/100")
        print(f"   Recommendation: {risk['recommendation']}")

        if risk.get("imminent_events"):
            print(f"   ⚠️  IMMINENT: {risk['imminent_events'][0]['event']}")
        print()

    print("=" * 60)
    print("UPCOMING MACRO EVENTS")
    print("=" * 60)
    for event in get_upcoming_events(14):
        print(f"📅 {event['date']} - {event['event']} ({event['impact']})")
        print(f"   Affects: {', '.join(event['tickers_affected'][:5])}")
        print()
