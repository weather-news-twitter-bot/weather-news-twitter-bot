#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表スクレイピング＆Twitter投稿 統合版（2025安定化版）
- Playwright Async → Selenium Stealth → フォールバック
- 全キャスター未定ならツイートスキップ
- 環境変数による対象日制御対応
"""
import os
import json
import sys
import re
import asyncio
from datetime import datetime, timezone, timedelta

# 日本時間のタイムゾーン
JST = timezone(timedelta(hours=9))

def log(message):
    """ログ出力"""
    now_jst = datetime.now(JST)
    print(f"[{now_jst.strftime('%H:%M:%S')}] {message}", file=sys.stderr)

class WeatherNewsBot:
    def __init__(self):
        self.url = "https://weathernews.jp/wnl/timetable.html"
        self.schedule_data = None
       
        # デバッグ情報出力
        log(f"現在時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")
        log(f"対象日制御モード: {os.getenv('SCHEDULE_TARGET_MODE', 'auto')}")
        log(f"判定時刻: {os.getenv('SCHEDULE_THRESHOLD_HOUR', '18')}:00")
        if os.getenv('SCHEDULE_TARGET_DATE'):
            log(f"明示的指定日: {os.getenv('SCHEDULE_TARGET_DATE')}")

    def get_target_date_with_env_control(self):
        """環境変数による対象日制御（変更なし）"""
        now_jst = datetime.now(JST)
        target_date_env = os.getenv('SCHEDULE_TARGET_DATE')
        if target_date_env:
            try:
                target_date = datetime.strptime(target_date_env, '%Y-%m-%d')
                target_date = target_date.replace(tzinfo=JST)
                target_date_str = target_date.strftime('%Y年%m月%d日')
                log(f"環境変数で指定された日付を使用: {target_date_str}")
                return target_date, target_date_str
            except ValueError:
                log(f"環境変数SCHEDULE_TARGET_DATEの形式が不正です: {target_date_env}")
       
        target_mode = os.getenv('SCHEDULE_TARGET_MODE', 'auto').lower()
        threshold_hour = int(os.getenv('SCHEDULE_THRESHOLD_HOUR', '18'))
       
        if target_mode == 'tomorrow':
            target_date = now_jst + timedelta(days=1)
            log(f"モード指定により翌日({target_date.strftime('%m月%d日')})の番組表を対象とします")
        elif target_mode == 'today':
            target_date = now_jst
            log(f"モード指定により当日({target_date.strftime('%m月%d日')})の番組表を対象とします")
        else:  # auto mode
            if now_jst.hour >= threshold_hour:
                target_date = now_jst + timedelta(days=1)
                log(f"{threshold_hour}:00以降の実行のため翌日({target_date.strftime('%m月%d日')})の番組表を対象とします")
            else:
                target_date = now_jst
                log(f"{threshold_hour}:00より前の実行のため当日({target_date.strftime('%m月%d日')})の番組表を対象とします")
       
        target_date_str = target_date.strftime('%Y年%m月%d日')
        return target_date, target_date_str

    async def try_playwright_scraping(self):
        """Playwright Async でスクレイピングを試行"""
        try:
            from playwright.async_api import async_playwright
            log("Playwright Async でスクレイピング開始...")
           
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--disable-blink-features=AutomationControlled']
                )
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                page = await context.new_page()
               
                await page.goto(self.url, wait_until="networkidle", timeout=90000)
                await page.wait_for_timeout(10000)
                await page.screenshot(path='debug_playwright.png', full_page=True)
               
                schedule_data = await page.evaluate('''() => {
                    const result = [];
                    const items = document.querySelectorAll('.boxStyle__item');
                    const mainTimes = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00'];
                    let foundNextDay = false;
                   
                    items.forEach(item => {
                        try {
                            const timeElements = item.querySelectorAll('p');
                            if (!timeElements || timeElements.length === 0) return;
                           
                            const timeText = timeElements[0].textContent.trim();
                            const timeMatch = timeText.match(/(\\d{2}:\\d{2})-/);
                            if (!timeMatch) return;
                           
                            const timeStr = timeMatch[1];
                           
                            let programName = "ウェザーニュースLiVE";
                            const programElements = item.querySelectorAll('p.bold');
                            if (programElements.length > 0) {
                                programName = programElements[0].textContent.trim();
                            }
                           
                            if (programName.includes('モーニング') && !foundNextDay) {
                                foundNextDay = true;
                            }
                           
                            if (foundNextDay && mainTimes.includes(timeStr)) {
                                const casterLinks = item.querySelectorAll('a[href*="caster"]');
                               
                                if (casterLinks.length > 0) {
                                    const casterLink = casterLinks[0];
                                    const casterName = casterLink.textContent.trim();
                                    const casterUrl = casterLink.href;
                                   
                                    if (casterName && casterName.length >= 2 && /[ぁ-んァ-ヶ一-龯]/.test(casterName)) {
                                        result.push({
                                            time: timeStr,
                                            caster: casterName,
                                            program: programName,
                                            profile_url: casterUrl
                                        });
                                    }
                                } else {
                                    result.push({
                                        time: timeStr,
                                        caster: '未定',
                                        program: programName,
                                        profile_url: ''
                                    });
                                }
                            }
                        } catch (error) {
                            console.error('アイテム処理エラー:', error);
                        }
                    });
                    return result;
                }''')
               
                await browser.close()
               
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
        """Selenium Stealth でスクレイピングを試行"""
        try:
            import undetected_chromedriver as uc
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
           
            log("Selenium Stealth でスクレイピング開始...")
           
            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument("--disable-renderer-timeout")
           
            driver = uc.Chrome(options=options, headless=False)  # テスト時はFalse
           
            driver.set_page_load_timeout(120)
            driver.implicitly_wait(15)
           
            driver.get(self.url)
           
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CLASS_NAME, "boxStyle__item"))
            )
           
            import time
            time.sleep(15)
            driver.save_screenshot('debug_selenium.png')
           
            schedule_items = driver.find_elements(By.CLASS_NAME, "boxStyle__item")
            programs = []
            main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
            found_next_day = False
           
            for item in schedule_items:
                try:
                    time_elements = item.find_elements(By.TAG_NAME, "p")
                    if not time_elements:
                        continue
                   
                    time_text = time_elements[0].text.strip()
                    time_match = re.search(r'(\d{2}:\d{2})-', time_text)
                    if not time_match:
                        continue
                   
                    time_str = time_match.group(1)
                   
                    program_name = "ウェザーニュースLiVE"
                    program_elements = item.find_elements(By.CSS_SELECTOR, "p.bold")
                    if program_elements:
                        program_name = program_elements[0].text.strip()
                   
                    if 'モーニング' in program_name and not found_next_day:
                        found_next_day = True
                        log(f"翌日分開始: {time_str} - {program_name}")
                   
                    if found_next_day and time_str in main_times:
                        caster_links = item.find_elements(By.CSS_SELECTOR, "a[href*='caster']")
                       
                        if caster_links:
                            caster_link = caster_links[0]
                            caster_name = caster_link.text.strip()
                            caster_url = caster_link.get_attribute('href')
                           
                            if (caster_name and len(caster_name) >= 2 and re.search(r'[ぁ-んァ-ヶ一-龯]', caster_name)):
                                programs.append({
                                    'time': time_str,
                                    'caster': caster_name,
                                    'program': program_name,
                                    'profile_url': caster_url
                                })
                                log(f"Selenium 抽出: {time_str} - {caster_name}")
                            else:
                                programs.append({
                                    'time': time_str,
                                    'caster': '未定',
                                    'program': program_name,
                                    'profile_url': ''
                                })
                        else:
                            programs.append({
                                'time': time_str,
                                'caster': '未定',
                                'program': program_name,
                                'profile_url': ''
                            })
                except Exception as e:
                    log(f"アイテム処理エラー: {e}")
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
        """Pyppeteer をスキップ（互換性問題回避）"""
        log("Pyppeteer: スキップ（websocketsエラー回避）")
        return None

    def get_fallback_schedule(self, partial_data=None):
        """フォールバック用スケジュール"""
        log("フォールバック: スケジュール生成")
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        programs = []
        existing_casters = {}
       
        if partial_data:
            for item in partial_data:
                if item.get('time') in main_times:
                    existing_casters[item['time']] = item.get('caster', '未定')
       
        for time_str in main_times:
            caster_name = existing_casters.get(time_str, '未定')
            programs.append({
                'time': time_str,
                'caster': caster_name,
                'program': self.get_program_name_by_time(time_str)
            })
        return programs

    def get_program_name_by_time(self, time_str):
        """時間帯から番組名を取得"""
        program_info = {
            '05:00': 'ウェザーニュースLiVE・モーニング',
            '08:00': 'ウェザーニュースLiVE・サンシャイン',
            '11:00': 'ウェザーニュースLiVE・コーヒータイム',
            '14:00': 'ウェザーニュースLiVE・アフタヌーン',
            '17:00': 'ウェザーニュースLiVE・イブニング',
            '20:00': 'ウェザーニュースLiVE・ムーン'
        }
        return program_info.get(time_str, 'ウェザーニュースLiVE')

    def filter_todays_schedule(self, programs):
        """主要時間帯のみフィルタリング"""
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        return [p for p in programs if p['time'] in main_times]

    def has_valid_caster(self, programs):
        """実在のキャスター名があるか判定（未定以外）"""
        return any(
            p['caster'] != '未定' and 
            len(p['caster']) >= 2 and 
            re.search(r'[ぁ-んァ-ヶ一-龯]', p['caster'])
            for p in programs
        )

    async def scrape_schedule(self):
        """スケジュール取得（優先順位: Playwright → Selenium → フォールバック）"""
        log("=== ウェザーニュース番組表取得開始 ===")
       
        # 1. Playwright Async
        programs = await self.try_playwright_scraping()
        if programs:
            filtered = self.filter_todays_schedule(programs)
            if len(filtered) >= 3:
                self.schedule_data = {
                    'programs': sorted(filtered, key=lambda x: x['time']),
                    'source': 'playwright',
                    'timestamp': datetime.now(JST).isoformat()
                }
                return self.schedule_data
       
        # 2. Selenium Stealth
        programs = self.try_selenium_scraping()
        if programs:
            filtered = self.filter_todays_schedule(programs)
            if len(filtered) >= 3:
                self.schedule_data = {
                    'programs': sorted(filtered, key=lambda x: x['time']),
                    'source': 'selenium',
                    'timestamp': datetime.now(JST).isoformat()
                }
                return self.schedule_data
       
        # 3. 完全フォールバック
        programs = self.get_fallback_schedule()
        self.schedule_data = {
            'programs': programs,
            'source': 'fallback',
            'timestamp': datetime.now(JST).isoformat()
        }
        log("完全フォールバックスケジュールを使用")
        return self.schedule_data

    def format_tweet_text(self):
        """ツイート文生成"""
        if not self.schedule_data:
            return None
       
        target_date, target_date_str = self.get_target_date_with_env_control()
        tweet_text = f"TV {target_date_str} WNL番組表\n\n"
       
        programs = self.schedule_data['programs']
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        caster_by_time = {p['time']: p['caster'] for p in programs if p['time'] in main_times}
       
        for time_str in main_times:
            caster = caster_by_time.get(time_str, '未定').replace(' ', '')
            tweet_text += f"{time_str}- {caster}\n"
       
        tweet_text += "\n#ウェザーニュース #番組表"
       
        if len(tweet_text) > 280:
            tweet_text = f"TV {target_date_str} WNL番組表\n\n"
            for time_str in main_times[:4]:
                caster = caster_by_time.get(time_str, '未定').replace(' ', '')
                tweet_text += f"{time_str}- {caster}\n"
            tweet_text += "※他は番組表参照\n\n#ウェザーニュース #番組表"
       
        return tweet_text

    def post_to_twitter(self, tweet_text):
        """Twitter投稿"""
        try:
            import tweepy
            client = tweepy.Client(
                consumer_key=os.getenv('TWITTER_API_KEY'),
                consumer_secret=os.getenv('TWITTER_API_SECRET'),
                access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
                access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET'),
                wait_on_rate_limit=True
            )
            response = client.create_tweet(text=tweet_text)
            if response.data:
                log(f"ツイート投稿成功: https://twitter.com/i/web/status/{response.data['id']}")
                return True
        except Exception as e:
            log(f"ツイート投稿エラー: {e}")
        return False

    async def run(self):
        """メイン実行"""
        try:
            schedule_data = await self.scrape_schedule()
           
            log("=== 取得されたデータ ===")
            for program in schedule_data['programs']:
                log(f" {program['time']} - {program['caster']}")
            log(f"データソース: {schedule_data['source']}")
            log("========================")
           
            tweet_text = self.format_tweet_text()
            if not tweet_text:
                log("ツイート文の生成に失敗しました")
                return False

            # 全キャスター未定ならスキップ
            if not self.has_valid_caster(schedule_data['programs']):
                log("全キャスターが未定のため、ツイートをスキップします")
                target_date, target_date_str = self.get_target_date_with_env_control()
                result = {
                    'success': False,
                    'schedule_data': schedule_data,
                    'tweet_text': tweet_text,
                    'timestamp': datetime.now(JST).isoformat(),
                    'execution_date_jst': datetime.now(JST).strftime('%Y年%m月%d日'),
                    'target_date_jst': target_date_str,
                    'skip_reason': 'all_casters_undetermined',
                    'target_mode': os.getenv('SCHEDULE_TARGET_MODE', 'auto'),
                    'threshold_hour': os.getenv('SCHEDULE_THRESHOLD_HOUR', '18')
                }
                with open('bot_result.json', 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                return False

            log("=== 生成されたツイート文 ===")
            log(tweet_text)
            log(f"文字数: {len(tweet_text)}")
            log("===========================")
           
            success = self.post_to_twitter(tweet_text)
           
            target_date, target_date_str = self.get_target_date_with_env_control()
            result = {
                'success': success,
                'schedule_data': schedule_data,
                'tweet_text': tweet_text,
                'timestamp': datetime.now(JST).isoformat(),
                'execution_date_jst': datetime.now(JST).strftime('%Y年%m月%d日'),
                'target_date_jst': target_date_str,
                'target_mode': os.getenv('SCHEDULE_TARGET_MODE', 'auto'),
                'threshold_hour': os.getenv('SCHEDULE_THRESHOLD_HOUR', '18')
            }
            with open('bot_result.json', 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
           
            log(f"=== 実行完了 ===")
            log(f"対象日: {target_date_str}")
            log(f"ツイート投稿: {'成功' if success else '失敗'}")
            return success
           
        except Exception as e:
            log(f"実行エラー: {e}")
            return False

async def main():
    log("=== ウェザーニュースボット開始（安定版）===")
    bot = WeatherNewsBot()
    success = await bot.run()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
