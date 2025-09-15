# Diction-Analysis-of-the-Stock-Market with Predictions — Grant Dries

This project has two parts:  

1. **Scraper** — Collects stock news from Finviz and Yahoo Finance, scores headlines with VADER + keyword lookup, and measures price impact (+1h, +4h, EOW).  
   - This scrape takes a long time (~55 hours) since it pulls all headlines from the past 7 days.  
   - At the end it creates an Excel file.  

2. **Predictions** — Uses that Excel file to generate future price predictions.  
   - This part runs quickly and outputs a new workbook with predictions added.  

---

## 📦 Setup

Make sure you have Python 3.10+ installed. You’ll also need to install some packages before running the scripts.

Install with pip:

```bash
pip install pandas numpy yfinance aiohttp beautifulsoup4 nltk python-dotenv tqdm openpyxl pytz python-dateutil

Or create a requirements.txt file with these lines and run:
pip install -r requirements.txt
pandas
numpy
yfinance
aiohttp
beautifulsoup4
nltk
python-dotenv
tqdm
openpyxl
pytz
python-dateutil

📧 Email Automation Setup (Scraper)

The scraper can automatically email you the weekly Excel report. To enable this:

Create a .env file in the same root directory as the scraper script.

Fill it in like this:
EMAIL_ADDRESS=INSERT_SENDER_EMAIL_ADDRESS_HERE
EMAIL_PASSWORD=INSERT_16_DIGIT_APP_PASSWORD
EMAIL_RECEIVER=INSERT_RECEIVING_EMAIL_ADDRESS_HERE

Important Notes

Do not use your normal Gmail password.
Generate a Gmail App Password:
Google Account → Security → App Passwords → Generate New.
Paste the 16-character password into EMAIL_PASSWORD.
By default, the script uses Gmail (SMTP_SERVER and SMTP_PORT). If you want another provider, change those values in the script.

If the variables are missing, the script will skip email sending but still save the Excel file locally.

📊 Running the Scraper

Run the scraper script to collect headlines and create the weekly report:
This produces an Excel file:

weekly_sentiment_report.xlsx

With sheets:
Headlines — all scraped headlines, scores, and price impact
Summary — per-ticker averages (lookup score, VADER score, price changes, etc.)

🔮 Running the Predictions Script

After you have the report, run the predictions script to add forecasts.

Make sure add_predictions.py is in the same root directory as:
The scraper script 
The Excel file from the scraper (weekly_sentiment_report.xlsx)

This creates:
weekly_sentiment_with_predictions_v4.xlsx

With sheets:
Headlines — original + any intraday repairs
Summary — adds a Pred_NextDay_% column
Predictions — per-ticker forecast and latest headline info

📁 Recommended Project Layout
project-root/
├─ weekly_sentiment_scraper.py
├─ add_predictions.py
├─ finviz.csv
├─ .env                  # optional (for email sending)
├─ requirements.txt
└─ weekly_sentiment_report.xlsx  # created after scraper runs

ℹ️ Notes

The scraper is heavy and slow (multi-day run). The prediction step is fast.
If you don’t want to use email, skip the .env setup — the Excel file still saves locally.

Good .gitignore additions:
.env
*.xlsx
__pycache__/
*.pyc

---
