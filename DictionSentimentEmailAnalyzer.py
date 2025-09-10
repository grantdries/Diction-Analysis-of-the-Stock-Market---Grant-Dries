# ---------------------------------------------------------------------------------
# Weekly Sentiment Scraper (Finviz-based) — Fully Commented Edition
# ---------------------------------------------------------------------------------
# Purpose
#   • Collect recent headlines for a large list of tickers (from finviz.csv) using the
#     Finviz "quote" page.
#   • Score each headline two ways: (1) simple keyword lookup and (2) VADER sentiment.
#   • Pull price snapshots around the article date using yfinance (daily bars).
#   • Save a detailed per-article CSV and a per-ticker Summary sheet to Excel.
#   • Email the Excel report via Gmail SMTP.
#
# Important Behaviors / Notes
#   • Finviz scraping is rate-limited by design via an explicit 20-second delay per ticker.
#     (This keeps us from getting blocked. Do not reduce this without testing.)
#   • "+1h" and "+4h" prices are approximations when using daily bars — they map to the next
#     rows in the daily series, not true one/four hour intraday snapshots.
#   • The keyword lookup uses sets of 100 positive and 100 negative tokens below. Only single words are matched (tokenized by word characters). Phrase matching (e.g., "beats estimates") is not implemented.

import pandas as pd
import datetime
from dateutil import parser
from collections import defaultdict
import os
import requests
from datetime import datetime, timedelta
import yfinance as yf
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
import re
import pytz
from tqdm import tqdm
import random
import time
import asyncio
import aiohttp
import feedparser
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from bs4 import BeautifulSoup

# === VADER Setup ===
# VADER (Valence Aware Dictionary and sEntiment Reasoner): a lexicon- and rule-based
# sentiment model optimized for short text (e.g., headlines). Outputs positive/neutral/
# negative proportions and a compound score in [-1, 1]. The following block ensures the
# VADER lexicon is available locally (downloaded on first run).
try:
    nltk.data.find('sentiment/vader_lexicon.zip')
except LookupError:
    nltk.download('vader_lexicon')

# === Load tickers from finviz.csv ===
# We expect finviz.csv to include a column named "Ticker" with symbols. We normalize to
# uppercase strings, strip whitespace, drop NA, and keep uniques.
finviz_df = pd.read_csv('finviz.csv')
HARDCODED_TICKERS = finviz_df['Ticker'].astype(str).str.upper().str.strip().dropna().unique().tolist()
print(f"✅ Loaded {len(HARDCODED_TICKERS)} tickers from finviz.csv")

# === Email Config ===
# Loads EMAIL_ADDRESS, EMAIL_PASSWORD, EMAIL_RECEIVER from .env and defines SMTP params.
load_dotenv()
EMAIL_SENDER = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVER = os.getenv('EMAIL_RECEIVER')
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

# === TIMEZONE ===
# Date/time calculations use US/Eastern (ET). Finviz "Today" timestamps are converted to
# timezone-aware ET datetimes for window comparisons. Some operations use naive datetimes
# for simplicity in a weekly batch run.
# noqa: E402 (placement is intentional for readability)
eastern_tz = pytz.timezone('US/Eastern')

# === SENTIMENT LOOKUP ===
# Populated sets of 100 positive and 100 negative tokens for the keyword-based lookup.
# The scoring logic simply checks membership: if a token is present in the positive set,
# it contributes +1; if in the negative set, it contributes -1. Ambiguity is flagged if
# both lists get hits for the same headline text.

positive_keywords = {
    "beat", "beats", "beating", "exceed", "exceeds", "exceeded", "exceeding", "surge", "surges", "surged", "soar", "soars", "soared", "rally", "rallies", "rallied", "jump", "jumps", "jumped", "spike", "spikes", "spiked", "pop", "pops", "popped", "gain", "gains", "gained", "advance", "advances", "advanced", "rise", "rises", "rose", "upbeat", "bull", "bullish", "optimism", "optimistic", "confidence", "confident", "strong", "strength", "robust", "resilient", "resilience", "record", "high", "highs", "profit", "profits", "profitable", "profitability", "margin", "margins", "expand", "expands", "expanded", "expanding", "growth", "growing", "accelerate", "accelerates", "accelerated", "accelerating", "outperform", "outperforms", "outperformed", "outperforming", "upgrade", "upgrades", "upgraded", "upgrading", "overweight", "buy", "buying", "accumulate", "accumulating", "initiate", "initiates", "initiated", "initiating", "guidance", "raise", "raises", "raised", "raising", "hike", "hikes", "hiked", "dividend", "dividends", "increase", "increases", "increased", "increasing", "buyback", "buybacks", "repurchase", "repurchases"
}

