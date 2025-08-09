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
        
    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y \
          wget \
          gnupg2 \
          ca-certificates \
          fonts-liberation \
          xvfb || echo "Some packages may not be available, continuing..."
          
    - name: Install Playwright browsers (priority)
      run: |
        playwright install chromium
        playwright install-deps chromium || echo "Playwright deps installation completed with warnings"
        
    - name: Install Chrome for Selenium (fallback)
      run: |
        wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
        sudo apt-get update
        sudo apt-get install -y google-chrome-stable || echo "Chrome installation failed, using system browser"
        
    - name: Download Chromium for Pyppeteer (optional)
      run: |
        python -c "
        import asyncio
        try:
            from pyppeteer import launch
            print('Downloading Chromium for Pyppeteer...')
            asyncio.get_event_loop().run_until_complete(launch())
            print('Pyppeteer setup complete')
        except Exception as e:
            print(f'Pyppeteer setup failed: {e}')
            print('Continuing without Pyppeteer...')
        "
        
    - name: Check repository structure
      run: |
        echo "=== Current directory ==="
        pwd
        echo "=== Repository contents ==="
        ls -la
        echo "=== Source directory ==="
        ls -la src/ || echo "src directory not found"
        echo "=== Python files ==="
        find . -name "*.py" -type f
        echo "=== Requirements file ==="
        cat requirements.txt || echo "requirements.txt not found"
        
    - name: Run WeatherNews Bot
      env:
        TWITTER_API_KEY: ${{ secrets.TWITTER_API_KEY }}
        TWITTER_API_SECRET: ${{ secrets.TWITTER_API_SECRET }}
        TWITTER_ACCESS_TOKEN: ${{ secrets.TWITTER_ACCESS_TOKEN }}
        TWITTER_ACCESS_TOKEN_SECRET: ${{ secrets.TWITTER_ACCESS_TOKEN_SECRET }}
        CHROME_BIN: /usr/bin/google-chrome-stable
        CHROMEDRIVER_PATH: /usr/bin/chromedriver
      run: |
        # ファイル存在確認と実行
        if [ -f "src/weather_bot.py" ]; then
          echo "Running src/weather_bot.py..."
          python src/weather_bot.py
        elif [ -f "weather_bot.py" ]; then
          echo "Running weather_bot.py..."
          python weather_bot.py
        elif [ -f "weathernews_bot.py" ]; then
          echo "Running weathernews_bot.py..."
          python weathernews_bot.py
        elif [ -f "src/weathernews_bot.py" ]; then
          echo "Running src/weathernews_bot.py..."
          python src/weathernews_bot.py
        else
          echo "ERROR: No Python bot file found!"
          echo "Available Python files:"
          find . -name "*.py" -type f
          exit 1
        fi
        
    - name: Upload results
      uses: actions/upload-artifact@v4
      if: always()
      with:
        name: bot-results
        path: |
          bot_result.json
        retention-days: 30
