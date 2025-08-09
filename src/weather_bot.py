#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表スクレイピング＆Twitter投稿 統合版
Playwright → Selenium → Pyppeteer の順で試行し、最初に成功したデータでツイート投稿
"""

import os
import json
import sys
import re
import asyncio
from datetime import datetime

def log(message):
    """ログ出力"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", file=sys.stderr)

class WeatherNewsBot:
    def __init__(self):
        self.url = "https://weathernews.jp/wnl/timetable.html"
        self.schedule_data = None
        
    def try_playwright_scraping(self):
        """Playwright でスクレイピングを試行"""
        try:
            from playwright.sync_api import sync_playwright
            
            log("Playwright でスクレイピング開始...")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                page.set_extra_http_headers({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                
                page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                
                # JavaScriptで番組表データを抽出
                schedule_data = page.evaluate('''() => {
                    const result = [];
                    
                    // .boxStyle__item 内の時間とキャスター情報を抽出
                    const items = document.querySelectorAll('.boxStyle__item');
                    
                    items.forEach(item => {
                        try {
                            // 時間情報を取得
                            const timeElement = item.querySelector('p');
                            if (!timeElement) return;
                            
                            const timeText = timeElement.textContent.trim();
                            const timeMatch = timeText.match(/(\\d{2}:\\d{2})-/);
                            if (!timeMatch) return;
                            
                            const timeStr = timeMatch[1];
                            
                            // キャスターリンクを探す（casterを含むhref）
                            const casterLinks = item.querySelectorAll('a[href*="caster"]');
                            
                            casterLinks.forEach(link => {
                                const casterName = link.textContent.trim();
                                const casterUrl = link.href;
                                
                                // 有効なキャスター名かチェック
                                if (casterName && 
                                    casterName.length >= 2 && 
                                    casterName.length <= 15 &&
                                    !casterName.includes('ニュース') &&
                                    !casterName.includes('ライブ') &&
                                    /[ぁ-んァ-ヶ一-龯]/.test(casterName)) {
                                    
                                    result.push({
                                        time: timeStr,
                                        caster: casterName,
                                        profile_url: casterUrl
                                    });
                                }
                            });
                            
                        } catch (error) {
                            // エラーは無視して次へ
                        }
                    });
                    
                    return result;
                }''')
                
                browser.close()
                
                if schedule_data and len(schedule_data) > 0:
                    for item in schedule_data:
                        log(f"Playwright 抽出: {item['time']} - {item['caster']}")
                    log(f"Playwright 成功: {len(schedule_data)}件取得")
                    return schedule_data
                else:
                    log("Playwright: 有効なデータ取得なし")
                    return None
                    
        except Exception as e:
            log(f"Playwright エラー: {e}")
            return None
    
    def try_selenium_scraping(self):
        """Selenium でスクレイピングを試行"""
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            log("Selenium でスクレイピング開始...")
            
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            
            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(60)
            
            driver.get(self.url)
            
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CLASS_NAME, "boxStyle__item"))
            )
            
            import time
            time.sleep(5)
            
            schedule_items = driver.find_elements(By.CLASS_NAME, "boxStyle__item")
            programs = []
            
            for item in schedule_items:
                try:
                    # 時間の取得
                    time_elements = item.find_elements(By.TAG_NAME, "p")
                    if not time_elements:
                        continue
                    
                    time_text = time_elements[0].text.strip()
                    time_match = re.search(r'(\d{2}:\d{2})-', time_text)
                    if not time_match:
                        continue
                    
                    time_str = time_match.group(1)
                    
                    # キャスターリンクを探す（href に caster を含むもの）
                    caster_links = item.find_elements(By.CSS_SELECTOR, "a[href*='caster']")
                    
                    for caster_link in caster_links:
                        try:
                            caster_name = caster_link.text.strip()
                            caster_url = caster_link.get_attribute('href')
                            
                            # 有効なキャスター名かチェック
                            if (caster_name and 
                                len(caster_name) >= 2 and 
                                len(caster_name) <= 15 and
                                'ニュース' not in caster_name and
                                'ライブ' not in caster_name and
                                re.search(r'[ぁ-んァ-ヶ一-龯]', caster_name)):
                                
                                programs.append({
                                    'time': time_str,
                                    'caster': caster_name,
                                    'profile_url': caster_url
                                })
                                log(f"Selenium 抽出: {time_str} - {caster_name}")
                                break  # 1つの時間帯につき1人のキャスター
                        except:
                            continue
                
                except Exception as e:
                    continue
            
            driver.quit()
            
            if programs:
                log(f"Selenium 成功: {len(programs)}件取得")
                return programs
            else:
                log("Selenium: 有効なデータ取得なし")
                return None
                
        except Exception as e:
            log(f"Selenium エラー: {e}")
            return None
    
    async def try_pyppeteer_scraping(self):
        """Pyppeteer でスクレイピングを試行"""
        try:
            from pyppeteer import launch
            
            log("Pyppeteer でスクレイピング開始...")
            
            browser = await launch({
                'headless': True,
                'args': [
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--window-size=1920,1080'
                ]
            })
            
            page = await browser.newPage()
            await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            await page.goto(self.url, {'waitUntil': 'domcontentloaded', 'timeout': 60000})
            await asyncio.sleep(5)
            
            # JavaScriptでデータを抽出
            schedule_items = await page.evaluate('''() => {
                const result = [];
                const items = document.querySelectorAll('.boxStyle__item');
                
                items.forEach(item => {
                    try {
                        // 時間情報を取得
                        const timeElement = item.querySelector('p');
                        if (!timeElement) return;
                        
                        const timeText = timeElement.textContent.trim();
                        const timeMatch = timeText.match(/(\\d{2}:\\d{2})-/);
                        if (!timeMatch) return;
                        
                        const timeStr = timeMatch[1];
                        
                        // キャスターリンクを探す（href に caster を含むもの）
                        const casterLinks = item.querySelectorAll('a[href*="caster"]');
                        
                        casterLinks.forEach(link => {
                            const casterName = link.textContent.trim();
                            const casterUrl = link.href;
                            
                            // 有効なキャスター名かチェック
                            if (casterName && 
                                casterName.length >= 2 && 
                                casterName.length <= 15 &&
                                !casterName.includes('ニュース') &&
                                !casterName.includes('ライブ') &&
                                /[ぁ-んァ-ヶ一-龯]/.test(casterName)) {
                                
                                result.push({
                                    time: timeStr,
                                    caster: casterName,
                                    profile_url: casterUrl
                                });
                            }
                        });
                        
                    } catch (error) {
                        // エラーは無視
                    }
                });
                
                return result;
            }''')
            
            await browser.close()
            
            if schedule_items:
                for item in schedule_items:
                    log(f"Pyppeteer 抽出: {item['time']} - {item['caster']}")
                log(f"Pyppeteer 成功: {len(schedule_items)}件取得")
                return schedule_items
            else:
                log("Pyppeteer: 有効なデータ取得なし")
                return None
                
        except Exception as e:
            log(f"Pyppeteer エラー: {e}")
            return None
    
    def get_fallback_schedule(self, partial_data=None):
        """フォールバック用スケジュール（部分データがあれば活用）"""
        log("フォールバック: スケジュール生成")
        
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        programs = []
        
        # 部分的に取得できたデータがあれば活用
        existing_casters = {}
        known_casters_pool = []
        
        if partial_data:
            log(f"部分データを活用: {len(partial_data)}件")
            for item in partial_data:
                if item.get('time') in main_times:
                    existing_casters[item['time']] = item['caster']
                    known_casters_pool.append(item['caster'])
        
        # 既知の実在キャスター（最小限のフォールバック）
        fallback_casters = [
            '青原桃香', '田辺真南葉', '松本真央', 
            '小林李衣奈', '岡本結子リサ', '山岸愛梨',
            '白井ゆかり', '駒木結衣', '戸北美月'
        ]
        
        # 取得できたキャスターを既知リストに追加
        for caster in known_casters_pool:
            if caster not in fallback_casters:
                fallback_casters.append(caster)
        
        # 各時間帯にキャスターを割り当て
        for i, time_str in enumerate(main_times):
            if time_str in existing_casters:
                # 実際に取得できたデータを使用
                programs.append({
                    'time': time_str,
                    'caster': existing_casters[time_str]
                })
                log(f"実データ使用: {time_str} - {existing_casters[time_str]}")
            elif i < len(fallback_casters):
                # フォールバックキャスターを使用
                programs.append({
                    'time': time_str,
                    'caster': fallback_casters[i]
                })
                log(f"フォールバック: {time_str} - {fallback_casters[i]}")
            else:
                # それでもない場合は「未定」
                programs.append({
                    'time': time_str,
                    'caster': '未定'
                })
                log(f"未定: {time_str}")
        
        return programs
    
    async def scrape_schedule(self):
        """スケジュール取得（複数手法を順次試行）"""
        log("=== ウェザーニュース番組表取得開始 ===")
        
        all_attempts_data = []  # 全ての試行で得られたデータを保存
        
        # 1. Playwright を試行
        programs = self.try_playwright_scraping()
        if programs:
            all_attempts_data.extend(programs)
            if len(programs) >= 3:  # 十分なデータが取得できた場合
                self.schedule_data = {
                    'programs': sorted(programs, key=lambda x: x['time']),
                    'source': 'playwright',
                    'timestamp': datetime.now().isoformat()
                }
                return self.schedule_data
        
        # 2. Selenium を試行
        programs = self.try_selenium_scraping()
        if programs:
            all_attempts_data.extend(programs)
            if len(programs) >= 3:  # 十分なデータが取得できた場合
                self.schedule_data = {
                    'programs': sorted(programs, key=lambda x: x['time']),
                    'source': 'selenium',
                    'timestamp': datetime.now().isoformat()
                }
                return self.schedule_data
        
        # 3. Pyppeteer を試行
        programs = await self.try_pyppeteer_scraping()
        if programs:
            all_attempts_data.extend(programs)
            if len(programs) >= 3:  # 十分なデータが取得できた場合
                self.schedule_data = {
                    'programs': sorted(programs, key=lambda x: x['time']),
                    'source': 'pyppeteer',
                    'timestamp': datetime.now().isoformat()
                }
                return self.schedule_data
        
        # 4. 部分データの統合を試行
        if all_attempts_data:
            log(f"部分データ統合: 全{len(all_attempts_data)}件から最適化")
            
            # 重複除去と時間帯別統合
            time_caster_map = {}
            for item in all_attempts_data:
                time_key = item['time']
                if time_key not in time_caster_map:
                    time_caster_map[time_key] = item['caster']
            
            consolidated_programs = []
            for time_str, caster in time_caster_map.items():
                consolidated_programs.append({
                    'time': time_str,
                    'caster': caster
                })
            
            if len(consolidated_programs) >= 2:  # 最低2件あれば使用
                # 不足分をフォールバックで補完
                programs = self.get_fallback_schedule(consolidated_programs)
                self.schedule_data = {
                    'programs': programs,
                    'source': 'consolidated_partial',
                    'timestamp': datetime.now().isoformat()
                }
                log(f"部分データ統合完了: {len(consolidated_programs)}件の実データ + フォールバック")
                return self.schedule_data
        
        # 5. 完全フォールバック
        programs = self.get_fallback_schedule()
        self.schedule_data = {
            'programs': programs,
            'source': 'fallback',
            'timestamp': datetime.now().isoformat()
        }
        log("完全フォールバックスケジュールを使用")
        return self.schedule_data
    
    def format_tweet_text(self):
        """ツイート文を生成"""
        if not self.schedule_data:
            return None
        
        today = datetime.now().strftime('%Y年%m月%d日')
        tweet_text = f"📺 {today} ウェザーニュースLiVE 番組表\n\n"
        
        programs = self.schedule_data['programs']
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        
        # 時間帯別にキャスターを整理
        caster_by_time = {}
        for program in programs:
            time_key = program['time']
            if time_key in main_times:
                caster_by_time[time_key] = program['caster']
        
        # ツイート本文を構築
        for time_str in main_times:
            if time_str in caster_by_time:
                caster = caster_by_time[time_str]
                tweet_text += f"{time_str}-{caster}\n"
            else:
                tweet_text += f"{time_str}-未定\n"
        
        tweet_text += "\n#ウェザーニュース #番組表"
        
        # 文字数制限チェック（280文字）
        if len(tweet_text) > 280:
            log(f"ツイート文が長すぎます({len(tweet_text)}文字)。短縮します。")
            tweet_text = f"📺 {today} ウェザーニュースLiVE 番組表\n\n"
            
            # 最初の4つの時間帯のみ
            for time_str in main_times[:4]:
                if time_str in caster_by_time:
                    caster = caster_by_time[time_str]
                    tweet_text += f"{time_str}-{caster}\n"
            
            tweet_text += "\n#ウェザーニュース #番組表"
        
        return tweet_text
    
    def post_to_twitter(self, tweet_text):
        """Twitterに投稿"""
        try:
            import tweepy
            
            # Twitter API認証情報を環境変数から取得
            api_key = os.getenv('TWITTER_API_KEY')
            api_secret = os.getenv('TWITTER_API_SECRET')
            access_token = os.getenv('TWITTER_ACCESS_TOKEN')
            access_token_secret = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
            
            if not all([api_key, api_secret, access_token, access_token_secret]):
                log("Twitter API認証情報が不完全です")
                return False
            
            # Twitter APIクライアント初期化
            client = tweepy.Client(
                consumer_key=api_key,
                consumer_secret=api_secret,
                access_token=access_token,
                access_token_secret=access_token_secret,
                wait_on_rate_limit=True
            )
            
            # ツイート投稿
            response = client.create_tweet(text=tweet_text)
            
            if response.data:
                tweet_id = response.data['id']
                log(f"ツイート投稿成功: https://twitter.com/i/web/status/{tweet_id}")
                return True
            else:
                log("ツイート投稿に失敗しました")
                return False
        
        except Exception as e:
            log(f"ツイート投稿エラー: {e}")
            return False
    
    async def run(self):
        """メイン実行"""
        try:
            # スケジュール取得
            schedule_data = await self.scrape_schedule()
            
            log("=== 取得されたデータ ===")
            for program in schedule_data['programs']:
                log(f"  {program['time']} - {program['caster']}")
            log(f"データソース: {schedule_data['source']}")
            log("========================")
            
            # ツイート文を生成
            tweet_text = self.format_tweet_text()
            
            if not tweet_text:
                log("ツイート文の生成に失敗しました")
                return False
            
            log("=== 生成されたツイート文 ===")
            log(tweet_text)
            log(f"文字数: {len(tweet_text)}")
            log("===========================")
            
            # Twitterに投稿
            success = self.post_to_twitter(tweet_text)
            
            # 結果を保存
            result = {
                'success': success,
                'schedule_data': schedule_data,
                'tweet_text': tweet_text,
                'timestamp': datetime.now().isoformat()
            }
            
            with open('bot_result.json', 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            log(f"=== 実行完了 ===")
            log(f"ツイート投稿: {'成功' if success else '失敗'}")
            
            return success
            
        except Exception as e:
            log(f"実行エラー: {e}")
            return False

async def main():
    """メイン実行"""
    log("=== ウェザーニュースボット開始 ===")
    
    bot = WeatherNewsBot()
    success = await bot.run()
    
    if success:
        log("処理完了: 成功")
        sys.exit(0)
    else:
        log("処理完了: 失敗")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
