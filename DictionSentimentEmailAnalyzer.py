# ---------------------------------------------------------------------------------
# Weekly Sentiment Scraper (Finviz-based) — Clean version (Pct_EOD removed)
# ---------------------------------------------------------------------------------
# Notes:
#   • Computes Pct_1h, Pct_4h, Pct_EOW.
#   • Everything remains drop-in compatible.
#
# Requirements: finviz.csv (Ticker column), yfinance, aiohttp, bs4, nltk (vader_lexicon), pytz, python-dotenv

import pandas as pd
from datetime import datetime, timedelta
from dateutil import parser
from collections import defaultdict
import os
import requests
import yfinance as yf
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
import re
import pytz
from tqdm import tqdm
import asyncio
import aiohttp
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from bs4 import BeautifulSoup

# === VADER Setup ===
try:
    nltk.data.find('sentiment/vader_lexicon')
except LookupError:
    nltk.download('vader_lexicon')

# === Load tickers from finviz.csv ===
finviz_df = pd.read_csv('finviz.csv')
HARDCODED_TICKERS = finviz_df['Ticker'].astype(str).str.upper().str.strip().dropna().unique().tolist()
print(f"✅ Loaded {len(HARDCODED_TICKERS)} tickers from finviz.csv")

# === Email Config ===
load_dotenv()
EMAIL_SENDER = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVER = os.getenv('EMAIL_RECEIVER')
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

# === TIMEZONE ===
eastern_tz = pytz.timezone('US/Eastern')

# === SENTIMENT LOOKUP ===
positive_keywords = {
    "beat","beats","beating","exceed","exceeds","exceeded","exceeding","surge","surges","surged",
    "soar","soars","soared","rally","rallies","rallied","jump","jumps","jumped","spike","spikes",
    "spiked","pop","pops","popped","gain","gains","gained","advance","advances","advanced","rise",
    "rises","rose","upbeat","bull","bullish","optimism","optimistic","confidence","confident",
    "strong","strength","robust","resilient","resilience","record","high","highs","profit","profits",
    "profitable","profitability","margin","margins","expand","expands","expanded","expanding","growth",
    "growing","accelerate","accelerates","accelerated","accelerating","outperform","outperforms",
    "outperformed","outperforming","upgrade","upgrades","upgraded","upgrading","overweight","buy",
    "buying","accumulate","accumulating","initiate","initiates","initiated","initiating","guidance",
    "raise","raises","raised","raising","hike","hikes","hiked","dividend","dividends","increase",
    "increases","increased","increasing","buyback","buybacks","repurchase","repurchases"
}
negative_keywords = {
    "miss","misses","missed","missing","lag","lags","lagged","lagging","plunge","plunges","plunged",
    "plunging","tumble","tumbles","tumbled","tumbling","drop","drops","dropped","dropping","fall",
    "falls","fell","falling","slump","slumps","slumped","slumping","slide","slides","slid","sliding",
    "decline","declines","declined","declining","selloff","selloffs","weak","weakness","soft","softness",
    "bear","bearish","pessimism","pessimistic","fear","loss","losses","unprofitable","compression",
    "compress","compressed","cut","cuts","cutting","lower","lowers","lowered","lowering","reduce",
    "reduces","reduced","reducing","downgrade","downgrades","downgraded","downgrading","underperform",
    "underperforms","underperformed","underperforming","warning","recall","recalls","recalled",
    "restructuring","layoff","layoffs","furlough","furloughs","bankruptcy","insolvency","default",
    "defaults","defaulted","dilution","dilutive","lawsuit","lawsuits","probe","probes","investigation",
    "investigations","fraud","scandal","resign","resigns","resigned","resignation"
}

sia = SentimentIntensityAnalyzer()
PRICE_CACHE = {}

def scrape_article_text(url):
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
    tokens = re.findall(r"\w+", text.lower())
    pos_matches = [w for w in tokens if w in positive_keywords]
    neg_matches = [w for w in tokens if w in negative_keywords]
    score = 1 if len(pos_matches) > len(neg_matches) else -1 if len(neg_matches) > len(pos_matches) else 0
    ambiguous = bool(pos_matches and neg_matches)
    return score, ', '.join(pos_matches), ', '.join(neg_matches), ambiguous

def classify_sentiment(text):
    pos, neg, neu = 0, 0, 0
    for s in re.split(r'[.!?]', text):
        if not s.strip():
            continue
        sc = sia.polarity_scores(s)
        if sc['compound'] >= 0.3:   pos += 1
        elif sc['compound'] <= -0.3: neg += 1
        else:                        neu += 1
    total = pos + neg + neu
    if total == 0: return 0, 'neutral'
    if pos / total >= 0.7: return 1, 'positive'
    if neg / total >= 0.7: return -1, 'negative'
    return 0, 'neutral'

