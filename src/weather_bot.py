def format_schedule_tweet(self, schedule_data):
        """番組表ツイートを生成"""
        today, jst_now = self.get_jst_today()
        
        if today not in schedule_data:
            print(f"❌ {today} の番組表データがありません")
            return None
        
        day_schedule = schedule_data[today]
        
        # 日付情報の整形（JST基準）
        date_str = jst_now.strftime("%m/%d")
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays[jst_now.weekday()]
        
        # 番組表を生成    def get_jst_today(self):
        """日本時間の今日の日付を取得"""
        # UTCから日本時間(JST = UTC+9)に変換
        utc_now = datetime.utcnow()
        jst_now = utc_now + timedelta(hours=9)
        today_jst = jst_now.strftime("%Y-%m-%d")
        
        print(f"🕒 UTC時刻: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🕒 JST時刻: {jst_now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📅 JST今日の日付: {today_jst}")
        
        return today_jst, jst_now    async def debug_site_structure(self):
        """サイト構造のデバッグ専用メソッド"""
        print("🔍 サイト構造の詳細調査開始...")
        
        # HTMLを取得
        html_content = await self.fetch_static_schedule_data()
        if not html_content:
            print("❌ HTML取得失敗")
            return
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # ページタイトルを確認
        title = soup.find('title')
        print(f"ページタイトル: {title.get_text() if title else 'なし'}")
        
        # 今日の日付に関連しそうな要素を広範囲で検索
        today_patterns = [
            datetime.now().strftime("%Y-%m-%d"),
            datetime.now().strftime("%Y/%m/%d"),
            datetime.now().strftime("%m/%d"),
            datetime.now().strftime("%-m/%-d") if os.name != 'nt' else datetime.now().strftime("%m/%d"),
            "2025-06-27",  # 固定で今日の日付
            "06-27",
            "06/27",
            "6/27"
        ]
        
        print(f"検索パターン: {today_patterns}")
        
        # 全テキストから日付を検索
        page_text = soup.get_text()
        for pattern in today_patterns:
            if pattern in page_text:
                print(f"✅ 日付パターン '{pattern}' を発見")
        
        # 水色関連の要素を検索
        colored_elements = soup.find_all(attrs={"style": lambda x: x and any(color in x.lower() for color in ['blue', 'cyan', 'aqua'])})
        print(f"🔷 色付き要素数: {len(colored_elements)}")
        
        for i, elem in enumerate(colored_elements[:5]):  # 最初の5個
            print(f"  色付き要素 {i}: {elem.name} - {elem.get('style')} - '{elem.get_text()[:50]}...'")
        
        # bgcolor属性を持つ要素を検索
        bgcolor_elements = soup.find_all(attrs={"bgcolor": True})
        print(f"🎨 bgcolor要素数: {len(bgcolor_elements)}")
        
        for i, elem in enumerate(bgcolor_elements[:5]):
            print(f"  bgcolor要素 {i}: {elem.name} - bgcolor='{elem.get('bgcolor')}' - '{elem.get_text()[:50]}...'")
    
    async def run_debug_mode(self):
        """デバッグモードで実行"""
        print("🚀 デバッグモード実行開始")
        
        # サイト構造を調査
        await self.debug_site_structure()
        
        # 通常の解析も実行
        html_content = await self.fetch_static_schedule_data()
        if html_content:
            schedule_data = self.parse_dynamic_schedule(html_content)
            print(f"\n📋 解析結果: {len(schedule_data)}日分のデータ")
            
            # ツイート文を生成（投稿はしない）
            tweet_text = self.format_schedule_tweet(schedule_data)
            if tweet_text:
                print(f"\n📝 生成されるツイート文:")
                print("="*50)
                print(tweet_text)
                print("="*50)
        
        return Trueimport tweepy