negative_keywords = {
    "miss", "misses", "missed", "missing", "lag", "lags", "lagged", "lagging", "plunge", "plunges", "plunged", "plunging", "tumble", "tumbles", "tumbled", "tumbling", "drop", "drops", "dropped", "dropping", "fall", "falls", "fell", "falling", "slump", "slumps", "slumped", "slumping", "slide", "slides", "slid", "sliding", "decline", "declines", "declined", "declining", "selloff", "selloffs", "weak", "weakness", "soft", "softness", "bear", "bearish", "pessimism", "pessimistic", "fear", "loss", "losses", "unprofitable", "compression", "compress", "compressed", "cut", "cuts", "cutting", "lower", "lowers", "lowered", "lowering", "reduce", "reduces", "reduced", "reducing", "downgrade", "downgrades", "downgraded", "downgrading", "underperform", "underperforms", "underperformed", "underperforming", "warning", "recall", "recalls", "recalled", "restructuring", "layoff", "layoffs", "furlough", "furloughs", "bankruptcy", "insolvency", "default", "defaults", "defaulted", "dilution", "dilutive", "lawsuit", "lawsuits", "probe", "probes", "investigation", "investigations", "fraud", "scandal", "resign", "resigns", "resigned", "resignation"
}

# Create the VADER analyzer once to reuse for all sentences.
sia = SentimentIntensityAnalyzer()


