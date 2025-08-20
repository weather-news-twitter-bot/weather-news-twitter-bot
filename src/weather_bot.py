#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表スクレイピング＆Twitter投稿 統合版
Playwright → Selenium → Pyppeteer の順で試行し、最初に成功したデータでツイート投稿
環境変数による対象日制御対応版
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
        """
        環境変数を使用した対象日制御
        
        環境変数:
            SCHEDULE_TARGET_MODE: 'today', 'tomorrow', 'auto' (デフォルト: 'auto')
            SCHEDULE_THRESHOLD_HOUR: auto mode時の判定時刻 (デフォルト: 18)
            SCHEDULE_TARGET_DATE: 明示的な日付指定 (YYYY-MM-DD形式、優先度最高)
        
        Returns:
            tuple: (対象日のdatetimeオブジェクト, 表示用文字列)
        """
        now_jst = datetime.now(JST)
        
        # 明示的な日付指定がある場合
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
        
        # モード指定
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
                
                # JavaScript で番組表データを正確に抽出（改善版）
                schedule_data = page.evaluate('''() => {
                    const result = [];
                    const timeMap = new Map(); // 時間帯ごとの最新情報を保持
                    
                    // .boxStyle__item 内の番組情報を抽出
                    const items = document.querySelectorAll('.boxStyle__item');
                    
                    items.forEach(item => {
                        try {
                            // 時間情報を取得 (例: "05:00- ", "17:00- ただいま放送中")
                            const timeElements = item.querySelectorAll('p');
                            if (!timeElements || timeElements.length === 0) return;
                            
                            const timeText = timeElements[0].textContent.trim();
                            const timeMatch = timeText.match(/(\\d{2}:\\d{2})-/);
                            if (!timeMatch) return;
                            
                            const timeStr = timeMatch[1];
                            
                            // 放送中かどうかをチェック
                            const isLive = timeText.includes('ただいま放送中') || timeText.includes('放送中');
                            
                            // 番組名を取得 (例: "ウェザーニュースLiVE・モーニング")
                            let programName = "ウェザーニュースLiVE";
                            const programElements = item.querySelectorAll('p.bold');
                            if (programElements.length > 0) {
                                programName = programElements[0].textContent.trim();
                            }
                            
                            // キャスターリンクを探す (href に "caster" を含む)
                            const casterLinks = item.querySelectorAll('a[href*="caster"]');
                            
                            if (casterLinks.length > 0) {
                                const casterLink = casterLinks[0];
                                const casterName = casterLink.textContent.trim();
                                const casterUrl = casterLink.href;
                                
                                // 有効なキャスター名かチェック (日本語文字を含む、適切な長さ)
                                if (casterName && 
                                    casterName.length >= 2 && 
                                    casterName.length <= 20 &&
                                    /[ぁ-んァ-ヶ一-龯]/.test(casterName)) {
                                    
                                    const itemData = {
                                        time: timeStr,
                                        caster: casterName,
                                        program: programName,
                                        profile_url: casterUrl,
                                        isLive: isLive
                                    };
                                    
                                    // 時間帯ごとに最新情報を更新
                                    // 放送中でない項目を優先（翌日の番組として扱う）
                                    if (!timeMap.has(timeStr) || (!isLive && timeMap.get(timeStr).isLive)) {
                                        timeMap.set(timeStr, itemData);
                                    }
                                }
                            }
                            
                        } catch (error) {
                            // エラーは無視して次へ
                        }
                    });
                    
                    // Mapから配列に変換
                    timeMap.forEach(item => {
                        result.push({
                            time: item.time,
                            caster: item.caster,
                            program: item.program,
                            profile_url: item.profile_url
                        });
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
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
            
            log("Selenium でスクレイピング開始...")
            
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # ChromeDriverの自動管理
            try:
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
            except:
                # フォールバック: システムのchromedriver
                driver = webdriver.Chrome(options=chrome_options)
            
            driver.set_page_load_timeout(60)
            
            driver.get(self.url)
            
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CLASS_NAME, "boxStyle__item"))
            )
            
            import time
            time.sleep(5)
            
            schedule_items = driver.find_elements(By.CLASS_NAME, "boxStyle__item")
            time_map = {}  # 時間帯ごとの最新情報を保持
            
            for item in schedule_items:
                try:
                    # 時間の取得 (最初の p タグ)
                    time_elements = item.find_elements(By.TAG_NAME, "p")
                    if not time_elements:
                        continue
                    
                    time_text = time_elements[0].text.strip()
                    time_match = re.search(r'(\d{2}:\d{2})-', time_text)
                    if not time_match:
                        continue
                    
                    time_str = time_match.group(1)
                    
                    # 放送中かどうかをチェック
                    is_live = 'ただいま放送中' in time_text or '放送中' in time_text
                    
                    # 番組名の取得 (p.bold 要素)
                    program_name = "ウェザーニュースLiVE"
                    try:
                        program_elements = item.find_elements(By.CSS_SELECTOR, "p.bold")
                        if program_elements:
                            program_name = program_elements[0].text.strip()
                    except:
                        pass
                    
                    # キャスターリンクを探す (href に caster を含むもの)
                    caster_links = item.find_elements(By.CSS_SELECTOR, "a[href*='caster']")
                    
                    for caster_link in caster_links:
                        try:
                            caster_name = caster_link.text.strip()
                            caster_url = caster_link.get_attribute('href')
                            
                            # 有効なキャスター名かチェック
                            if (caster_name and 
                                len(caster_name) >= 2 and 
                                len(caster_name) <= 20 and
                                re.search(r'[ぁ-んァ-ヶ一-龯]', caster_name)):
                                
                                item_data = {
                                    'time': time_str,
                                    'caster': caster_name,
                                    'program': program_name,
                                    'profile_url': caster_url,
                                    'is_live': is_live
                                }
                                
                                # 時間帯ごとに最新情報を更新
                                # 放送中でない項目を優先（翌日の番組として扱う）
                                if time_str not in time_map or (not is_live and time_map[time_str].get('is_live', False)):
                                    time_map[time_str] = item_data
                                    log(f"Selenium 抽出: {time_str} - {caster_name} {'(放送中)' if is_live else ''}")
                                
                                break  # 1つの時間帯につき1人のキャスター
                        except:
                            continue
                
                except Exception as e:
                    continue
            
            driver.quit()
            
            # 結果を配列に変換
            programs = []
            for time_str, item_data in time_map.items():
                programs.append({
                    'time': item_data['time'],
                    'caster': item_data['caster'],
                    'program': item_data['program'],
                    'profile_url': item_data['profile_url']
                })
            
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
            
            # JavaScriptでデータを抽出（改善版）
            schedule_items = await page.evaluate('''() => {
                const result = [];
                const timeMap = new Map(); // 時間帯ごとの最新情報を保持
                const items = document.querySelectorAll('.boxStyle__item');
                
                items.forEach(item => {
                    try {
                        // 時間情報を取得 (最初の p 要素)
                        const timeElements = item.querySelectorAll('p');
                        if (!timeElements || timeElements.length === 0) return;
                        
                        const timeText = timeElements[0].textContent.trim();
                        const timeMatch = timeText.match(/(\\d{2}:\\d{2})-/);
                        if (!timeMatch) return;
                        
                        const timeStr = timeMatch[1];
                        
                        // 放送中かどうかをチェック
                        const isLive = timeText.includes('ただいま放送中') || timeText.includes('放送中');
                        
                        // 番組名を取得 (p.bold 要素)
                        let programName = "ウェザーニュースLiVE";
                        const programElements = item.querySelectorAll('p.bold');
                        if (programElements.length > 0) {
                            programName = programElements[0].textContent.trim();
                        }
                        
                        // キャスターリンクを探す (href に "caster" を含む)
                        const casterLinks = item.querySelectorAll('a[href*="caster"]');
                        
                        if (casterLinks.length > 0) {
                            const casterLink = casterLinks[0];
                            const casterName = casterLink.textContent.trim();
                            const casterUrl = casterLink.href;
                            
                            // 有効なキャスター名かチェック
                            if (casterName && 
                                casterName.length >= 2 && 
                                casterName.length <= 20 &&
                                /[ぁ-んァ-ヶ一-龯]/.test(casterName)) {
                                
                                const itemData = {
                                    time: timeStr,
                                    caster: casterName,
                                    program: programName,
                                    profile_url: casterUrl,
                                    isLive: isLive
                                };
                                
                                // 時間帯ごとに最新情報を更新
                                // 放送中でない項目を優先（翌日の番組として扱う）
                                if (!timeMap.has(timeStr) || (!isLive && timeMap.get(timeStr).isLive)) {
                                    timeMap.set(timeStr, itemData);
                                }
                            }
                        }
                        
                    } catch (error) {
                        // エラーは無視
                    }
                });
                
                // Mapから配列に変換
                timeMap.forEach(item => {
                    result.push({
                        time: item.time,
                        caster: item.caster,
                        program: item.program,
                        profile_url: item.profile_url
                    });
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
        """フォールバック用スケジュール（部分データがあれば活用、不足分は「未定」）"""
        log("フォールバック: スケジュール生成")
        
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        programs = []
        
        # 部分的に取得できたデータがあれば活用
        existing_casters = {}
        
        if partial_data:
            log(f"部分データを活用: {len(partial_data)}件")
            for item in partial_data:
                if item.get('time') in main_times:
                    existing_casters[item['time']] = item.get('caster', '未定')
        
        # 各時間帯にキャスターを割り当て
        for time_str in main_times:
            if time_str in existing_casters:
                # 実際に取得できたデータを使用
                caster_name = existing_casters[time_str]
                log(f"実データ使用: {time_str} - {caster_name}")
            else:
                # 取得できなかった場合は「未定」
                caster_name = '未定'
                log(f"未定: {time_str}")
            
            programs.append({
                'time': time_str,
                'caster': caster_name,
                'program': self.get_program_name_by_time(time_str)
            })
        
        return programs
    
    def get_program_info_by_time(self, time_str):
        """時間帯から番組名とアイコンを取得"""
        try:
            hour = int(time_str.split(':')[0])
            
            program_info = {
                5: {
                    'name': 'モーニング',
                    'icon': '🌅',
                    'full_name': 'ウェザーニュースLiVE・モーニング'
                },
                8: {
                    'name': 'サンシャイン',
                    'icon': '☀️',
                    'full_name': 'ウェザーニュースLiVE・サンシャイン'
                },
                11: {
                    'name': 'コーヒータイム',
                    'icon': '☕',
                    'full_name': 'ウェザーニュースLiVE・コーヒータイム'
                },
                14: {
                    'name': 'アフタヌーン',
                    'icon': '🌞',
                    'full_name': 'ウェザーニュースLiVE・アフタヌーン'
                },
                17: {
                    'name': 'イブニング',
                    'icon': '🌆',
                    'full_name': 'ウェザーニュースLiVE・イブニング'
                },
                20: {
                    'name': 'ムーン',
                    'icon': '🌙',
                    'full_name': 'ウェザーニュースLiVE・ムーン'
                }
            }
            
            return program_info.get(hour, {
                'name': 'LiVE',
                'icon': '📺',
                'full_name': 'ウェザーニュースLiVE'
            })
        except:
            return {
                'name': 'LiVE',
                'icon': '📺',
                'full_name': 'ウェザーニュースLiVE'
            }
    
    def get_program_name_by_time(self, time_str):
        """時間帯から番組名を取得（従来の関数、互換性のため残す）"""
        program_info = self.get_program_info_by_time(time_str)
        return program_info['full_name']
    
    def filter_todays_schedule(self, programs):
        """今日の番組のみを抽出（重複除去）"""
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        
        # 時間帯別にキャスターを整理（最初に見つかったものを採用）
        time_caster_map = {}
        for program in programs:
            time_key = program['time']
            if time_key in main_times and time_key not in time_caster_map:
                time_caster_map[time_key] = program
        
        # 今日の番組として返す
        filtered_programs = []
        for time_str in main_times:
            if time_str in time_caster_map:
                filtered_programs.append(time_caster_map[time_str])
        
        return filtered_programs

    async def scrape_schedule(self):
        """スケジュール取得（複数手法を順次試行）"""
        log("=== ウェザーニュース番組表取得開始 ===")
        
        all_attempts_data = []  # 全ての試行で得られたデータを保存
        
        # 1. Playwright を試行
        programs = self.try_playwright_scraping()
        if programs:
            all_attempts_data.extend(programs)
            # 重複除去と今日の番組のみフィルタリング
            filtered_programs = self.filter_todays_schedule(programs)
            if len(filtered_programs) >= 3:  # 十分なデータが取得できた場合
                self.schedule_data = {
                    'programs': sorted(filtered_programs, key=lambda x: x['time']),
                    'source': 'playwright',
                    'timestamp': datetime.now(JST).isoformat()
                }
                return self.schedule_data
        
        # 2. Selenium を試行
        programs = self.try_selenium_scraping()
        if programs:
            all_attempts_data.extend(programs)
            filtered_programs = self.filter_todays_schedule(programs)
            if len(filtered_programs) >= 3:  # 十分なデータが取得できた場合
                self.schedule_data = {
                    'programs': sorted(filtered_programs, key=lambda x: x['time']),
                    'source': 'selenium',
                    'timestamp': datetime.now(JST).isoformat()
                }
                return self.schedule_data
        
        # 3. Pyppeteer を試行
        programs = await self.try_pyppeteer_scraping()
        if programs:
            all_attempts_data.extend(programs)
            filtered_programs = self.filter_todays_schedule(programs)
            if len(filtered_programs) >= 3:  # 十分なデータが取得できた場合
                self.schedule_data = {
                    'programs': sorted(filtered_programs, key=lambda x: x['time']),
                    'source': 'pyppeteer',
                    'timestamp': datetime.now(JST).isoformat()
                }
                return self.schedule_data
        
        # 4. 部分データの統合を試行
        if all_attempts_data:
            log(f"部分データ統合: 全{len(all_attempts_data)}件から最適化")
            
            # 重複除去と今日の番組のみフィルタリング
            filtered_data = self.filter_todays_schedule(all_attempts_data)
            
            if len(filtered_data) >= 2:  # 最低2件あれば使用
                # 不足分をフォールバックで補完
                programs = self.get_fallback_schedule(filtered_data)
                self.schedule_data = {
                    'programs': programs,
                    'source': 'consolidated_partial',
                    'timestamp': datetime.now(JST).isoformat()
                }
                log(f"部分データ統合完了: {len(filtered_data)}件の実データ + フォールバック")
                return self.schedule_data
        
        # 5. 完全フォールバック
        programs = self.get_fallback_schedule()
        self.schedule_data = {
            'programs': programs,
            'source': 'fallback',
            'timestamp': datetime.now(JST).isoformat()
        }
        log("完全フォールバックスケジュールを使用")
        return self.schedule_data
    
    def format_tweet_text(self):
        """ツイート文を生成（環境変数制御対応版）"""
        if not self.schedule_data:
            return None
        
        # 対象日を取得（環境変数制御）
        target_date, target_date_str = self.get_target_date_with_env_control()
        
        tweet_text = f"📺 {target_date_str} WNL番組表\n\n"
        
        programs = self.schedule_data['programs']
        main_times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        
        # 時間帯別にキャスターを整理
        caster_by_time = {}
        for program in programs:
            time_key = program['time']
            if time_key in main_times:
                caster_by_time[time_key] = program['caster']
        
        # ツイート本文を構築（シンプル形式）
        program_lines = []
        for time_str in main_times:
            if time_str in caster_by_time:
                caster = caster_by_time[time_str]
                # スペースを除去してよりコンパクトに
                caster_clean = caster.replace(' ', '')
                program_lines.append(f"{time_str}- {caster_clean}")
            else:
                program_lines.append(f"{time_str}- 未定")
        
        tweet_text += "\n".join(program_lines)
        tweet_text += "\n\n#ウェザーニュース #番組表"
        
        # 文字数制限チェック（280文字）
        if len(tweet_text) > 280:
            log(f"ツイート文が長すぎます({len(tweet_text)}文字)。短縮します。")
            # 基本情報のみに短縮
            tweet_text = f"📺 {target_date_str} WNL番組表\n\n"
            
            # 最初の4つの時間帯のみ表示して文字数を抑える
            for time_str in main_times[:4]:
                if time_str in caster_by_time:
                    caster = caster_by_time[time_str].replace(' ', '')
                    tweet_text += f"{time_str}- {caster}\n"
                else:
                    tweet_text += f"{time_str}- 未定\n"
            
            tweet_text += "※他の時間帯は番組表をご確認ください\n\n#ウェザーニュース #番組表"
        
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
