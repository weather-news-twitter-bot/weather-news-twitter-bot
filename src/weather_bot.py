#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表スクレイピング＆Twitter投稿 統合版
機能: リトライ/Playwright&Seleniumフォールバック/更新監視/正確な日付判定/更新ツイート
"""
import os
import json
import sys
import re
import asyncio
import time
from datetime import datetime, timezone, timedelta

# 日本時間のタイムゾーン設定
JST = timezone(timedelta(hours=9))
MAIN_TIMES = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']

def log(message):
    """ログ出力"""
    now_jst = datetime.now(JST)
    print(f"[{now_jst.strftime('%H:%M:%S')}] {message}", file=sys.stderr)

class WeatherNewsBot:
    def __init__(self):
        self.url = "https://weathernews.jp/wnl/timetable.html"
        self.schedule_data = None
        self.DATA_FILE = 'schedule_data.json'
        self.MAX_RETRIES = 10
        self.RETRY_DELAY = 60
        log(f"初期化完了。現在時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")

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
    
    async def try_playwright_scraping(self):
        try:
            from playwright.async_api import async_playwright
            log("Playwright Async でスクレイピング開始...")
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
                context = await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36', viewport={'width': 1920, 'height': 1080})
                page = await context.new_page()
                
                await page.goto(self.url, wait_until="networkidle", timeout=90000)
                await page.wait_for_timeout(5000)
                
                # 全ての番組枠を抽出（日付で切り分けず）
                all_programs = await page.evaluate(f'''() => {{
                    const result = [];
                    const items = document.querySelectorAll('.boxStyle__item');
                    const mainTimes = {MAIN_TIMES}; 
                    
                    items.forEach(item => {{
                        try {{
                            const timeElements = item.querySelectorAll('p');
                            if (!timeElements || timeElements.length === 0) return;
                            
                            const timeText = timeElements[0].textContent.trim();
                            const timeMatch = timeText.match(/(\\d{{2}}:\\d{{2}})-/);
                            if (!timeMatch) return;
                            
                            const timeStr = timeMatch[1];
                            
                            let programName = "ウェザーニュースLiVE";
                            const programElements = item.querySelectorAll('p.bold');
                            if (programElements.length > 0) {{
                                programName = programElements[0].textContent.trim();
                            }}
                            
                            if (mainTimes.includes(timeStr)) {{
                                const casterLinks = item.querySelectorAll('a[href*="caster"]');
                                
                                let casterName = '未定';
                                let casterUrl = '';
                                if (casterLinks.length > 0) {{
                                    const casterLink = casterLinks[0];
                                    casterName = casterLink.textContent.trim();
                                    casterUrl = casterLink.href;
                                }}
                                
                                result.push({{
                                    time: timeStr,
                                    caster: casterName,
                                    program: programName,
                                    profile_url: casterUrl
                                }});
                            }}
                        }} catch (error) {{
                             // console.error('アイテム処理エラー:', error);
                        }}
                    }});
                    return result;
                }}''')
                
                await browser.close()
                
                if all_programs and len(all_programs) > 0:
                    return all_programs
                else:
                    log("Playwright: 有効なデータ取得なし")
                    return None
                    
        except Exception as e:
            log(f"Playwright エラー: {e}")
            return None

    def try_selenium_scraping(self):
        try:
            import undetected_chromedriver as uc
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            log("Selenium Stealth でスクレイピング開始...")
            
            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            
            driver = uc.Chrome(options=options, headless=True)
            driver.set_page_load_timeout(120)
            driver.implicitly_wait(15)
            driver.get(self.url)
            
            WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.CLASS_NAME, "boxStyle__item")))
            time.sleep(15)
            
            schedule_items = driver.find_elements(By.CLASS_NAME, "boxStyle__item")
            all_programs = []
            
            for item in schedule_items:
                try:
                    time_elements = item.find_elements(By.TAG_NAME, "p")
                    if not time_elements: continue
                    
                    time_text = time_elements[0].text.strip()
                    time_match = re.search(r'(\d{2}:\d{2})-', time_text)
                    if not time_match: continue
                    
                    time_str = time_match.group(1)
                    
                    if time_str in MAIN_TIMES:
                        program_name = "ウェザーニュースLiVE"
                        program_elements = item.find_elements(By.CSS_SELECTOR, "p.bold")
                        if program_elements:
                            program_name = program_elements[0].text.strip()
                        
                        caster_links = item.find_elements(By.CSS_SELECTOR, "a[href*='caster']")
                        
                        caster_name = '未定'
                        caster_url = ''
                        if caster_links:
                            caster_link = caster_links[0]
                            caster_name = caster_link.text.strip()
                            caster_url = caster_link.get_attribute('href')
                            
                        all_programs.append({
                            'time': time_str,
                            'caster': caster_name,
                            'program': program_name,
                            'profile_url': caster_url
                        })
                except Exception as e:
                    continue
            
            driver.quit()
            
            if all_programs:
                return all_programs
            else:
                log("Selenium: 有効なデータ取得なし")
                return None
                
        except Exception as e:
            log(f"Selenium エラー: {e}")
            return None

    def get_program_name_by_time(self, time_str):
        program_info = {
            '05:00': 'ウェザーニュースLiVE・モーニング',
            '08:00': 'ウェザーニュースLiVE・サンシャイン',
            '11:00': 'ウェザーニュースLiVE・コーヒータイム',
            '14:00': 'ウェザーニュースLiVE・アフタヌーン',
            '17:00': 'ウェザーニュースLiVE・イブニング',
            '20:00': 'ウェザーニュースLiVE・ムーン'
        }
        return program_info.get(time_str, 'ウェザーニュースLiVE')

    def split_schedule_by_date(self, all_programs):
        """
        サイト上の最初の '05:00' を境界線として、番組表を「今日」と「明日」に分割する
        """
        today_programs = []
        tomorrow_programs = []
        found_tomorrow_start = False
        
        # サイトは降順（未来ほど上）の場合と、今日→明日で流れる場合があるため、
        # 取得したデータは既に時間順に並んでいる前提（スクレイピング順）で処理
        
        for program in all_programs:
            if program['time'] == '05:00':
                # 2回目の '05:00' が見つかったら、そこからを「明日」のデータとする
                if found_tomorrow_start:
                    tomorrow_programs.append(program)
                else:
                    # 1回目の '05:00' は、日付の切れ目と判断し、次のデータを「明日」とする
                    found_tomorrow_start = True
                    today_programs.append(program) # 1回目の05:00は今日に含める (05:00-翌05:00が1日分)
            elif not found_tomorrow_start:
                today_programs.append(program)
            else:
                tomorrow_programs.append(program)

        # 取得できたデータによって today/tomorrow の意味が変わるため、
        # 最終的に長い方を today_programs として返す（データが多い方を優先）
        if len(tomorrow_programs) > len(today_programs):
            # 例: 今が深夜で、明日の方が多く取れた場合
            return tomorrow_programs, today_programs
        else:
            return today_programs, tomorrow_programs


    def get_fallback_schedule(self):
        """完全フォールバック用スケジュール"""
        log("フォールバック: スケジュール生成")
        programs = []
        for time_str in MAIN_TIMES:
            programs.append({
                'time': time_str,
                'caster': '未定',
                'program': self.get_program_name_by_time(time_str)
            })
        return programs

    async def scrape_schedule(self):
        """Playwright → Selenium → Fallback の順で試行し、リトライする"""
        all_programs = None
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            log(f"--- スクレイピング試行 {attempt}/{self.MAX_RETRIES} 回目 ---")

            programs = await self.try_playwright_scraping()
            if programs:
                all_programs = programs
                break

            programs = self.try_selenium_scraping()
            if programs:
                all_programs = programs
                break
            
            if attempt < self.MAX_RETRIES:
                log(f"データ取得失敗またはタイムアウト。{self.RETRY_DELAY}秒後にリトライします...")
                await asyncio.sleep(self.RETRY_DELAY)
            else:
                log("全リトライ回数失敗。フォールバック処理に移行します。")
                
        if all_programs:
            # 取得したデータを「今日」と「明日」に分割
            today_data, tomorrow_data = self.split_schedule_by_date(all_programs)
            
            target_date, target_date_str = self.get_target_date_with_env_control()
            
            # ターゲット日を基準にデータを選択
            is_tomorrow_target = (target_date.date() - datetime.now(JST).date()).days >= 1
            
            if is_tomorrow_target:
                final_programs = tomorrow_data
                log(f"ターゲット日({target_date_str})が翌日のため、翌日の番組データを選択。")
            else:
                final_programs = today_data
                log(f"ターゲット日({target_date_str})が本日のため、本日の番組データを選択。")
                
            # 取得したデータが空だった場合の最終フォールバック
            if not final_programs:
                 log("ターゲット日のデータが空でした。完全フォールバックに移行。")
                 final_programs = self.get_fallback_schedule()

            return {
                'programs': sorted(final_programs, key=lambda x: x['time']),
                'source': 'web_scrape',
                'timestamp': datetime.now(JST).isoformat()
            }

        # 3. 完全フォールバック
        return {
            'programs': self.get_fallback_schedule(),
            'source': 'fallback',
            'timestamp': datetime.now(JST).isoformat()
        }

    # --- データ保存・比較ロジック ---

    def load_previous_data(self):
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
        try:
            with open(self.DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log("現在のデータをファイルに保存しました。")
        except Exception as e:
            log(f"データの保存失敗: {e}")

    # --- ツイート生成（更新対応版） ---

    def has_valid_caster(self, programs):
        """実在のキャスター名があるか判定（未定以外）"""
        return any(
            p['caster'] and p['caster'] != '未定' and 
            len(p['caster']) >= 2 and 
            re.search(r'[ぁ-んァ-ヶ一-龯]', p['caster'])
            for p in programs
        )

    def format_normal_tweet_text(self):
        """通常投稿用のツイート文生成"""
        if not self.schedule_data: return None
        
        target_date, target_date_str = self.get_target_date_with_env_control()
        tweet_text = f"📺 {target_date_str} WNL番組表\n\n"

        programs = self.schedule_data['programs']
        caster_by_time = {p['time']: p['caster'] for p in programs}
        
        for time_str in MAIN_TIMES:
            caster = caster_by_time.get(time_str, '未定').replace(' ', '')
            tweet_text += f"{time_str}- {caster}\n"
        
        tweet_text += "\n#ウェザーニュース #番組表"
        return tweet_text

    def format_update_tweet(self, previous_progs, current_progs, target_date_str):
        """
        キャスター変更を検出した際の更新通知ツイートを生成する
        フォーマット: 05:00- キャスターB (キャスターAから変更:09:20)
        """
        prev_map = {p['time']: p['caster'] for p in previous_progs}
        curr_map = {p['time']: p['caster'] for p in current_progs}
        
        tweet_lines = []
        changes_count = 0
        detect_time = datetime.now(JST).strftime('%H:%M')

        for time_str in MAIN_TIMES:
            prev_caster = prev_map.get(time_str)
            curr_caster = curr_map.get(time_str)
            
            # 1. 変更判定: 現在のデータがあり、過去のデータと異なるとき
            if curr_caster and prev_caster and curr_caster != prev_caster:
                # 【変更あり】
                line = f"{time_str}- {curr_caster} ({prev_caster}から変更:{detect_time})"
                changes_count += 1
                log(f"変更検出: {time_str} {prev_caster} -> {curr_caster}")
            elif curr_caster:
                # 【変更なし】現在のデータを表示
                line = f"{time_str}- {curr_caster}"
            elif prev_caster:
                # 【データ消失】現在のデータが取得できない場合、過去の情報を表示維持
                # (放送終了時刻は超えていないがサイトから消えた場合を想定)
                line = f"{time_str}- {prev_caster}"
            else:
                continue
                
            tweet_lines.append(line)

        if changes_count > 0:
            tweet_text = f"📢 【番組表変更のお知らせ】\n\n📺 {target_date_str} WNL番組表(更新)\n\n"
            tweet_text += "\n".join(tweet_lines)
            tweet_text += "\n\n#ウェザーニュース #番組表"
            return tweet_text
            
        return None

    # --- 実行モード ---

    async def run(self):
        """メイン実行（初回投稿・通常モード）"""
        target_date, target_date_str = self.get_target_date_with_env_control()
        schedule_data = await self.scrape_schedule()
        
        self.schedule_data = schedule_data
        schedule_data['target_date_jst'] = target_date_str
        
        log("=== 取得されたデータ ===")
        for program in schedule_data['programs']:
             log(f" {program['time']} - {program['caster']}")
        log("========================")

        if not self.has_valid_caster(schedule_data['programs']):
            log("有効なキャスター情報がないため、ツイートをスキップします")
            self.save_current_data(schedule_data)
            return False

        tweet_text = self.format_normal_tweet_text()
        success = self.post_to_twitter(tweet_text)
        
        self.save_current_data(schedule_data)
        
        log(f"=== 実行完了 (通常) ===")
        log(f"ツイート投稿: {'成功' if success else '失敗'}")
        return success

    async def run_check_mode(self):
        """監視・更新モード"""
        log("=== 番組表 監視・更新モード開始 ===")
        
        previous_data = self.load_previous_data()
        
        if not previous_data:
            log("過去データが存在しません。強制的に通常モードで実行します。")
            return await self.run()

        current_data = await self.scrape_schedule()
        if not current_data:
            log("現在のデータが取得できませんでした。スキップします。")
            return False

        target_date_str = previous_data.get('target_date_jst', '日付不明')
        tweet_text = self.format_update_tweet(
            previous_data['programs'], 
            current_data['programs'],
            target_date_str
        )
        self.schedule_data = current_data # ログ出力用に設定

        if tweet_text:
            log("変更を検出しました。更新ツイートを投稿します。")
            
            if self.post_to_twitter(tweet_text):
                current_data['target_date_jst'] = target_date_str
                self.save_current_data(current_data)
                log("状態ファイルを更新しました。")
                return True
            else:
                log("ツイート投稿に失敗したため、状態ファイルは更新しません。再リトライ待ち。")
                return False
        else:
            log("変更は検出されませんでした。")
            return True

async def main():
    log("=== ウェザーニュースボット開始 ===")
    
    execution_mode = os.getenv('EXECUTION_MODE', 'normal').lower()
    log(f"実行モード: {execution_mode}")
    
    bot = WeatherNewsBot()
    
    if execution_mode == 'check':
        success = await bot.run_check_mode()
    else:
        success = await bot.run()
        
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
    # Windows環境などで実行する場合は、asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()) が必要になる場合があります。
    asyncio.run(main())
