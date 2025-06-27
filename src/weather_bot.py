# dynamic_weather_bot.py
import tweepy
import os
import sys
from datetime import datetime
import asyncio
from pyppeteer import launch
from bs4 import BeautifulSoup
import re

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
            await page.goto('https://minorin.jp/wnl/caster.cgi', {
                'waitUntil': 'networkidle2',
                'timeout': 30000
            })
            
            # 少し待機（JavaScriptの実行完了を待つ）
            await asyncio.sleep(3)
            
            # JavaScript実行後のHTMLを取得
            html_content = await page.content()
            
            await browser.close()
            
            print("✅ 動的HTML取得成功")
            print(f"🔍 HTMLサイズ: {len(html_content)}文字")
            
            return html_content
            
        except Exception as e:
            print(f"❌ 動的HTML取得失敗: {e}")
            return None
    
    def parse_dynamic_schedule(self, html_content):
        """動的HTMLから番組表を解析"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            schedule_data = {}
            
            today = datetime.now().strftime("%Y-%m-%d")
            print(f"🔍 解析対象日: {today}")
            
            # 全てのテーブル要素を探す
            tables = soup.find_all('table')
            print(f"🔍 テーブル数: {len(tables)}")
            
            # 水色ハイライト行を探す（style属性やclass属性で）
            all_rows = soup.find_all('tr')
            print(f"🔍 全行数: {len(all_rows)}")
            
            for row_index, row in enumerate(all_rows):
                # 行のスタイルを確認
                row_style = row.get('style', '')
                row_class = row.get('class', [])
                
                # 水色ハイライトを示すスタイルを探す
                is_highlighted = (
                    'background-color: lightblue' in row_style or
                    'background-color: cyan' in row_style or
                    'background-color: aqua' in row_style or
                    'bgcolor="lightblue"' in str(row) or
                    'bgcolor="cyan"' in str(row) or
                    any('highlight' in str(cls) for cls in row_class if isinstance(cls, str))
                )
                
                cells = row.find_all('td')
                if len(cells) > 0:
                    first_cell_text = cells[0].get_text(strip=True)
                    
                    # 今日の日付を含む行を探す
                    if (today in first_cell_text or 
                        "2025-06-28" in first_cell_text or
                        is_highlighted):
                        
                        print(f"✅ 今日のデータを発見！")
                        print(f"🔍 行 {row_index}")
                        print(f"🔍 ハイライト: {is_highlighted}")
                        print(f"🔍 行スタイル: {row_style}")
                        print(f"🔍 行クラス: {row_class}")
                        print(f"🔍 最初のセル: '{first_cell_text}'")
                        print(f"🔍 セル数: {len(cells)}")
                        
                        # 各セルの詳細を表示
                        for i, cell in enumerate(cells[:7]):  # 最初の7セルのみ
                            cell_text = cell.get_text(strip=True)
                            print(f"🔍 セル {i}: '{cell_text}'")
                            
                            # divタグがあるかチェック
                            divs = cell.find_all('div')
                            if divs:
                                for j, div in enumerate(divs):
                                    div_text = div.get_text(strip=True)
                                    div_style = div.get('style', '')
                                    print(f"  div {j}: '{div_text}' (style: {div_style})")
                        
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
                        return schedule_data
            
            print(f"⚠️ 今日の日付 ({today}) のデータが見つかりませんでした")
            return {}
            
        except Exception as e:
            print(f"❌ 動的HTML解析エラー: {e}")
            return {}
    
    def extract_caster_name_dynamic(self, cell):
        """動的HTMLからキャスター名を抽出"""
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
                bytes_data = name.encode('iso-8859-1')
                name = bytes_data.decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        
        name = name.strip()
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
            print(f"📤 ツイート投稿中: {tweet_text}")
            
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
        """動的番組表ツイートを実行"""
        print("🚀 動的番組表ツイート実行開始")
        
        # 動的HTMLを取得
        html_content = await self.fetch_dynamic_schedule_data()
        if not html_content:
            return False
        
        # データを解析
        schedule_data = self.parse_dynamic_schedule(html_content)
        if not schedule_data:
            return False
        
        # ツイート文を生成
        tweet_text = self.format_schedule_tweet(schedule_data)
        if not tweet_text:
            return False
        
        # ツイート投稿
        return self.post_tweet(tweet_text)

async def main():
    """メイン実行関数"""
    print("=" * 50)
    print("🤖 動的ウェザーニュース番組表ボット開始")
    print("=" * 50)
    
    try:
        bot = DynamicWeatherNewsBot()
        
        # 動的番組表ツイートを実行
        success = await bot.run_schedule_tweet()
        
        if success:
            print("\n🎉 番組表ツイートが正常に完了しました!")
            sys.exit(0)
        else:
            print("\n💥 ツイート処理中にエラーが発生しました")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
