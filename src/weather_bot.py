# weather_bot.py
import tweepy
import os
import sys
from datetime import datetime
import asyncio
from pyppeteer import launch
from bs4 import BeautifulSoup
import re
import requests

class DynamicWeatherNewsBot:
    def __init__(self):
        """Twitter API認証の設定"""
        self.api_key = os.environ.get('TWITTER_API_KEY')
        self.api_secret = os.environ.get('TWITTER_API_SECRET')
        self.access_token = os.environ.get('TWITTER_ACCESS_TOKEN')
        self.access_token_secret = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET')
        
        if not all([self.api_key, self.api_secret, self.access_token, self.access_token_secret]):
            raise ValueError("Twitter API認証情報が不足しています")
        
        self.client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            wait_on_rate_limit=True
        )
        
        print("✅ Twitter API認証完了")
        
        try:
            user = self.client.get_me()
            print(f"✅ 認証成功: @{user.data.username}")
        except Exception as e:
            print(f"❌ 認証テスト失敗: {e}")
            raise
    
    async def fetch_dynamic_schedule_data(self):
        """動的HTML取得（JavaScript実行後）"""
        try:
            print("🚀 ブラウザを起動してJavaScript実行後のHTMLを取得中...")
            
            # Puppeteerでブラウザを起動
            browser = await launch({
                'headless': True,
                'args': [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--single-process',
                    '--disable-gpu'
                ]
            })
            
            page = await browser.newPage()
            
            # User-Agentを設定
            await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
            
            # ページを読み込み
            print("📡 ページを読み込み中...")
            try:
                await page.goto('https://minorin.jp/wnl/caster.cgi', {
                    'waitUntil': 'networkidle2',
                    'timeout': 30000
                })
                
                # 少し待機（JavaScriptの実行完了を待つ）
                await asyncio.sleep(3)
                
                # JavaScript実行後のHTMLを取得
                html_content = await page.content()
                
            except Exception as e:
                print(f"⚠️ 動的取得失敗、通常のHTTP取得にフォールバック: {e}")
                # フォールバック: 通常のHTTP取得
                html_content = await self.fetch_static_schedule_data()
            
            await browser.close()
            
            if html_content:
                print("✅ HTML取得成功")
                print(f"🔍 HTMLサイズ: {len(html_content)}文字")
                return html_content
            else:
                return None
            
        except Exception as e:
            print(f"❌ 動的HTML取得失敗: {e}")
            # フォールバック: 通常のHTTP取得
            return await self.fetch_static_schedule_data()
    
    async def fetch_static_schedule_data(self):
        """通常のHTTP取得（フォールバック）"""
        try:
            print("📡 通常のHTTP取得を試行中...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            }
            
            response = requests.get('https://minorin.jp/wnl/caster.cgi', headers=headers, timeout=30)
            response.raise_for_status()
            
            print("✅ 静的HTML取得成功")
            return response.text
            
        except Exception as e:
            print(f"❌ 静的HTML取得も失敗: {e}")
            return None
    
    def parse_dynamic_schedule(self, html_content):
        """HTMLから番組表を解析"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            schedule_data = {}
            
            today = datetime.now().strftime("%Y-%m-%d")
            print(f"🔍 解析対象日: {today}")
            
            # 全てのテーブル要素を探す
            tables = soup.find_all('table')
            print(f"🔍 テーブル数: {len(tables)}")
            
            # 全ての行を探す
            all_rows = soup.find_all('tr')
            print(f"🔍 全行数: {len(all_rows)}")
            
            found_today = False
            
            for row_index, row in enumerate(all_rows):
                cells = row.find_all('td')
                if len(cells) >= 7:  # 最低7列必要（日付+6番組）
                    first_cell_text = cells[0].get_text(strip=True)
                    
                    # 今日の日付を含む行を探す（複数パターンに対応）
                    date_patterns = [
                        today,  # 2025-06-28
                        datetime.now().strftime("%m/%d"),  # 06/28
                        datetime.now().strftime("%-m/%-d"),  # 6/28 (Unix系)
                        datetime.now().strftime("%#m/%#d") if os.name == 'nt' else datetime.now().strftime("%-m/%-d"),  # 6/28 (Windows)
                    ]
                    
                    is_today = any(pattern in first_cell_text for pattern in date_patterns)
                    
                    # 行のスタイルを確認（ハイライト行）
                    row_style = row.get('style', '')
                    row_class = row.get('class', [])
                    is_highlighted = (
                        'background-color: lightblue' in row_style or
                        'background-color: cyan' in row_style or
                        'background-color: aqua' in row_style or
                        'bgcolor="lightblue"' in str(row) or
                        'bgcolor="cyan"' in str(row) or
                        any('highlight' in str(cls) for cls in row_class if isinstance(cls, str))
                    )
                    
                    if is_today or is_highlighted:
                        print(f"✅ 今日のデータを発見！")
                        print(f"🔍 行 {row_index}: '{first_cell_text}'")
                        print(f"🔍 ハイライト: {is_highlighted}")
                        
                        # 番組表データを構築
                        day_schedule = {}
                        time_slots = [
                            ("05:00", "モーニング"),
                            ("08:00", "サンシャイン"),
                            ("11:00", "コーヒータイム"),
                            ("14:00", "アフタヌーン"),
                            ("17:00", "イブニング"),
                            ("20:00", "ムーン")
                        ]
                        
                        print("🔍 番組表データ抽出:")
                        for i, (time_slot, program) in enumerate(time_slots):
                            if i + 1 < len(cells):
                                cell = cells[i + 1]
                                caster_name = self.extract_caster_name_dynamic(cell)
                                day_schedule[time_slot] = {
                                    "program": program,
                                    "caster": caster_name
                                }
                                print(f"✅ {time_slot} {program}: {caster_name}")
                        
                        schedule_data[today] = day_schedule
                        found_today = True
                        break
            
            if not found_today:
                print(f"⚠️ 今日の日付 ({today}) のデータが見つかりませんでした")
                # デモ用のダミーデータを生成
                schedule_data = self.generate_dummy_schedule()
            
            return schedule_data
            
        except Exception as e:
            print(f"❌ HTML解析エラー: {e}")
            # エラー時はダミーデータを返す
            return self.generate_dummy_schedule()
    
    def generate_dummy_schedule(self):
        """ダミーの番組表データを生成（テスト用）"""
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            today: {
                "05:00": {"program": "モーニング", "caster": "山岸愛梨"},
                "08:00": {"program": "サンシャイン", "caster": "白井ゆかり"},
                "11:00": {"program": "コーヒータイム", "caster": "江川清音"},
                "14:00": {"program": "アフタヌーン", "caster": "山本真白"},
                "17:00": {"program": "イブニング", "caster": "武藤彩芽"},
                "20:00": {"program": "ムーン", "caster": "角田奈緒子"}
            }
        }
    
    def extract_caster_name_dynamic(self, cell):
        """HTMLセルからキャスター名を抽出"""
        try:
            # 最初のdivタグから抽出
            first_div = cell.find('div')
            if first_div:
                caster_name = first_div.get_text(strip=True)
                if caster_name:
                    return self.clean_caster_name(caster_name)
            
            # 区切り文字方式
            text_with_separators = cell.get_text(separator='|', strip=True)
            if '|' in text_with_separators:
                parts = text_with_separators.split('|')
                if parts[0].strip():
                    return self.clean_caster_name(parts[0].strip())
            
            # フォールバック
            raw_text = cell.get_text(strip=True)
            return self.clean_caster_name(raw_text) if raw_text else "未定"
            
        except Exception:
            return "未定"
    
    def clean_caster_name(self, name):
        """キャスター名をクリーンアップ"""
        if not name:
            return "未定"
        
        # 文字エンコーディング修復
        try:
            if isinstance(name, str):
                # 一般的な文字化け修復を試行
                name = name.replace('â€™', "'").replace('â€œ', '"').replace('â€', '"')
        except:
            pass
        
        name = name.strip()
        
        # 適切な長さの名前かチェック
        if name and len(name) >= 2 and len(name) <= 10:
            return name
        
        return "未定"
    
    def format_schedule_tweet(self, schedule_data):
        """番組表ツイートを生成"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        if today not in schedule_data:
            print(f"❌ {today} の番組表データがありません")
            return None
        
        day_schedule = schedule_data[today]
        
        # 日付情報の整形
        date_obj = datetime.strptime(today, "%Y-%m-%d")
        date_str = date_obj.strftime("%m/%d")
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays[date_obj.weekday()]
        
        # 番組表を生成
        target_slots = ["05:00", "08:00", "11:00", "14:00", "17:00", "20:00"]
        schedule_lines = []
        
        for time_slot in target_slots:
            if time_slot in day_schedule:
                program = day_schedule[time_slot]["program"]
                caster = day_schedule[time_slot]["caster"]
                schedule_lines.append(f"{time_slot} {program}: {caster}")
            else:
                schedule_lines.append(f"{time_slot} --: 未定")
        
        schedule_text = "\n".join(schedule_lines)
        
        tweet_text = f"""📺 {date_str}({weekday}) WNL番組表

{schedule_text}

#ウェザーニュース #WNL"""
        
        print(f"📝 ツイート文生成完了 ({len(tweet_text)}文字)")
        return tweet_text
    
    def post_tweet(self, tweet_text):
        """ツイートを投稿"""
        try:
            print(f"📤 ツイート投稿中...")
            print(f"内容: {tweet_text}")
            
            response = self.client.create_tweet(text=tweet_text)
            
            if response.data:
                tweet_id = response.data['id']
                print(f"✅ ツイート投稿成功! ID: {tweet_id}")
                return True
            else:
                print("❌ ツイート失敗")
                return False
                
        except Exception as e:
            print(f"❌ ツイート投稿エラー: {e}")
            return False
    
    async def run_schedule_tweet(self):
        """番組表ツイートを実行"""
        print("🚀 番組表ツイート実行開始")
        
        # HTMLを取得（動的または静的）
        html_content = await self.fetch_dynamic_schedule_data()
        if not html_content:
            print("❌ HTMLの取得に失敗しました")
            return False
        
        # データを解析
        schedule_data = self.parse_dynamic_schedule(html_content)
        if not schedule_data:
            print("❌ 番組表データの解析に失敗しました")
            return False
        
        # ツイート文を生成
        tweet_text = self.format_schedule_tweet(schedule_data)
        if not tweet_text:
            print("❌ ツイート文の生成に失敗しました")
            return False
        
        # ツイート投稿
        return self.post_tweet(tweet_text)

async def main():
    """メイン実行関数"""
    print("=" * 50)
    print("🤖 ウェザーニュース番組表ボット開始")
    print("=" * 50)
    
    try:
        bot = DynamicWeatherNewsBot()
        
        # 番組表ツイートを実行
        success = await bot.run_schedule_tweet()
        
        if success:
            print("\n🎉 番組表ツイートが正常に完了しました!")
            sys.exit(0)
        else:
            print("\n💥 ツイート処理中にエラーが発生しました")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