import os
import sys
from datetime import datetime, timedelta
import asyncio
from pyppeteer import launch
from bs4 import BeautifulSoup
import re
import requests
import pytz

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
        browser = None
        try:
            print("🚀 ブラウザを起動してJavaScript実行後のHTMLを取得中...")
            
            # Puppeteer設定を環境に応じて調整
            launch_options = {
                'headless': True,
                'args': [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--single-process',
                    '--disable-gpu',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            }
            
            # CI環境での実行可能パス設定
            if os.environ.get('PUPPETEER_EXECUTABLE_PATH'):
                launch_options['executablePath'] = os.environ.get('PUPPETEER_EXECUTABLE_PATH')
            
            # Puppeteerでブラウザを起動
            browser = await launch(launch_options)
            
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
                
                await browser.close()
                browser = None
                
                if html_content:
                    print("✅ 動的HTML取得成功")
                    print(f"🔍 HTMLサイズ: {len(html_content)}文字")
                    return html_content
                
            except Exception as e:
                print(f"⚠️ 動的取得失敗、通常のHTTP取得にフォールバック: {e}")
                if browser:
                    await browser.close()
                    browser = None
                # フォールバック: 通常のHTTP取得
                return await self.fetch_static_schedule_data()
            
        except Exception as e:
            print(f"❌ 動的HTML取得失敗: {e}")
            if browser:
                try:
                    await browser.close()
                except:
                    pass
            # フォールバック: 通常のHTTP取得
            return await self.fetch_static_schedule_data()
        
        return None
    
    async def fetch_static_schedule_data(self):
        """通常のHTTP取得（フォールバック）"""
        try:
            print("📡 通常のHTTP取得を試行中...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            response = requests.get('https://minorin.jp/wnl/caster.cgi', headers=headers, timeout=30)
            response.raise_for_status()
            
            # エンコーディングの自動検出を試行
            if response.encoding.lower() in ['iso-8859-1', 'ascii']:
                # UTF-8で再試行
                response.encoding = 'utf-8'
            
            print(f"✅ 静的HTML取得成功 (エンコーディング: {response.encoding})")
            return response.text
            
        except Exception as e:
            print(f"❌ 静的HTML取得も失敗: {e}")
            return None
    
    def parse_dynamic_schedule(self, html_content):
        """HTMLから番組表を解析"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            schedule_data = {}
            
            # 日本時間の今日の日付を取得
            today, jst_now = self.get_jst_today()
            print(f"🔍 解析対象日: {today}")
            
            # HTMLの全体構造を調査
            print("🔍 HTML構造の詳細調査開始...")
            
            # 全てのテーブルを詳しく調査
            tables = soup.find_all('table')
            print(f"🔍 テーブル数: {len(tables)}")
            
            for table_index, table in enumerate(tables):
                print(f"\n--- テーブル {table_index} ---")
                
                # テーブルの属性を確認
                table_attrs = table.attrs
                print(f"テーブル属性: {table_attrs}")
                
                # このテーブルの行数
                rows = table.find_all('tr')
                print(f"行数: {len(rows)}")
                
                # 最初の数行を詳しく調査
                for row_index, row in enumerate(rows[:5]):  # 最初の5行のみ
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        print(f"  行 {row_index}: {len(cells)}列")
                        
                        # 行のスタイルとクラスを確認
                        row_style = row.get('style', '')
                        row_class = row.get('class', [])
                        row_bgcolor = row.get('bgcolor', '')
                        
                        if row_style or row_class or row_bgcolor:
                            print(f"    スタイル: {row_style}")
                            print(f"    クラス: {row_class}")
                            print(f"    bgcolor: {row_bgcolor}")
                        
                        # 各セルの内容をチェック
                        for cell_index, cell in enumerate(cells[:7]):  # 最初の7列のみ
                            cell_text = cell.get_text(strip=True)
                            cell_style = cell.get('style', '')
                            cell_class = cell.get('class', [])
                            cell_bgcolor = cell.get('bgcolor', '')
                            
                            print(f"    セル {cell_index}: '{cell_text[:20]}...' " + 
                                  (f"(style: {cell_style})" if cell_style else "") +
                                  (f"(class: {cell_class})" if cell_class else "") +
                                  (f"(bgcolor: {cell_bgcolor})" if cell_bgcolor else ""))
                            
                            # 日付らしきパターンをチェック（今日の日付で）
                            date_patterns = [
                                today,  # 2025-06-28
                                jst_now.strftime("%m/%d"),  # 06/28
                                jst_now.strftime("%-m/%-d") if os.name != 'nt' else jst_now.strftime("%m/%d").lstrip('0').replace('/0', '/'),  # 6/28
                                jst_now.strftime("%Y/%m/%d"),  # 2025/06/28
                            ]
                            
                            if any(pattern in cell_text for pattern in date_patterns):
                                print(f"    ⭐ 日付候補発見: '{cell_text}'")
                            
                            # 水色/ハイライト関連のスタイルをチェック
                            if any(color in str(cell_style).lower() for color in ['blue', 'cyan', 'aqua', 'lightblue']):
                                print(f"    🔷 ハイライトセル発見: {cell_style}")
                            
                            if any(color in str(cell_bgcolor).lower() for color in ['blue', 'cyan', 'aqua', 'lightblue']):
                                print(f"    🔷 ハイライトセル発見 (bgcolor): {cell_bgcolor}")
            
            # 水色ハイライト行を特別に検索
            print("\n🔍 水色ハイライト行の特別検索...")
            highlighted_rows = []
            
            # 全ての行を再検索
            all_rows = soup.find_all('tr')
            for row_index, row in enumerate(all_rows):
                # 行全体のスタイルチェック
                row_style = str(row.get('style', '')).lower()
                row_bgcolor = str(row.get('bgcolor', '')).lower()
                row_class = str(row.get('class', [])).lower()
                
                # セル単位でのスタイルチェック
                cells = row.find_all(['td', 'th'])
                cell_highlights = []
                
                for cell in cells:
                    cell_style = str(cell.get('style', '')).lower()
                    cell_bgcolor = str(cell.get('bgcolor', '')).lower()
                    cell_class = str(cell.get('class', [])).lower()
                    
                    is_highlighted = any([
                        'lightblue' in cell_style,
                        'cyan' in cell_style,
                        'aqua' in cell_style,
                        '#add8e6' in cell_style,  # lightblue hex
                        '#00ffff' in cell_style,  # cyan hex
                        'lightblue' in cell_bgcolor,
                        'cyan' in cell_bgcolor,
                        'aqua' in cell_bgcolor,
                        'highlight' in cell_class
                    ])
                    
                    if is_highlighted:
                        cell_highlights.append(cell.get_text(strip=True))
                
                # 行レベルでのハイライトチェック
                row_highlighted = any([
                    'lightblue' in row_style,
                    'cyan' in row_style,
                    'aqua' in row_style,
                    'lightblue' in row_bgcolor,
                    'cyan' in row_bgcolor,
                    'aqua' in row_bgcolor,
                    'highlight' in row_class
                ])
                
                if row_highlighted or cell_highlights:
                    print(f"🔷 ハイライト行発見 {row_index}: {len(cells)}列")
                    if cell_highlights:
                        print(f"  ハイライトセル: {cell_highlights}")
                    
                    # この行に今日の日付が含まれているかチェック
                    row_text = row.get_text()
                    date_patterns = [
                        today,  # 2025-06-28
                        jst_now.strftime("%m/%d"),  # 06/28
                        jst_now.strftime("%-m/%-d") if os.name != 'nt' else jst_now.strftime("%m/%d").lstrip('0').replace('/0', '/'),  # 6/28
                        jst_now.strftime("%Y/%m/%d"),  # 2025/06/28
                    ]
                    
                    if any(pattern in row_text for pattern in date_patterns):
                        print(f"  ⭐⭐⭐ 今日の番組表候補: 行 {row_index}")
                        highlighted_rows.append((row_index, row))
            
            # 候補が見つかった場合の処理
            if highlighted_rows:
                print(f"\n✅ {len(highlighted_rows)}個の候補を発見")
                for row_index, row in highlighted_rows:
                    cells = row.find_all(['td', 'th'])
                    print(f"\n--- 候補行 {row_index} の詳細解析 ---")
                    
                    for i, cell in enumerate(cells):
                        cell_text = cell.get_text(strip=True)
                        # 文字化け修復を試行
                        fixed_text = self.fix_encoding(cell_text)
                        if fixed_text != cell_text:
                            print(f"列 {i}: '{cell_text}' → 修復後: '{fixed_text}'")
                        else:
                            print(f"列 {i}: '{fixed_text}'")
                        
                        # この列がキャスター名らしいかチェック
                        if self.is_likely_caster_name(fixed_text):
                            print(f"  → キャスター名候補: {fixed_text}")
                    
                    # 実際の番組表として解析を試行
                    return self.extract_schedule_from_row(row, today)
            
            print(f"⚠️ 今日の日付 ({today}) のハイライト行が見つかりませんでした")
            # デモ用のダミーデータを生成
            return self.generate_dummy_schedule()
            
        except Exception as e:
            print(f"❌ HTML解析エラー: {e}")
            import traceback
            traceback.print_exc()
            # エラー時はダミーデータを返す
            return self.generate_dummy_schedule()
    
    def fix_encoding(self, text):
        """文字エンコーディングの修復"""
        if not text:
            return text
        
        try:
            # 一般的な文字化けパターンを修復
            text = text.replace('â€™', "'").replace('â€œ', '"').replace('â€', '"')
            
            # 日本語の文字化けパターンを修復
            if 'ã' in text or 'æ' in text or 'ç' in text:
                try:
                    # ISO-8859-1でエンコードしてUTF-8でデコード
                    bytes_data = text.encode('iso-8859-1')
                    fixed_text = bytes_data.decode('utf-8')
                    return fixed_text
                except (UnicodeDecodeError, UnicodeEncodeError):
                    # 修復できない場合は元の文字列を返す
                    pass
            
            return text
        except Exception:
            return text
    
    def is_likely_caster_name(self, text):
        """テキストがキャスター名らしいかを判定"""
        if not text or len(text) < 2 or len(text) > 15:
            return False
        
        # 日本語文字が含まれているかチェック
        has_japanese = any('\u3040' <= char <= '\u309F' or  # ひらがな
                          '\u30A0' <= char <= '\u30FF' or  # カタカナ
                          '\u4E00' <= char <= '\u9FAF'     # 漢字
                          for char in text)
        
        # 明らかに時間や番組名ではないかチェック
        time_patterns = [':', '時', '分', 'AM', 'PM', 'モーニング', 'サンシャイン', 'コーヒータイム', 'アフタヌーン', 'イブニング', 'ムーン']
        is_time_related = any(pattern in text for pattern in time_patterns)
        
        return has_japanese and not is_time_related
    
    def extract_schedule_from_row(self, row, date):
        """行から番組表データを抽出"""
        cells = row.find_all(['td', 'th'])
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
        
        # 最初のセルは日付として、2列目以降を番組データとして処理
        for i, (time_slot, program) in enumerate(time_slots):
            cell_index = i + 1  # 日付列をスキップ
            if cell_index < len(cells):
                cell = cells[cell_index]
                caster_name = self.extract_caster_name_dynamic(cell)
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
                print(f"⚠️ {time_slot} {program}: データなし")
        
        return schedule_data
    
    def generate_dummy_schedule(self):
        """ダミーの番組表データを生成（テスト用）"""
        today, _ = self.get_jst_today()
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
                    fixed_name = self.fix_encoding(caster_name)
                    return self.clean_caster_name(fixed_name)
            
            # 区切り文字方式
            text_with_separators = cell.get_text(separator='|', strip=True)
            if '|' in text_with_separators:
                parts = text_with_separators.split('|')
                if parts[0].strip():
                    fixed_name = self.fix_encoding(parts[0].strip())
                    return self.clean_caster_name(fixed_name)
            
            # フォールバック
            raw_text = cell.get_text(strip=True)
            if raw_text:
                fixed_text = self.fix_encoding(raw_text)
                return self.clean_caster_name(fixed_text)
            
            return "未定"
            
        except Exception:
            return "未定"
    
    def clean_caster_name(self, name):
        """キャスター名をクリーンアップ"""
        if not name:
            return "未定"
        
        # 文字エンコーディング修復
        try:
            # まず UTF-8 として処理を試行
            if isinstance(name, str):
                # 一般的な文字化け修復を試行
                name = name.replace('â€™', "'").replace('â€œ', '"').replace('â€', '"')
                
                # 日本語の文字化けパターンを修復
                if 'ã' in name or 'æ' in name or 'ç' in name:
                    try:
                        # ISO-8859-1でエンコードしてUTF-8でデコード
                        bytes_data = name.encode('iso-8859-1')
                        name = bytes_data.decode('utf-8')
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        # 修復できない場合は元の文字列を使用
                        pass
                
        except Exception:
            pass
        
        name = name.strip()
        
        # 日本語文字が含まれているかチェック
        has_japanese = any('\u3040' <= char <= '\u309F' or  # ひらがな
                          '\u30A0' <= char <= '\u30FF' or  # カタカナ
                          '\u4E00' <= char <= '\u9FAF'     # 漢字
                          for char in name)
        
        # 適切な長さの名前で、日本語が含まれている場合
        if name and len(name) >= 2 and len(name) <= 10 and has_japanese:
            return name
        
        # 英数字のみの場合も許可（一部キャスターは英語名）
        if name and len(name) >= 2 and len(name) <= 15 and name.replace(' ', '').isalnum():
            return name
        
        return "未定"
    
    def format_schedule_tweet(self, schedule_data):
        """番組表ツイートを生成"""
        today, jst_now = self.get_jst_today()
        
        if today not in schedule_data:
            print(f"❌ {today} の番組表データがありません")
            return None
        
        day_schedule = schedule_data[today]
        
        # 日付情報の整形（JST基準）
        date_str = jst_now.strftime("%m/%d")
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
        
        # デバッグモードかどうかを環境変数で制御
        debug_mode = os.environ.get('DEBUG_MODE', 'false').lower() == 'true'
        
        if debug_mode:
            print("🔍 デバッグモードで実行します")
            success = await bot.run_debug_mode()
        else:
            # 通常モード：番組表ツイートを実行
            success = await bot.run_schedule_tweet()
        
        if success:
            print("\n🎉 処理が正常に完了しました!")
        else:
            print("\n💥 処理中にエラーが発生しました")
            
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
    
    # プログラム終了前に少し待機
    await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Asyncio error: {e}")
    finally:
        # 確実にプログラムを終了
        sys.exit(0)
