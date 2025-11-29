#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表スクレイピング＆Twitter投稿 統合版（2025安定化・リトライ強化版・更新対応）
"""
import os
import json
import sys
import re
import asyncio
import time
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
        self.DATA_FILE = 'schedule_data.json' # 状態保存用ファイル
        
        # リトライ設定
        self.MAX_RETRIES = 10       # 最大リトライ回数
        self.RETRY_DELAY = 60       # 待機時間（秒）
        
        log(f"現在時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")

    # --- 対象日制御 ---

    def get_target_date_with_env_control(self):
        """環境変数による対象日制御"""
        now_jst = datetime.now(JST)
        target_date_env = os.getenv('SCHEDULE_TARGET_DATE')
        
        if target_date_env:
            try:
                target_date = datetime.strptime(target_date_env, '%Y-%m-%d').replace(tzinfo=JST)
                target_date_str = target_date.strftime('%Y年%m月%d日')
                log(f"環境変数で指定された日付を使用: {target_date_str}")
                return target_date, target_date_str
            except ValueError:
                log(f"環境変数SCHEDULE_TARGET_DATEの形式が不正です: {target_date_env}")
        
        target_mode = os.getenv('SCHEDULE_TARGET_MODE', 'auto').lower()
        threshold_hour = int(os.getenv('SCHEDULE_THRESHOLD_HOUR', '18'))
        
        if target_mode == 'tomorrow':
            target_date = now_jst + timedelta(days=1)
        elif target_mode == 'today':
            target_date = now_jst
        else:  # auto mode
            if now_jst.hour >= threshold_hour:
                target_date = now_jst + timedelta(days=1)
            else:
                target_date = now_jst
        
        target_date_str = target_date.strftime('%Y年%m月%d日')
        log(f"決定された対象日: {target_date_str} (モード: {target_mode})")
        return target_date, target_date_str

    # --- スクレイピング (Playwright & Selenium) ---
    
    # ※ try_playwright_scraping と try_selenium_scraping は、文字数の都合上
    #    ユーザー提示のオリジナルコードと同一として省略します。

    async def try_playwright_scraping(self):
        # ユーザー提示のオリジナルコードの try_playwright_scraping() をここに配置
        # （インポートや実行コードはそのまま）
        try:
            from playwright.async_api import async_playwright
            log("Playwright Async でスクレイピング開始...")
            # ... (Playwrightのロジック本体) ...
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--disable-blink-features=AutomationControlled']
                )
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                page = await context.new_page()
                
                await page.goto(self.url, wait_until="networkidle", timeout=90000)
                await page.wait_for_timeout(10000)
                
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
                             // console.error('アイテム処理エラー:', error);
                        }
                    });
                    return result;
                }''')
                
                await browser.close()
                
                if schedule_data and len(schedule_data) > 0:
                    return schedule_data
                else:
                    log("Playwright: 有効なデータ取得なし")
                    return None
                    
        except Exception as e:
            log(f"Playwright エラー: {e}")
            return None

    def try_selenium_scraping(self):
        # ユーザー提示のオリジナルコードの try_selenium_scraping() をここに配置
        # （インポートや実行コードはそのまま）
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
            
            driver = uc.Chrome(options=options, headless=True)
            
            driver.set_page_load_timeout(120)
            driver.implicitly_wait(15)
            
            driver.get(self.url)
            
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CLASS_NAME, "boxStyle__item"))
            )
            
            time.sleep(15)
            
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
                    continue
            
            driver.quit()
            
            if programs:
                return programs
            else:
                log("Selenium: 有効なデータ取得なし")
                return None
                
        except Exception as e:
            log(f"Selenium エラー: {e}")
            return None

    def get_fallback_schedule(self, partial_data=None):
        """フォールバック用スケジュール"""
        # ... (既存の get_fallback_schedule のロジックはそのまま) ...
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
        # ... (既存の get_program_name_by_time のロジックはそのまま) ...
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
        """Playwright → Selenium → Fallback の順で試行し、リトライする"""
        for attempt in range(1, self.MAX_RETRIES + 1):
            log(f"--- スクレイピング試行 {attempt}/{self.MAX_RETRIES} 回目 ---")

            # 1. Playwright Async 試行
            programs = await self.try_playwright_scraping()
            if programs:
                filtered = self.filter_todays_schedule(programs)
                if len(filtered) >= 3:
                    return {
                        'programs': sorted(filtered, key=lambda x: x['time']),
                        'source': 'playwright',
                        'timestamp': datetime.now(JST).isoformat()
                    }

            # 2. Selenium Stealth 試行
            programs = self.try_selenium_scraping()
            if programs:
                filtered = self.filter_todays_schedule(programs)
                if len(filtered) >= 3:
                    return {
                        'programs': sorted(filtered, key=lambda x: x['time']),
                        'source': 'selenium',
                        'timestamp': datetime.now(JST).isoformat()
                    }

            if attempt < self.MAX_RETRIES:
                log(f"データ取得失敗またはタイムアウト。{self.RETRY_DELAY}秒後にリトライします...")
                await asyncio.sleep(self.RETRY_DELAY)
            else:
                log("全リトライ回数失敗。フォールバック処理に移行します。")

        # 3. 完全フォールバック
        programs = self.get_fallback_schedule()
        log("完全フォールバックスケジュールを使用")
        return {
            'programs': programs,
            'source': 'fallback',
            'timestamp': datetime.now(JST).isoformat()
        }

    # --- データ保存・比較ロジック ---

    def load_previous_data(self):
        """前回の保存データ（Artifactからダウンロードされたファイル）を読み込む"""
        if os.path.exists(self.DATA_FILE):
            try:
                with open(self.DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    log("過去データを読み込みました。")
                    return data
            except Exception as e:
                log(f"過去データの読み込み失敗: {e}")
        return None

    def save_current_data(self, data):
        """現在のデータをファイルに保存する（次の実行のためのArtifact化準備）"""
        try:
            with open(self.DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log("現在のデータをファイルに保存しました。")
        except Exception as e:
            log(f"データの保存失敗: {e}")

    # --- ツイート生成（更新対応版） ---

    def format_normal_tweet_text(self):
        """通常投稿用のツイート文生成"""
        if not self.schedule_data:
            return None
        
        target_date, target_date_str = self.get_target_date_with_env_control()
        tweet_text = f"📺 {target_date_str} WNL番組表\n\n"

        programs = self.schedule_data['programs']
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        caster_by_time = {p['time']: p['caster'] for p in programs if p['time'] in main_times}
        
        for time_str in main_times:
            caster = caster_by_time.get(time_str, '未定').replace(' ', '')
            tweet_text += f"{time_str}- {caster}\n"
        
        tweet_text += "\n#ウェザーニュース #番組表"
        return tweet_text

    def format_update_tweet(self, previous_progs, current_progs, target_date_str):
        """
        キャスター変更を検出した際の更新通知ツイートを生成する
        フォーマット: 05:00- キャスターB (キャスターAから変更:09:20)
        """
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        
        # 辞書化
        prev_map = {p['time']: p['caster'] for p in previous_progs if p['time'] in main_times}
        curr_map = {p['time']: p['caster'] for p in current_progs if p['time'] in main_times}
        
        tweet_lines = []
        changes_count = 0
        detect_time = datetime.now(JST).strftime('%H:%M') # 検出時刻

        # 全時間帯をチェック
        for time_str in main_times:
            prev_caster = prev_map.get(time_str)
            curr_caster = curr_map.get(time_str)
            
            # --- 変更判定ロジック ---
            # 1. 現在のデータがあり (放送終了で消えていない)、
            # 2. 過去のデータもあり、
            # 3. キャスター名が異なる
            if curr_caster and prev_caster and curr_caster != prev_caster:
                # 【変更あり】新しいフォーマットを適用
                line = f"{time_str}- {curr_caster} ({prev_caster}から変更:{detect_time})"
                changes_count += 1
                log(f"変更検出: {time_str} {prev_caster} -> {curr_caster}")
            elif curr_caster:
                # 【変更なし】現在のデータを表示
                line = f"{time_str}- {curr_caster}"
            elif prev_caster:
                # 【データ消失】現在のデータが取得できない場合、過去の情報を表示維持
                line = f"{time_str}- {prev_caster}"
            else:
                continue
                
            tweet_lines.append(line)

        if changes_count > 0:
            tweet_text = f"📢 【番組表変更のお知らせ】\n\n📺 {target_date_str} WNL番組表(更新)\n\n"
            tweet_text += "\n".join(tweet_lines)
            tweet_text += "\n\n#ウェザーニュース #番組表"
            
            # 文字数オーバー対策
            if len(tweet_text) > 280:
                tweet_text = f"📢 WNL番組表変更(更新)\n\n"
                tweet_text += "\n".join(tweet_lines[:4])
                tweet_text += "\n...\n\n#ウェザーニュース #番組表"

            return tweet_text
            
        return None

    def post_to_twitter(self, tweet_text):
        """Twitter投稿"""
        try:
            import tweepy
            # ... (既存の認証ロジックはそのまま) ...
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

    # --- 実行モード ---

    async def run(self):
        """メイン実行（初回投稿・通常モード）"""
        schedule_data = await self.scrape_schedule()
        self.schedule_data = schedule_data
        
        target_date, target_date_str = self.get_target_date_with_env_control()
        schedule_data['target_date_jst'] = target_date_str # 日付情報を保存用に付与
        
        log("=== 取得されたデータ ===")
        for program in schedule_data['programs']:
             log(f" {program['time']} - {program['caster']}")
        log("========================")

        # 1. 全キャスター未定ならスキップ
        if not self.has_valid_caster(schedule_data['programs']):
            log("全キャスターが未定のため、ツイートをスキップします")
            self.save_current_data(schedule_data) # 空でも保存して次回比較対象にする
            return False

        # 2. ツイート生成
        tweet_text = self.format_normal_tweet_text()
        
        # 3. 投稿
        success = self.post_to_twitter(tweet_text)
        
        # 4. 状態保存（次回監視実行のためのArtifactに備える）
        self.save_current_data(schedule_data)
        
        log(f"=== 実行完了 (通常) ===")
        log(f"ツイート投稿: {'成功' if success else '失敗'}")
        return success

    async def run_check_mode(self):
        """監視・更新モード"""
        log("=== 番組表 監視・更新モード開始 ===")
        
        # 1. 前回の状態を読み込む (Artifactからダウンロードされているはず)
        previous_data = self.load_previous_data()
        
        if not previous_data:
            log("過去データが存在しません。強制的に通常スクレイピングモードに移行します。")
            return await self.run()

        # 2. 現在の状態をスクレイピング
        current_data = await self.scrape_schedule()
        if not current_data:
            log("現在のデータが取得できませんでした。スキップします。")
            return False

        # 3. 差分チェックとツイート生成
        target_date_str = previous_data.get('target_date_jst', '日付不明')
        tweet_text = self.format_update_tweet(
            previous_data['programs'], 
            current_data['programs'],
            target_date_str
        )

        # 4. 変更があった場合のみツイートし、状態を更新
        if tweet_text:
            log("変更を検出しました。更新ツイートを投稿します。")
            
            if self.post_to_twitter(tweet_text):
                # 投稿成功: 最新データを「正」として保存（Artifact上書き準備）
                current_data['target_date_jst'] = target_date_str
                self.save_current_data(current_data)
                log("状態ファイルを更新しました。")
                return True
            else:
                log("ツイート投稿に失敗したため、状態ファイルは更新しません。再リトライ待ち。")
                return False
        else:
            log("変更は検出されませんでした。状態ファイルは更新しません。")
            return True

async def main():
    log("=== ウェザーニュースボット開始 ===")
    
    # 環境変数 EXECUTION_MODE で実行モードを切り替え
    execution_mode = os.getenv('EXECUTION_MODE', 'normal').lower()
    log(f"実行モード: {execution_mode}")
    
    bot = WeatherNewsBot()
    
    if execution_mode == 'check':
        success = await bot.run_check_mode()
    else:
        success = await bot.run()
        
    # 実行結果をJSONとして出力（GitHub Actionsのログなどで参照可能）
    if bot.schedule_data:
        bot_result = {
            'success': success,
            'source': bot.schedule_data.get('source'),
            'timestamp': datetime.now(JST).isoformat(),
            'target_date_jst': bot.schedule_data.get('target_date_jst')
        }
        with open('bot_result.json', 'w', encoding='utf-8') as f:
            json.dump(bot_result, f, ensure_ascii=False, indent=2)

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
