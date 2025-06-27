# weather_bot.py
import tweepy
import os
import sys
from datetime import datetime, timedelta
import asyncio
import requests
from bs4 import BeautifulSoup
import re

class WeatherNewsBot:
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
    
    def get_jst_today(self):
        """日本時間の今日の日付を取得"""
        utc_now = datetime.utcnow()
        jst_now = utc_now + timedelta(hours=9)
        today_jst = jst_now.strftime("%Y-%m-%d")
        
        print(f"🕒 UTC時刻: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🕒 JST時刻: {jst_now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📅 JST今日の日付: {today_jst}")
        
        return today_jst, jst_now
    
    def fetch_schedule_data(self):
        """番組表データを取得（静的HTML優先、必要に応じて動的取得）"""
        try:
            print("📡 番組表データを取得中（静的HTML）...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
                'Connection': 'keep-alive',
            }
            
            response = requests.get('https://minorin.jp/wnl/caster.cgi', headers=headers, timeout=30)
            response.raise_for_status()
            
            # エンコーディングを正しく設定
            response.encoding = 'utf-8'
            
            print(f"✅ 静的HTMLデータ取得成功")
            
            # 今日の日付が含まれているかチェック
            today, _ = self.get_jst_today()
            if today in response.text:
                print(f"✅ 今日のデータ ({today}) が静的HTMLに含まれています")
                return response.text
            else:
                print(f"⚠️ 今日のデータ ({today}) が静的HTMLに見つかりません")
                print("🚀 動的取得（JavaScript実行）を試行します...")
                return self.fetch_dynamic_schedule_data()
            
        except Exception as e:
            print(f"❌ 静的HTML取得失敗: {e}")
            print("🚀 動的取得（JavaScript実行）を試行します...")
            return self.fetch_dynamic_schedule_data()
    
    def fetch_dynamic_schedule_data(self):
        """Puppeteerで動的HTMLを取得（フォールバック）"""
        try:
            import asyncio
            return asyncio.run(self._fetch_with_puppeteer())
        except ImportError:
            print("❌ Puppeteerがインストールされていません")
            print("💡 requirements.txtにpyppeteerを追加してください")
            return None
        except Exception as e:
            print(f"❌ 動的取得も失敗: {e}")
            return None
    
    async def _fetch_with_puppeteer(self):
        """Puppeteerでブラウザを使用してHTMLを取得"""
        from pyppeteer import launch
        browser = None
        try:
            print("🚀 ブラウザを起動してJavaScript実行後のHTMLを取得中...")
            
            # Puppeteer設定
            launch_options = {
                'headless': True,
                'args': [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--no-first-run',
                    '--single-process'
                ]
            }
            
            # CI環境での実行可能パス設定
            if os.environ.get('PUPPETEER_EXECUTABLE_PATH'):
                launch_options['executablePath'] = os.environ.get('PUPPETEER_EXECUTABLE_PATH')
            
            browser = await launch(launch_options)
            page = await browser.newPage()
            
            await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            await page.goto('https://minorin.jp/wnl/caster.cgi', {
                'waitUntil': 'networkidle2',
                'timeout': 30000
            })
            
            # JavaScript実行完了を待つ
            await asyncio.sleep(3)
            
            html_content = await page.content()
            await browser.close()
            browser = None
            
            print("✅ 動的HTML取得成功")
            return html_content
            
        except Exception as e:
            if browser:
                try:
                    await browser.close()
                except:
                    pass
            print(f"❌ 動的HTML取得失敗: {e}")
            return None
    
    def find_today_schedule(self, html_content):
        """今日の日付の行を探してデータを抽出"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            today, jst_now = self.get_jst_today()
            
            print(f"🔍 {today} の番組表を検索中...")
            
            # 全ての行を取得
            rows = soup.find_all('tr')
            print(f"🔍 全行数: {len(rows)}")
            
            for row_index, row in enumerate(rows):
                cells = row.find_all(['td', 'th'])
                if len(cells) < 7:  # 日付+6番組の最低7列が必要
                    continue
                
                # 最初のセル（日付列）をチェック
                first_cell_text = cells[0].get_text(strip=True)
                
                # 今日の日付が含まれているかチェック
                if today in first_cell_text:
                    print(f"✅ 今日の番組表を発見: 行 {row_index}")
                    print(f"   日付セル: '{first_cell_text}'")
                    
                    # 番組表データを抽出
                    schedule = self.extract_schedule_from_row(cells, today)
                    return schedule
            
            print(f"⚠️ {today} の番組表が見つかりませんでした")
            return None
            
        except Exception as e:
            print(f"❌ 解析エラー: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def extract_schedule_from_row(self, cells, date):
        """行から番組表データを抽出"""
        try:
            schedule_data = {date: {}}
            
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
                cell_index = i + 1  # 日付列（0番目）をスキップ
                if cell_index < len(cells):
                    cell = cells[cell_index]
                    caster_name = self.extract_caster_name(cell)
                    schedule_data[date][time_slot] = {
                        "program": program,
                        "caster": caster_name
                    }
                    print(f"✅ {time_slot} {program}: {caster_name}")
                else:
                    schedule_data[date][time_slot] = {
                        "program": program,
                        "caster": "未定"
                    }
                    print(f"⚠️ {time_slot} {program}: セルなし")
            
            return schedule_data
            
        except Exception as e:
            print(f"❌ 行からの抽出エラー: {e}")
            return None
    
    def extract_caster_name(self, cell):
        """セルからキャスター名を抽出・文字化け修復"""
        try:
            # セルの全テキストを取得
            cell_text = cell.get_text(strip=True)
            
            # 文字化け修復
            fixed_text = self.fix_encoding(cell_text)
            print(f"   セル内容: '{fixed_text}'")
            
            # 複数の方法でキャスター名を抽出
            candidates = []
            
            # 方法1: 改行で分割
            lines = fixed_text.split('\n')
            for line in lines:
                line = line.strip()
                if line and self.is_valid_caster_name(line):
                    candidates.append(line)
            
            # 方法2: HTMLタグ別に抽出
            for tag_name in ['div', 'span', 'p']:
                elements = cell.find_all(tag_name)
                for elem in elements:
                    elem_text = self.fix_encoding(elem.get_text(strip=True))
                    if elem_text and self.is_valid_caster_name(elem_text):
                        candidates.append(elem_text)
            
            # 方法3: 複数名前の分離（新機能）
            if fixed_text and len(fixed_text) > 6:  # 長い文字列の場合のみ
                separated_names = self.separate_multiple_names(fixed_text)
                for name in separated_names:
                    if self.is_valid_caster_name(name):
                        candidates.append(name)
            
            # 方法4: 連続する日本語文字を抽出
            current_name = ""
            for char in fixed_text:
                if '\u3040' <= char <= '\u309F' or '\u30A0' <= char <= '\u30FF' or '\u4E00' <= char <= '\u9FAF':
                    current_name += char
                else:
                    if current_name and self.is_valid_caster_name(current_name):
                        candidates.append(current_name)
                    current_name = ""
            
            # 最後の名前も追加
            if current_name and self.is_valid_caster_name(current_name):
                candidates.append(current_name)
            
            # 最適な候補を選択
            if candidates:
                # 重複を除去し、最初の候補を返す
                unique_candidates = list(dict.fromkeys(candidates))
                
                # 長さでソート（短い名前を優先 = 単一の名前を優先）
                unique_candidates.sort(key=len)
                
                best_candidate = unique_candidates[0]
                
                if len(unique_candidates) > 1:
                    print(f"   候補: {unique_candidates} → 選択: '{best_candidate}'")
                else:
                    print(f"   抽出: '{best_candidate}'")
                
                return best_candidate
            
            print("   → 未定")
            return "未定"
            
        except Exception as e:
            print(f"名前抽出エラー: {e}")
            return "未定"
    
    def separate_multiple_names(self, text):
        """複数の名前が結合している場合に分離を試行"""
        names = []
        
        # パターン1: よくある名字で分割
        common_surnames = ['山岸', '江川', '松雪', '白井', '駒木', '戸北', '小林', '川畑', '魚住', '小川', '岡本', '青原', '福吉', '山口', '内藤', '宇野沢', '森田']
        
        for surname in common_surnames:
            if surname in text:
                parts = text.split(surname)
                if len(parts) >= 2:
                    # 名字+名前の組み合わせを復元
                    for i in range(1, len(parts)):
                        if parts[i]:
                            potential_name = surname + parts[i][:2]  # 名字+名前2文字
                            if len(potential_name) <= 6:  # 妥当な長さ
                                names.append(potential_name)
        
        # パターン2: 3-4文字ずつ分割
        if len(text) >= 6 and not names:
            for i in range(0, len(text), 3):
                chunk = text[i:i+4]  # 3-4文字ずつ
                if len(chunk) >= 3:
                    names.append(chunk)
        
        return names
    
    def fix_encoding(self, text):
        """文字エンコーディングの修復"""
        if not text:
            return text
        
        try:
            # UTF-8の誤解釈による文字化けを修復
            if any(char in text for char in ['ã', 'æ', 'ç', 'è', 'é']):
                try:
                    # ISO-8859-1としてエンコードしてUTF-8でデコード
                    bytes_data = text.encode('iso-8859-1')
                    fixed_text = bytes_data.decode('utf-8')
                    # 修復が成功し、日本語文字が含まれている場合のみ使用
                    if any('\u3040' <= char <= '\u309F' or '\u30A0' <= char <= '\u30FF' or '\u4E00' <= char <= '\u9FAF' for char in fixed_text):
                        return fixed_text
                except (UnicodeDecodeError, UnicodeEncodeError):
                    pass
            
            return text
        except Exception:
            return text
    
    def is_valid_caster_name(self, text):
        """有効なキャスター名かチェック（バランス重視）"""
        if not text or len(text) < 2:
            return False
        
        # 長すぎる場合は除外（ただし余裕を持たせる）
        if len(text) > 12:  # 8→12に緩和
            return False
        
        # 日本語文字が含まれているかチェック
        has_japanese = any('\u3040' <= char <= '\u309F' or  # ひらがな
                          '\u30A0' <= char <= '\u30FF' or  # カタカナ
                          '\u4E00' <= char <= '\u9FAF'     # 漢字
                          for char in text)
        
        if not has_japanese:
            return False
        
        # 明らかに除外すべきパターンのみ（最小限に）
        exclude_patterns = [
            'モーニング', 'サンシャイン', 'コーヒータイム', 'アフタヌーン', 'イブニング', 'ムーン',  # 番組名
            '2025-', '202', '時間表示', '日間表示',  # 明らかに番組表関連
            '(', ')', '![]', 'http',  # HTML/記号
        ]
        
        # 完全一致する除外パターンのみチェック
        if any(text == pattern or pattern in text for pattern in exclude_patterns):
            return False
        
        # 数字のみや記号のみの場合は除外
        if text.isdigit() or text in ['-', '−', '・', '×', '○', '未定']:
            return False
        
        # 基本的に日本語が含まれていれば有効とする（寛容な判定）
        return True
    
    def format_schedule_tweet(self, schedule_data):
        """番組表ツイートを生成"""
        today, jst_now = self.get_jst_today()
        
        if today not in schedule_data:
            print(f"❌ {today} の番組表データがありません")
            return None
        
        day_schedule = schedule_data[today]
        
        # 日付情報の整形（JST基準）
        date_str = jst_now.strftime("%-m/%-d" if os.name != 'nt' else "%m/%d").lstrip('0').replace('/0', '/')
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays[jst_now.weekday()]
        
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
        
        # 重複投稿を避けるために時刻を追加
        hour_minute = jst_now.strftime("%H:%M")
        
        tweet_text = f"""📺 {date_str}({weekday}) WNL番組表 [{hour_minute}更新]

