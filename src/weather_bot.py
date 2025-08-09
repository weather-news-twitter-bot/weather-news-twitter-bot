# weather_bot.py - 最終版（自己完結）
import os
import json
import asyncio
import re
import sys
from datetime import datetime
import tweepy
from pyppeteer import launch

def debug_log(message):
    """ログ出力"""
    print(f"[INFO] {datetime.now().strftime('%H:%M:%S')} - {message}")
    sys.stdout.flush()

class WeatherNewsBot:
    def __init__(self):
        self.url = "https://weathernews.jp/wnl/timetable.html"
        
        # Twitter API認証情報
        self.api_key = os.getenv('TWITTER_API_KEY')
        self.api_secret = os.getenv('TWITTER_API_SECRET')
        self.access_token = os.getenv('TWITTER_ACCESS_TOKEN')
        self.access_token_secret = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
        
        # Twitter APIクライアント初期化
        if all([self.api_key, self.api_secret, self.access_token, self.access_token_secret]):
            self.client = tweepy.Client(
                consumer_key=self.api_key,
                consumer_secret=self.api_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
                wait_on_rate_limit=True
            )
            debug_log("Twitter API認証成功")
        else:
            self.client = None
            debug_log("Twitter API認証情報が不完全（テストモード）")
        
    async def scrape_schedule(self):
        """番組表スクレイピング"""
        browser = None
        try:
            debug_log("ブラウザ起動中...")
            
            browser = await launch({
                'headless': True,
                'args': [
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-extensions',
                    '--disable-plugins',
                    '--disable-images',
                    '--window-size=1920,1080'
                ]
            })
            
            page = await browser.newPage()
            debug_log(f"ページアクセス: {self.url}")
            
            await page.goto(self.url, {'waitUntil': 'networkidle2'})
            
            # JavaScript読み込み待機
            debug_log("5秒待機...")
            await asyncio.sleep(5)
            
            # スケジュール抽出
            schedule_data = await self.extract_schedule_data(page)
            debug_log(f"取得完了: {len(schedule_data['programs'])}件")
            
            return schedule_data
            
        except Exception as e:
            debug_log(f"スクレイピングエラー: {e}")
            return self.get_fallback_schedule()
        finally:
            if browser:
                await browser.close()
    
    async def extract_schedule_data(self, page):
        """スケジュール情報抽出"""
        schedule_data = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'programs': [],
            'source': 'weather_bot'
        }
        
        # セレクタパターンを試行
        selectors = [
            ".timetable-item",
            ".schedule-item", 
            ".program-item",
            "[data-time]",
            "tr td",
            "li"
        ]
        
        for selector in selectors:
            try:
                elements = await page.querySelectorAll(selector)
                if elements:
                    debug_log(f"要素発見: {selector} ({len(elements)}個)")
                    programs = await self.parse_elements(page, elements)
                    if programs:
                        schedule_data['programs'].extend(programs)
                        break
            except Exception as e:
                continue
        
        # フォールバック
        if not schedule_data['programs']:
            debug_log("フォールバック実行")
            page_text = await page.evaluate('() => document.body.textContent')
            schedule_data['programs'] = self.extract_from_text(page_text)
        
        return schedule_data
    
    async def parse_elements(self, page, elements):
        """要素解析"""
        programs = []
        
        for element in elements:
            try:
                text = await page.evaluate('(element) => element.textContent', element)
                if not text or "{{" in text:
                    continue
                
                text = text.strip()
                
                # 時間とキャスター名マッチング
                time_match = re.search(r'(\d{1,2}):(\d{2})', text)
                name_match = re.search(r'([ぁ-んァ-ヶ一-龯]{2,8})', text)
                
                if time_match and name_match:
                    time_str = time_match.group(0)
                    caster_name = name_match.group(1)
                    
                    programs.append({
                        'time': time_str,
                        'caster': caster_name,
                        'program': self.get_program_name_by_time(time_str)
                    })
                    
            except:
                continue
        
        return programs
    
    def extract_from_text(self, page_text):
        """テキストから抽出"""
        programs = []
        lines = page_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or "{{" in line:
                continue
            
            pattern = r'(\d{1,2}):(\d{2})\s*([ぁ-んァ-ヶ一-龯]{2,8})'
            matches = re.findall(pattern, line)
            
            for match in matches:
                time_str = f"{match[0]}:{match[1]}"
                caster_name = match[2]
                
                programs.append({
                    'time': time_str,
                    'caster': caster_name,
                    'program': self.get_program_name_by_time(time_str)
                })
        
        return programs
    
    def get_program_name_by_time(self, time_str):
        """時間帯から番組名取得"""
        try:
            hour = int(time_str.split(':')[0])
            
            if 5 <= hour < 8:
                return 'ウェザーニュースLiVE・モーニング'
            elif 8 <= hour < 11:
                return 'ウェザーニュースLiVE・サンシャイン'
            elif 11 <= hour < 14:
                return 'ウェザーニュースLiVE・コーヒータイム'
            elif 14 <= hour < 17:
                return 'ウェザーニュースLiVE・アフタヌーン'
            elif 17 <= hour < 20:
                return 'ウェザーニュースLiVE・イブニング'
            elif 20 <= hour < 23:
                return 'ウェザーニュースLiVE・ムーン'
            else:
                return 'ウェザーニュースLiVE・ミッドナイト'
        except:
            return 'ウェザーニュースLiVE'
    
    def get_fallback_schedule(self):
        """フォールバック用スケジュール"""
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'programs': [
                {'time': '05:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・モーニング'},
                {'time': '08:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・サンシャイン'},
                {'time': '11:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・コーヒータイム'},
                {'time': '14:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・アフタヌーン'},
                {'time': '17:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・イブニング'},
                {'time': '20:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・ムーン'},
                {'time': '23:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・ミッドナイト'}
            ],
            'source': 'fallback'
        }
    
    def format_schedule_tweet(self, schedule_data):
        """ツイート文生成"""
        today = datetime.now().strftime('%Y年%m月%d日')
        
        tweet_text = f"📺 {today} ウェザーニュースLiVE 番組表\n\n"
        
        if schedule_data['programs']:
            for program in schedule_data['programs']:
                tweet_text += f"🕐 {program['time']} {program['caster']}\n"
                if len(tweet_text) > 250:
                    tweet_text += "...\n"
                    break
        else:
            tweet_text += "番組表の取得に失敗しました。\n"
            
        tweet_text += f"\n#ウェザーニュース #番組表 #天気予報"
        
        if len(tweet_text) > 280:
            tweet_text = tweet_text[:270] + "...\n\n#ウェザーニュース"
            
        return tweet_text
    
    def post_tweet(self, text):
        """ツイート投稿"""
        if not self.client:
            debug_log("Twitter投稿をスキップ（認証情報なし）")
            return False
            
        try:
            response = self.client.create_tweet(text=text)
            debug_log(f"ツイート投稿成功: {response.data['id']}")
            return True
        except Exception as e:
            debug_log(f"ツイート投稿失敗: {e}")
            return False
    
    async def run(self):
        """メイン実行"""
        try:
            debug_log("=== ウェザーニュースボット開始 ===")
            
            # スケジュール取得
            schedule_data = await self.scrape_schedule()
            
            # ファイル保存
            with open('latest_schedule.json', 'w', encoding='utf-8') as f:
                json.dump(schedule_data, f, ensure_ascii=False, indent=2)
            
            # ツイート生成・投稿
            tweet_text = self.format_schedule_tweet(schedule_data)
            debug_log(f"ツイート内容:\n{tweet_text}")
            
            success = self.post_tweet(tweet_text)
            
            result = {
                'success': success,
                'schedule_data': schedule_data,
                'tweet_text': tweet_text
            }
            
            # 結果保存
            with open('run_result.json', 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            debug_log("=== 実行完了 ===")
            return result
            
        except Exception as e:
            debug_log(f"実行エラー: {e}")
            return {'success': False, 'error': str(e)}

# メイン実行
if __name__ == "__main__":
    asyncio.run(WeatherNewsBot().run())
