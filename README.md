# Diction-Analysis-of-the-Stock-Market with Predictions---Grant-Dries

Sentiment & price tracking scripts that collect stock news from **Finviz** and **Yahoo Finance**, score headlines with **VADER + keyword lookup**, and measure price impact (+1h, +4h, EOW).  
- The scraper takes ~55 hours to run and collects everything from the past 7 days.  
- After that, you run the predictions model to generate future price predictions. This step is much faster.

---

## 📧 Email Automation Setup (Scraper)

To receive the report by email, create a `.env` file in the **same root directory** as the scraper script.  

Example `.env` file:

```ini
EMAIL_ADDRESS=INSERT_SENDER_EMAIL_ADDRESS_HERE
EMAIL_PASSWORD=INSERT_16_DIGIT_APP_PASSWORD
EMAIL_RECEIVER=INSERT_RECEIVING_EMAIL_ADDRESS_HERE

IMPORTANT NOTES: Do not use your normal email password. You need to generate an App Password from your email account and it must be with Gmail unless you swap out SMTP_SERVER and SMTP_PORT in the script for another provider. If any of the variables are missing, the script will skip email sending, but still save the Excel file locally.
Gmail directions: go to your Google Account -> Security -> "App Passwords" -> Generate a new one (this does not change your login password). You then copy the 16-character password into EMAIL_PASSWORD 

DIRECTIONS TO RUN PREDICTIONS SCRIPT:
Have the script saved in the same root directory as the DictionSentimentEmailAnalyzer script and more importantly, the same root folder that the Excel file produced from the previous script is in. The Predictions script looks for the Excel file name and alters it. 