{schedule_text}

#ウェザーニュース #WNL"""
        
        print(f"📝 ツイート文生成完了 ({len(tweet_text)}文字)")
        return tweet_text
    
    def post_tweet(self, tweet_text):
        """ツイートを投稿"""
        try:
            print(f"📤 ツイート投稿中...")
            print(f"内容:\n{tweet_text}")
            
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
    
    def run(self):
        """メイン実行"""
        print("🚀 番組表ツイート実行開始")
        
        # データを取得
        html_content = self.fetch_schedule_data()
        if not html_content:
            print("❌ HTMLの取得に失敗しました")
            return False
        
        # 今日の番組表を検索
        schedule_data = self.find_today_schedule(html_content)
        if not schedule_data:
            print("❌ 今日の番組表が見つかりませんでした")
            return False
        
        # ツイート文を生成
        tweet_text = self.format_schedule_tweet(schedule_data)
        if not tweet_text:
            print("❌ ツイート文の生成に失敗しました")
            return False
        
        # ツイート投稿
        return self.post_tweet(tweet_text)

def main():
    """メイン実行関数"""
    print("=" * 50)
    print("🤖 ウェザーニュース番組表ボット開始")
    print("=" * 50)
    
    try:
        bot = WeatherNewsBot()
        
        # 番組表ツイートを実行
        success = bot.run()
        
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
    main()