def scrape_article_text(url):
    """
    Best-effort page text fetcher for a given article URL.
    Returns plain text extracted from <p> tags (joined). If anything fails, returns "".
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return ""
        soup = BeautifulSoup(res.text, 'html.parser')
        paragraphs = soup.find_all('p')
        text = ' '.join(p.text for p in paragraphs)
        return text.strip()
    except:
        return ""


def score_lookup(text):
    """
    Simple keyword-based sentiment:
      • Tokenize by word characters (\w+) and lowercase.
      • Count hits in positive_keywords and negative_keywords.
      • Score is +1 / -1 / 0 based on which side has more hits.
      • Also return the matched tokens (comma-separated) and an ambiguity flag.
    """
    tokens = re.findall(r"\w+", text.lower())
    pos_matches = [w for w in tokens if w in positive_keywords]
    neg_matches = [w for w in tokens if w in negative_keywords]
    score = 1 if len(pos_matches) > len(neg_matches) else -1 if len(neg_matches) > len(pos_matches) else 0
    ambiguous = bool(pos_matches and neg_matches)
    return score, ', '.join(pos_matches), ', '.join(neg_matches), ambiguous


def classify_sentiment(text):
    """
    VADER-based classification with majority vote across sentences:
      • Split on . ! ?
      • For each sentence, get VADER compound.
      • Tally counts of positive (>= 0.3), negative (<= -0.3), neutral (between).
      • Final label is whichever class dominates; ties resolve to neutral.
    Returns (score, label) where score in {1, 0, -1} and label in {"positive","neutral","negative"}.
    """
    pos, neg, neu = 0, 0, 0
    for s in re.split(r'[.!?]', text):
        score = sia.polarity_scores(s)
        if score['compound'] >= 0.3:
            pos += 1
        elif score['compound'] <= -0.3:
            neg += 1
        else:
            neu += 1
    total = pos + neg + neu
    if total == 0:
        return 0, 'neutral'
    if pos / total >= 0.7:
        return 1, 'positive'
    elif neg / total >= 0.7:
        return -1, 'negative'
    else:
        return 0, 'neutral'


def get_price_change(ticker, dt):
    """
    Pulls daily data around the article date and returns price snapshots:
      • Price @ Time (approx = same-day close if available, else closest)
      • +1h Price (approx = next daily row if available)
      • +4h Price (approx = next-next daily row if available)
      • End of Week Price (last available daily row in the retrieved window)
      • End of Day Price (close on article's date if available)
      • Premarket Price (first "Open" in the retrieved window)
    NOTE: Because we use daily bars, +1h/+4h are *approximations*, not true intraday.
    """
    try:
        dt_naive = dt.replace(tzinfo=None)  # strip TZ to feed yfinance date strings
        dt_str = dt_naive.strftime('%Y-%m-%d')
        ticker_data = yf.Ticker(ticker)
        hist = ticker_data.history(start=dt_str, end=(dt_naive + timedelta(days=7)).strftime('%Y-%m-%d'))

        if hist.empty:
            return ("N/A",) * 6

        # Close on the article date (if present)
        price_now_row = hist.loc[hist.index.strftime('%Y-%m-%d') == dt_str]
        price_now = price_now_row['Close'].values[0] if not price_now_row.empty else 'N/A'

        # Approximations using daily bars
        plus_1h = hist.iloc[1]['Close'] if len(hist) > 1 else 'N/A'
        plus_4h = hist.iloc[2]['Close'] if len(hist) > 2 else 'N/A'
        eod_price = hist.iloc[hist.index.strftime('%Y-%m-%d') == dt_str]['Close'].values[0] if dt_str in hist.index.strftime('%Y-%m-%d') else 'N/A'
        eow_price = hist.iloc[-1]['Close']
        premarket = hist.iloc[0]['Open'] if not hist.empty else 'N/A'

        return price_now, plus_1h, plus_4h, eow_price, eod_price, premarket
    except:
        return ("N/A",) * 6


async def scrape_finviz_and_yahoo(tickers, start, end):
    """
    Finviz headline scraper with a strict 20-second delay per ticker.
    Steps per ticker:
      • Throttle with asyncio.sleep(20) to respect Finviz.
      • Request the Finviz quote page and parse the news table.
      • Parse each row into (title, url, timestamp). Handles "Today hh:mmAM/PM" and
        full date strings like "Aug-13-25 03:45PM"; converts to ET.
      • Filter to the [start, end] window (ET).
      • For each article, optionally fetch page text (fallback to title), compute
        keyword score (with matched terms and ambiguity) + VADER score/label.
      • Compute price snapshots with yfinance.
    Returns a DataFrame of unique articles per (Ticker, Title, Datetime).
    """
    collected = []
    async with aiohttp.ClientSession() as session:
        for t in tqdm(tickers, desc="💫 News Collection"):
            try:
                # 20-second delay between tickers to reduce risk of being blocked by Finviz
                await asyncio.sleep(20)

                url = f"https://finviz.com/quote.ashx?t={t}"
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})  # sync request intentionally
                soup = BeautifulSoup(res.text, 'html.parser')

                # Finviz layout may vary. This targets the "fullview" news table variant used on quote pages.
                table = soup.find('table', class_='fullview-news-outer')
                if not table:
                    continue

                rows = table.find_all('tr')
                now = datetime.now(tz=eastern_tz)

                for row in rows:
                    try:
                        cells = row.find_all('td')
                        if len(cells) < 2:
                            continue

                        date_text = cells[0].text.strip()
                        link_tag = cells[1].find('a')
                        if not link_tag:
                            continue

                        link = link_tag['href']
                        title = link_tag.text.strip()

                        # Convert Finviz timestamp text to a timezone-aware ET datetime
                        if 'Today' in date_text:
                            # e.g., "Today 03:15PM"
                            tstr = date_text.split()[1]
                            hour, minute = map(int, tstr[:-2].split(':'))
                            if 'PM' in tstr and hour != 12:
                                hour += 12
                            elif 'AM' in tstr and hour == 12:
                                hour = 0
                            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        elif re.match(r'\w{3}-\d{2}-\d{2} \d{1,2}:\d{2}(AM|PM)', date_text):
                            # e.g., "Aug-12-25 03:45PM"
                            dt = datetime.strptime(date_text, '%b-%d-%y %I:%M%p')
                            dt = eastern_tz.localize(dt)
                        else:
                            # If the format doesn't match, skip gracefully.
                            continue

                        # Only include if within the requested ET time window
                        if not (start <= dt <= end):
                            continue

                        # Fetch article text (best effort) and score it; fallback to title
                        text = scrape_article_text(link) or title
                        lookup_score, pos_words, neg_words, ambiguous = score_lookup(text)
                        vader_score, vader_label = classify_sentiment(text)

                        # Pull pricing snapshots (approximate when using daily bars)
                        price_now, plus_1h, plus_4h, eow_price, eod_price, premarket = get_price_change(t, dt)

                        collected.append({
                            "Ticker": t,
                            "Datetime": dt,
                            "Title": title,
                            "Content": text,
                            "Lookup Score": lookup_score,
                            "Pos Words": pos_words,
                            "Neg Words": neg_words,
                            "Ambiguous": ambiguous,
                            "VADER Score": vader_score,
                            "VADER Label": vader_label,
                            "Weekend News": dt.weekday() >= 5,
                            "After Market Close": dt.time() > datetime.strptime("16:00", "%H:%M").time(),
                            "Price @ Time": price_now,
                            "+1h Price": plus_1h,
                            "+4h Price": plus_4h,
                            "End of Week Price": eow_price,
                            "End of Day Price": eod_price,
                            "Premarket Price": premarket
                        })
                    except:
                        # Skip malformed rows without breaking the outer loop
                        continue
            except:
                # Skip tickers that fail without aborting the whole run
                continue

    # Remove accidental duplicates for the same (Ticker, Title, Datetime)
    return pd.DataFrame(collected).drop_duplicates(subset=["Ticker", "Title", "Datetime"])


def price_change_pct(price_series, df, target_col):
    """
    Helper to compute an average % change from a base series to a target price column.
    - Iterates row-wise; converts safely to float; skips rows that can't be parsed.
    - Returns mean percentage change across valid rows or 0 if none.
    """
    changes = []
    for i, p in enumerate(price_series):
        try:
            base = float(p)
            target = float(df.iloc[i][target_col])
            change = ((target - base) / base) * 100
            changes.append(change)
        except:
            continue
    return sum(changes) / len(changes) if changes else 0


if __name__ == "__main__":
    # -----------------------------
    # Define the weekly window (last Monday → last Sunday) in ET
    # -----------------------------
    today = datetime.now(tz=eastern_tz)
    last_sunday = today - timedelta(days=today.weekday() + 1)
    last_monday = last_sunday - timedelta(days=6)

    start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = last_sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
    print(f"🗕️ Scraping from {start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%Y-%m-%d %H:%M')}")

    # -----------------------------
    # Scrape headlines and compute per-article rows
    # -----------------------------
    df = asyncio.run(scrape_finviz_and_yahoo(HARDCODED_TICKERS, start, end))
    print(f"📈 Headlines fetched: {len(df)}")

    if not df.empty:
        # Sort and normalize time for output consistency
        df.sort_values(by=["Ticker", "Datetime"], inplace=True)
        df["Datetime"] = df["Datetime"].dt.tz_localize(None)

        # Save the full per-article dataset
        df.to_csv("news_data.csv", index=False)

        # -----------------------------
        # Build per-ticker summary (means and average % changes)
        # -----------------------------
        summary_df = df.groupby("Ticker").agg(
            Avg_Lookup_Score=('Lookup Score', 'mean'),
            Avg_VADER_Score=('VADER Score', 'mean'),
            Headlines_Count=('Title', 'count'),
            Avg_1h_Change=('Price @ Time', lambda x: price_change_pct(x, df, '+1h Price')),
            Avg_4h_Change=('Price @ Time', lambda x: price_change_pct(x, df, '+4h Price')),
            Avg_EOD_Change=('Price @ Time', lambda x: price_change_pct(x, df, 'End of Day Price')),
            Avg_EOW_Change=('Price @ Time', lambda x: price_change_pct(x, df, 'End of Week Price'))
        ).reset_index()

        # -----------------------------
        # Write Excel workbook (Headlines + Summary)
        # -----------------------------
        filename = "weekly_sentiment_report.xlsx"
        with pd.ExcelWriter(filename) as writer:
            df.to_excel(writer, sheet_name="Headlines", index=False)
            summary_df.to_excel(writer, sheet_name="Summary", index=False)

        # -----------------------------
        # Email the Excel report via Gmail SMTP (TLS)
        # -----------------------------
        msg = EmailMessage()
        msg['Subject'] = 'Weekly Sentiment Report'
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg.set_content('Attached is your weekly sentiment analysis report.')

        with open(filename, 'rb') as f:
            file_data = f.read()
            msg.add_attachment(file_data, maintype='application', subtype='octet-stream', filename=filename)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)
            print("🚀 Email sent successfully!")
    else:
        print("⚠️ No valid headlines or price data to export.")
