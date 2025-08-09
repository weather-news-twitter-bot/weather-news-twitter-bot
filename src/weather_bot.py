#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表スクレイピング＆Twitter投稿 軽量版
Playwrightのみ使用、フォールバック機能付き
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
        
    def try_playwright_scraping(self):
        """Playwright でスクレイピングを試行（強化版）"""
        try:
            from playwright.sync_api import sync_playwright
            
            log("Playwright でスクレイピング開始...")
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                page.set_extra_http_headers({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                })
                
                log(f"ページアクセス開始: {self.url}")
                
                # より確実なページ読み込み
                page.goto(self.url, wait_until="networkidle", timeout=60000)
                log("基本読み込み完了")
                
                # 要素が確実に読み込まれるまで待機
                try:
                    page.wait_for_selector('.boxStyle__item', timeout=30000)
                    log("番組表要素の読み込み確認")
                except:
                    log("番組表要素の待機タイムアウト")
                
                # 追加の待機時間（JavaScriptの実行完了を待つ）
                page.wait_for_timeout(10000)
                log("追加待機完了")
                
                # デバッグ: ページタイトルを確認
                title = page.title()
                log(f"ページタイトル: {title}")
                
                # デバッグ: .boxStyle__item の数を確認
                item_count = page.evaluate('document.querySelectorAll(".boxStyle__item").length')
                log(f"検出された .boxStyle__item の数: {item_count}")
                
                # JavaScript で番組表データを正確に抽出
                schedule_data = page.evaluate('''() => {
                    const result = [];
                    console.log("JavaScript実行開始");
                    
                    // .boxStyle__item 内の番組情報を抽出
                    const items = document.querySelectorAll('.boxStyle__item');
                    console.log("検出されたアイテム数:", items.length);
                    
                    items.forEach((item, index) => {
                        try {
                            console.log(`アイテム ${index} 処理開始`);
                            
                            // 時間情報を取得 (例: "05:00- ", "08:00- ")
                            const timeElements = item.querySelectorAll('p');
                            if (!timeElements || timeElements.length === 0) {
                                console.log(`アイテム ${index}: p要素なし`);
                                return;
                            }
                            
                            const timeText = timeElements[0].textContent.trim();
                            console.log(`アイテム ${index}: 時間テキスト = "${timeText}"`);
                            
                            const timeMatch = timeText.match(/(\\d{2}:\\d{2})-/);
                            if (!timeMatch) {
                                console.log(`アイテム ${index}: 時間パターンなし`);
                                return;
                            }
                            
                            const timeStr = timeMatch[1];
                            console.log(`アイテム ${index}: 抽出された時間 = ${timeStr}`);
                            
                            // 番組名を取得 (例: "ウェザーニュースLiVE・モーニング")
                            let programName = "ウェザーニュースLiVE";
                            const programElements = item.querySelectorAll('p.bold');
                            if (programElements.length > 0) {
                                programName = programElements[0].textContent.trim();
                                console.log(`アイテム ${index}: 番組名 = ${programName}`);
                            }
                            
                            // キャスターリンクを探す (href に "caster" を含む)
                            const casterLinks = item.querySelectorAll('a[href*="caster"]');
                            console.log(`アイテム ${index}: キャスターリンク数 = ${casterLinks.length}`);
                            
                            if (casterLinks.length > 0) {
                                const casterLink = casterLinks[0];
                                const casterName = casterLink.textContent.trim();
                                const casterUrl = casterLink.href;
                                
                                console.log(`アイテム ${index}: キャスター名 = "${casterName}"`);
                                console.log(`アイテム ${index}: キャスターURL = ${casterUrl}`);
                                
                                // 有効なキャスター名かチェック (日本語文字を含む、適切な長さ)
                                if (casterName && 
                                    casterName.length >= 2 && 
                                    casterName.length <= 20 &&
                                    /[ぁ-んァ-ヶ一-龯]/.test(casterName)) {
                                    
                                    console.log(`アイテム ${index}: 有効なキャスター名として追加`);
                                    result.push({
                                        time: timeStr,
                                        caster: casterName,
                                        program: programName,
                                        profile_url: casterUrl
                                    });
                                } else {
                                    console.log(`アイテム ${index}: 無効なキャスター名: "${casterName}"`);
                                }
                            } else {
                                console.log(`アイテム ${index}: キャスターリンクなし`);
                            }
                            
                        } catch (error) {
                            console.log(`アイテム ${index}: エラー =`, error);
                        }
                    });
                    
                    console.log("最終結果:", result);
                    return result;
                }''')
                
                browser.close()
                
                log(f"JavaScript実行結果: {len(schedule_data) if schedule_data else 0}件")
                
                if schedule_data and len(schedule_data) > 0:
                    for item in schedule_data:
                        log(f"Playwright 抽出: {item['time']} - {item['caster']}")
                    log(f"Playwright 成功: {len(schedule_data)}件取得")
                    return schedule_data
                else:
                    log("Playwright: 有効なデータ取得なし")
                    
                    # デバッグ: ページの内容を一部出力
                    try:
                        page_content = page.content()
                        if "番組表" in page_content:
                            log("ページに「番組表」の文字を確認")
                        if "boxStyle__item" in page_content:
                            log("ページに「boxStyle__item」クラスを確認")
                        else:
                            log("警告: ページに「boxStyle__item」クラスが見つかりません")
                    except:
                        pass
                    
                    return None
                    
        except Exception as e:
            log(f"Playwright エラー: {e}")
            import traceback
            log(f"詳細エラー: {traceback.format_exc()}")
            return None
    
    def get_fallback_schedule(self, partial_data=None):
        """フォールバック用スケジュール（取得できなかった分は未定）"""
        log("フォールバック: スケジュール生成（未定ベース）")
        
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
                log(f"取得失敗で未定: {time_str}")
            
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
        """スケジュール取得（軽量版：Playwrightのみ）"""
        log("=== ウェザーニュース番組表取得開始 ===")
        
        # Playwright でスクレイピング試行
        programs = self.try_playwright_scraping()
        if programs:
            # 重複除去と今日の番組のみフィルタリング
            filtered_programs = self.filter_todays_schedule(programs)
            if len(filtered_programs) >= 3:  # 十分なデータが取得できた場合
                self.schedule_data = {
                    'programs': sorted(filtered_programs, key=lambda x: x['time']),
                    'source': 'playwright',
                    'timestamp': datetime.now(JST).isoformat()
                }
                log(f"Playwright成功: {len(filtered_programs)}件の番組データを取得")
                return self.schedule_data
            elif len(filtered_programs) > 0:
                # 部分的にデータが取得できた場合はフォールバックで補完
                log(f"部分データ取得: {len(filtered_programs)}件、フォールバックで補完")
                programs = self.get_fallback_schedule(filtered_programs)
                self.schedule_data = {
                    'programs': programs,
                    'source': 'playwright_partial',
                    'timestamp': datetime.now(JST).isoformat()
                }
                return self.schedule_data
        
        # 完全フォールバック
        log("スクレイピング失敗、完全フォールバックを使用")
        programs = self.get_fallback_schedule()
        self.schedule_data = {
            'programs': programs,
            'source': 'fallback',
            'timestamp': datetime.now(JST).isoformat()
        }
        return self.schedule_data
    
    def format_tweet_text(self):
        """ツイート文を生成（シンプル版、日本時間対応）"""
        if not self.schedule_data:
            return None
        
        # 日本時間で日付を取得（24:00実行時は翌日の番組表）
        now_jst = datetime.now(JST)
        today_jst = now_jst.strftime('%Y年%m月%d日')
        
        tweet_text = f"📺 {today_jst} WNL番組表\n\n"
        
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
            tweet_text = f"📺 {today_jst} WNL番組表\n\n"
            
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
            result = {
                'success': success,
                'schedule_data': schedule_data,
                'tweet_text': tweet_text,
                'timestamp': datetime.now(JST).isoformat(),
                'execution_date_jst': datetime.now(JST).strftime('%Y年%m月%d日')
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
    log("=== ウェザーニュースボット開始（軽量版） ===")
    
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