def get_price_change(ticker, dt, start_window, end_window):
    """
    Daily-based approximations (fast, no intraday). We still record End of Day Price,
    but we DO NOT compute Pct_EOD anywhere in this script.
    """
    try:
        key = (ticker, start_window.date(), end_window.date())
        if key not in PRICE_CACHE:
            tkr = yf.Ticker(ticker)
            hist = tkr.history(
                start=start_window.strftime('%Y-%m-%d'),
                end=(end_window + timedelta(days=7)).strftime('%Y-%m-%d')
            )
            PRICE_CACHE[key] = hist
        else:
            hist = PRICE_CACHE[key]

        if hist.empty:
            return ("N/A",) * 6

        dt_et = dt.astimezone(eastern_tz)
        dt_str = dt_et.strftime('%Y-%m-%d')
        day_row = hist.loc[hist.index.strftime('%Y-%m-%d') == dt_str]
        if day_row.empty:
            return ("N/A",) * 6

        open_  = float(day_row["Open"].iloc[0])
        close_ = float(day_row["Close"].iloc[0])

        # crude "price at time" using daily bars
        if dt_et.time() < datetime.strptime("16:00", "%H:%M").time():
            price_now = open_
        else:
            price_now = close_

        plus_1h = "N/A"   # not reliable without intraday
        plus_4h = "N/A"
        eod_price = close_
        eow_price = float(hist["Close"].iloc[-1])
        premarket = open_

        return price_now, plus_1h, plus_4h, eow_price, eod_price, premarket
    except:
        return ("N/A",) * 6

async def scrape_finviz_and_yahoo(tickers, start, end):
    collected = []
    async with aiohttp.ClientSession() as session:
        for t in tqdm(tickers, desc="💫 News Collection"):
            try:
                # throttle per ticker
                await asyncio.sleep(20)
                url = f"https://finviz.com/quote.ashx?t={t}"
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                soup = BeautifulSoup(res.text, 'html.parser')
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

                        # Finviz timestamp → ET datetime
                        if 'Today' in date_text:
                            tstr = date_text.split()[1]   # "03:15PM"
                            hour_min, ampm = tstr[:-2], tstr[-2:]
                            hour, minute = map(int, hour_min.split(':'))
                            if ampm == 'PM' and hour != 12: hour += 12
                            if ampm == 'AM' and hour == 12: hour = 0
                            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        elif re.match(r'\w{3}-\d{2}-\d{2} \d{1,2}:\d{2}(AM|PM)', date_text):
                            dt = datetime.strptime(date_text, '%b-%d-%y %I:%M%p')
                            dt = eastern_tz.localize(dt)
                        else:
                            continue

                        if not (start <= dt <= end):
                            continue

                        text = scrape_article_text(link) or title
                        lookup_score, pos_words, neg_words, ambiguous = score_lookup(text)
                        vader_score, vader_label = classify_sentiment(text)

                        price_now, plus_1h, plus_4h, eow_price, eod_price, premarket = \
                            get_price_change(t, dt, start, end)

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
                        continue
            except:
                continue

    return pd.DataFrame(collected).drop_duplicates(subset=["Ticker", "Title", "Datetime"])

def _pct(a, b):
    try:
        a = float(a); b = float(b)
        return ((b - a) / a) * 100.0
    except:
        return None

if __name__ == "__main__":
    # last Monday → last Sunday in ET
    today = datetime.now(tz=eastern_tz)
    last_sunday = today - timedelta(days=today.weekday() + 1)
    last_monday = last_sunday - timedelta(days=6)
    start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    end   = last_sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
    print(f"🗕️ Scraping from {start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%Y-%m-%d %H:%M')}")

    df = asyncio.run(scrape_finviz_and_yahoo(HARDCODED_TICKERS, start, end))
    print(f"📈 Headlines fetched: {len(df)}")

    if not df.empty:
        df.sort_values(by=["Ticker", "Datetime"], inplace=True)
        df["Datetime"] = df["Datetime"].dt.tz_localize(None)

        # per-row percent changes (NO Pct_EOD)
        df['Pct_1h']  = df.apply(lambda r: _pct(r['Price @ Time'], r['+1h Price']), axis=1)
        df['Pct_4h']  = df.apply(lambda r: _pct(r['Price @ Time'], r['+4h Price']), axis=1)
        df['Pct_EOW'] = df.apply(lambda r: _pct(r['Price @ Time'], r['End of Week Price']), axis=1)

        df.to_csv("news_data.csv", index=False)

        # per-ticker summary (NO Avg_EOD_Change)
        summary_df = df.groupby("Ticker").agg(
            Avg_Lookup_Score=('Lookup Score', 'mean'),
            Avg_VADER_Score=('VADER Score', 'mean'),
            Headlines_Count=('Title', 'count'),
            Avg_1h_Change=('Pct_1h', 'mean'),
            Avg_4h_Change=('Pct_4h', 'mean'),
            Avg_EOW_Change=('Pct_EOW', 'mean')
        ).reset_index()

        filename = "weekly_sentiment_report.xlsx"
        with pd.ExcelWriter(filename) as writer:
            df.to_excel(writer, sheet_name="Headlines", index=False)
            summary_df.to_excel(writer, sheet_name="Summary", index=False)

        # email
        if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER:
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
            print("ℹ️ Email variables not set; skipped email.")
    else:
        print("⚠️ No valid headlines or price data to export.")

