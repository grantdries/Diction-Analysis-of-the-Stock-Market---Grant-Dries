# Diction-Analysis-of-the-Stock-Market with Predictions---Grant-Dries
Sentiment &amp; price tracking scripts that collect stock news from Finviz/Yahoo, score headlines with VADER + keyword lookup, and measure price impact (+1h, +4h, EOD, EOW). Takes over 55 hours to run and collects everything from the past 7 days.

In order to run the DictionSentimentEmailAnalyzer and recieve an email of the report, you have to create a .env file and store it in the same root directory that the script is saved in. Fill it with the following information in this format:

EMAIL_ADDRESS=INSERT SENDER EMAIL ADDRESS HERE
EMAIL_PASSWORD=16 DIGIT APP PASSWORD FOR THE EMAIL ADDRESS THAT ALLOWS THE CODE TO ACCESS (NOT THE NORMAL EMAIL PASSWORD)
EMAIL_RECEIVER=INSERT RECIEVING EMAIL ADDRESS HERE

IMPORTANT NOTES: Do not use your normal email password. You need to generate an App Password from your email account and it must be with Gmail unless you swap out STMP_SERVER and STMP_PORT in the script for another provider. If any of the variables are missing, the script will skip email sending, but still save the Excel file locally.
Gmail directions: go to your Google Account -> Security -> "App Passwords" -> Generate a new one (this does not change your login password). You then copy the 16-character password into EMAIL_PASSWORD 

DIRECTIONS TO RUN PREDICTIONS SCRIPT:
Have the script samed in the same root directory as 
