name: WeatherNews Schedule Bot

on:
  schedule:
    # 毎日朝6時に実行 (JST 15時 = UTC 6時)
    - cron: '0 6 * * *'
  workflow_dispatch: # 手動実行も可能

jobs:
  scrape_and_post:
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout repository
      uses: actions/checkout@v4
      
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'
        
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        
    - name: Install Chrome dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y \
          wget \
          gnupg \
          unzip \
          curl
        
        # Google Chrome Stable をインストール
        wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
        sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
        sudo apt-get update
        sudo apt-get install -y google-chrome-stable
        
        # ChromeDriverは webdriver-manager で自動管理
          
    - name: Download Chromium for Pyppeteer
      run: |
        python -c "
import asyncio
from pyppeteer import launch

async def download_chromium():
    try:
        browser = await launch()
        await browser.close()
        print('✅ Chromium download completed')
    except Exception as e:
        print(f'⚠️ Chromium download failed: {e}')

asyncio.run(download_chromium())
"
        
    - name: Run WeatherNews scraper (Selenium)
      run: |
        echo "🔄 Seleniumでスクレイピング実行中..."
        python selenium_weathernews_bot.py > selenium_output.json 2>&1 || echo "⚠️ Selenium failed"
        if [ -f selenium_output.json ]; then
          echo "✅ Selenium output generated"
        fi
        
    - name: Run WeatherNews scraper (Pyppeteer) 
      run: |
        echo "🔄 Pyppeteerでスクレイピング実行中..."
        python pyppeteer_weathernews_bot.py > pyppeteer_output.json 2>&1 || echo "⚠️ Pyppeteer failed"
        if [ -f pyppeteer_output.json ]; then
          echo "✅ Pyppeteer output generated"
        fi
        
    - name: Post to Twitter/X
      env:
        TWITTER_API_KEY: ${{ secrets.TWITTER_API_KEY }}
        TWITTER_API_SECRET: ${{ secrets.TWITTER_API_SECRET }}
        TWITTER_ACCESS_TOKEN: ${{ secrets.TWITTER_ACCESS_TOKEN }}
        TWITTER_ACCESS_TOKEN_SECRET: ${{ secrets.TWITTER_ACCESS_TOKEN_SECRET }}
      run: |
        echo "📱 X(Twitter)投稿実行中..."
        python weather_bot.py 2>&1 || echo "⚠️ X投稿に失敗しました"
        echo "🏁 処理完了"
        
    - name: Upload artifacts
      uses: actions/upload-artifact@v4
      if: always()
      with:
        name: scraping-results-${{ github.run_number }}
        path: |
          selenium_output.json
          pyppeteer_output.json
          latest_schedule.json
          run_result.json
        retention-days: 30
        if-no-files-found: warn
