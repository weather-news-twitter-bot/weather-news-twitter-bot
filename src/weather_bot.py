    def format_schedule_tweet(self, schedule_data, target_date=None):
        """最新の利用可能な日付で番組表を生成"""
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        print(f"🔍 希望日付: {target_date}")
        print(f"🔍 利用可能な日付: {sorted(schedule_data.keys())}")
        
        # 対象日付のデータが見つからない場合、最新の日付を使用
        if target_date not in schedule_data:
            print(f"⚠️ {target_date} の番組表が見つかりません")
            
            # 利用可能な日付で最新の日を探す
            available_dates = sorted(schedule_data.keys(), reverse=True)  # 降順ソート
            if available_dates:
                latest_date = available_dates[0]
                print(f"📅 最新の利用可能な日付 {latest_date} を使用します")
                target_date = latest_date
            else:
                print("❌ 利用可能なデータがありません")
                return None
        
        day_schedule = schedule_data[target_date]
        
        # 日付情報の整形
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        date_str = date_obj.strftime("%m/%d")
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays[date_obj.weekday()]
        
        # 実際の今日の日付と異なる場合は注記を追加
        today = datetime.now().strftime("%Y-%m-%d")
        date_note = ""
        if target_date != today:
            date_note = f" (最新データ)"
        
        # 5:00から20:00まで3時間毎の番組表
        target_slots = ["05:00", "08:00", "11:00", "14:00", "17:00", "20:00"]
        schedule_lines = []
        
        for time_slot in target_slots:
            if time_slot in day_schedule:
                program = day_schedule[time_slot]["program"]
                caster = day_schedule[time_slot]["caster"]
                # "他日"や"未取得"の場合は"未定"に変更
                if caster in ["他日", "未取得", ""]:
                    caster = "未定# src/weather_bot.py
import tweepy
import os
import sys
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import re

class WeatherNewsBot:
    def __init__(self):
        """Twitter API認証の設定（最小テストボットと同じ方式）"""
        self.api_key = os.environ.get('TWITTER_API_KEY')
        self.api_secret = os.environ.get('TWITTER_API_SECRET')
        self.access_token = os.environ.get('TWITTER_ACCESS_TOKEN')
        self.access_token_secret = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET')
        
        # 必要な環境変数がすべて設定されているかチェック
        if not all([self.api_key, self.api_secret, self.access_token, self.access_token_secret]):
            raise ValueError("Twitter API認証情報が不足しています。以下の環境変数を設定してください:\n"
                           "TWITTER_API_KEY, TWITTER_API_SECRET, "
                           "TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET")
        
        # Twitter API v2クライアント初期化（最小テストボットと同じ）
        self.client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            wait_on_rate_limit=True
        )
        
        print("✅ Twitter API認証完了")
        
        # 認証テスト
        try:
            user = self.client.get_me()
            print(f"✅ 認証成功: @{user.data.username}")
        except Exception as e:
            print(f"❌ 認証テスト失敗: {e}")
            raise
    
    def fetch_schedule_data(self):
        """番組表データを取得（文字エンコーディング修正）"""
        main_url = "https://minorin.jp/wnl/caster.cgi"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept-Charset': 'UTF-8'
            }
            
            print(f"📡 番組表データを取得中: {main_url}")
            response = requests.get(main_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # 文字エンコーディングを明示的に設定
            if response.encoding is None or response.encoding.lower() in ['iso-8859-1', 'ascii']:
                response.encoding = 'utf-8'
            
            print(f"✅ 番組表データ取得成功")
            return response.text
            
        except requests.RequestException as e:
            print(f"❌ データ取得失敗: {e}")
            return None
    
    def parse_schedule(self, html_content):
        """HTMLから番組表を解析（テーブル構造を詳しく調査）"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            schedule_data = {}
            
            # 現在の日付を取得
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            print(f"🔍 解析対象日: {today}")
            
            # テーブルの全ての行を取得
            rows = soup.find_all('tr')
            print(f"📊 {len(rows)}行のデータを解析中...")
            
            # 各行の詳細を確認
            for row_index, row in enumerate(rows):
                cells = row.find_all('td')
                if len(cells) > 0:
                    # 最初のセルの内容を確認
                    first_cell_text = cells[0].get_text(strip=True)
                    
                    # 日付が含まれているかチェック
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', first_cell_text)
                    
                    if date_match:
                        current_date = date_match.group(1)
                        print(f"🔍 行 {row_index}: 日付 {current_date} を発見")
                        print(f"🔍 セル数: {len(cells)}")
                        
                        # 今日の日付の場合、詳細を表示
                        if current_date == today:
                            print(f"✅ 今日のデータ ({current_date}) を発見！")
                            print(f"🔍 最初のセル: {repr(first_cell_text)}")
                            
                            # 各セルの内容を確認
                            for i, cell in enumerate(cells):
                                cell_text = cell.get_text(strip=True)
                                cell_html = str(cell)
                                print(f"🔍 セル {i}: テキスト='{cell_text}', HTML={cell_html[:200]}...")
                                
                                # セパレーター付きテキストも確認
                                cell_sep_text = cell.get_text(separator='|', strip=True)
                                if '|' in cell_sep_text:
                                    print(f"🔍 セル {i} セパレーター: '{cell_sep_text}'")
                        
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
                        
                        # 各時間帯のデータを抽出
                        for i, (time_slot, program) in enumerate(time_slots):
                            if i + 1 < len(cells):
                                cell = cells[i + 1]
                                
                                if current_date == today:
                                    # 今日の場合は詳細抽出
                                    caster_name = self.extract_caster_name_new(cell)
                                    print(f"🔍 {time_slot} {program}: '{caster_name}'")
                                else:
                                    # 他の日は簡易処理
                                    caster_name = "他日"
                                
                                day_schedule[time_slot] = {
                                    "program": program,
                                    "caster": caster_name
                                }
                        
                        schedule_data[current_date] = day_schedule
                        print(f"📅 {current_date} の番組表を解析完了")
            
            print(f"✅ {len(schedule_data)}日分の番組表解析完了")
            print(f"🔍 今日 ({today}) のデータが含まれています: {today in schedule_data}")
            
            if today in schedule_data:
                print(f"🎉 今日のデータ詳細: {schedule_data[today]}")
            
            return schedule_data
            
        except Exception as e:
            print(f"❌ 番組表解析エラー: {e}")
            return {}
    
    def extract_caster_name_new(self, cell):
        """キャスター名抽出（区切り文字方式 - 最も確実）"""
        try:
            # 方法1: 区切り文字方式（最も確実）
            text_with_separators = cell.get_text(separator='|', strip=True)
            if '|' in text_with_separators:
                parts = text_with_separators.split('|')
                if len(parts) >= 1 and parts[0].strip():
                    first_part = parts[0].strip()
                    return self.clean_caster_name(first_part)
            
            # 方法2: 最初のdivタグから抽出（フォールバック）
            first_div = cell.find('div')
            if first_div:
                caster_name = first_div.get_text(strip=True)
                if caster_name:
                    return self.clean_caster_name(caster_name)
            
            # 方法3: 最後の手段として改行区切り
            raw_text = cell.get_text(strip=True)
            if '\n' in raw_text:
                lines = raw_text.split('\n')
                if lines[0].strip():
                    return self.clean_caster_name(lines[0].strip())
            
            # 方法4: 既知の気象予報士名で分割
            forecasters = ["山口剛央", "飯島栄一", "宇野沢達也", "本田竜也", "芳野達郎"]
            for forecaster in forecasters:
                if forecaster in raw_text:
                    parts = raw_text.split(forecaster)
                    if parts[0].strip():
                        return self.clean_caster_name(parts[0].strip())
            
            return "未定"
            
        except Exception as e:
            return "未定"
    
    def clean_caster_name(self, name):
        """キャスター名をクリーンアップ（シンプル版）"""
        if not name:
            return "未定"
        
        # 文字エンコーディング修復
        try:
            if isinstance(name, str):
                bytes_data = name.encode('iso-8859-1')
                name = bytes_data.decode('utf-8')
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
        
        # 基本的なクリーンアップのみ
        name = name.strip()
        
        # 有効性チェック
        if name and len(name) >= 2 and len(name) <= 10:
            return name
        
        return "未定"
    
    def extract_caster_name(self, caster_info):
        """キャスター名を抽出（1行目のみ、確実に）"""
        if not caster_info:
            return "未定"
        
        try:
            # 文字エンコーディング修復
            fixed_text = caster_info
            try:
                if isinstance(caster_info, str):
                    bytes_data = caster_info.encode('iso-8859-1')
                    fixed_text = bytes_data.decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                fixed_text = caster_info
            
            # 複数の改行パターンで分割を試行
            lines = []
            for separator in ['\n', '\r\n', '\r', '<br>', '<BR>']:
                if separator in fixed_text:
                    lines = fixed_text.split(separator)
                    break
            
            # 改行が見つからない場合は、既知のパターンで分割
            if not lines or len(lines) == 1:
                # 既知の気象予報士名で分割
                forecasters = ["山口剛央", "飯島栄一", "宇野沢達也", "本田竜也", "芳野達郎"]
                text_to_split = fixed_text
                
                for forecaster in forecasters:
                    if forecaster in text_to_split:
                        # 気象予報士名の直前で分割
                        parts = text_to_split.split(forecaster)
                        if parts[0].strip():
                            lines = [parts[0].strip()]
                            break
                
                # まだ分割できていない場合は、「クロス」で分割
                if not lines or len(lines) == 1:
                    if "クロス" in text_to_split:
                        parts = text_to_split.split("クロス")
                        if parts[0].strip():
                            lines = [parts[0].strip()]
                    elif "(クロス)" in text_to_split:
                        parts = text_to_split.split("(クロス)")
                        if parts[0].strip():
                            lines = [parts[0].strip()]
            
            # 1行目を取得
            if lines and lines[0].strip():
                first_line = lines[0].strip()
                
                # さらに念のため、気象予報士名とクロスを除去
                forecasters = ["山口剛央", "飯島栄一", "宇野沢達也", "本田竜也", "芳野達郎"]
                for forecaster in forecasters:
                    first_line = first_line.replace(forecaster, "").strip()
                
                # クロス関連の文字を除去
                first_line = re.sub(r'[()（）]*クロス[()（）]*', '', first_line).strip()
                
                # 有効な名前かチェック
                if first_line and len(first_line) >= 2 and len(first_line) <= 10:
                    return first_line
            
            return "未定"
            
        except Exception as e:
            return "未定"
    
    def get_current_time_slot(self):
        """現在時刻に最も近い番組の時間帯を取得"""
        now = datetime.now()
        current_hour = now.hour
        
        time_slots = [
            ("05:00", "モーニング"),
            ("08:00", "サンシャイン"), 
            ("11:00", "コーヒータイム"),
            ("14:00", "アフタヌーン"),
            ("17:00", "イブニング"),
            ("20:00", "ムーン")
        ]
        
        # 現在時刻に最も近い番組を見つける
        for i, (time_str, program) in enumerate(time_slots):
            slot_hour = int(time_str.split(':')[0])
            if abs(current_hour - slot_hour) <= 1 or (current_hour >= 23 and slot_hour <= 5):
                return time_str, program
        
        # デフォルトは現在時刻に最も近いもの
        min_diff = 24
        closest_slot = time_slots[0]
        for time_str, program in time_slots:
            slot_hour = int(time_str.split(':')[0])
            diff = min(abs(current_hour - slot_hour), 24 - abs(current_hour - slot_hour))
            if diff < min_diff:
                min_diff = diff
                closest_slot = (time_str, program)
        
        return closest_slot
    
    def format_schedule_tweet(self, schedule_data, target_date=None):
        """実行日の5:00-20:00の3時間毎キャスター表を生成（フォールバック対応）"""
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        print(f"🔍 対象日付: {target_date}")
        print(f"🔍 利用可能な日付: {list(schedule_data.keys())}")
        
        # 対象日付のデータが見つからない場合、最新の日付を使用
        if target_date not in schedule_data:
            print(f"⚠️ {target_date} の番組表が見つかりません")
            
            # 利用可能な日付で最新の日を探す
            available_dates = sorted(schedule_data.keys(), reverse=True)  # 降順ソート
            if available_dates:
                latest_date = available_dates[0]
                print(f"📅 最新の利用可能な日付 {latest_date} を使用します")
                target_date = latest_date
            else:
                print("❌ 利用可能なデータがありません")
                return None
        
        day_schedule = schedule_data[target_date]
        print(f"🔍 使用する日付: {target_date}")
        
        # 日付情報の整形
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        date_str = date_obj.strftime("%m/%d")
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays[date_obj.weekday()]
        
        # 実際の今日の日付と異なる場合は注記を追加
        today = datetime.now().strftime("%Y-%m-%d")
        date_note = ""
        if target_date != today:
            today_obj = datetime.strptime(today, "%Y-%m-%d")
            today_str = today_obj.strftime("%m/%d")
            today_weekday = weekdays[today_obj.weekday()]
            date_note = f" (最新データ)"
        
        # 5:00から20:00まで3時間毎の番組表
        target_slots = ["05:00", "08:00", "11:00", "14:00", "17:00", "20:00"]
        schedule_lines = []
        
        for time_slot in target_slots:
            if time_slot in day_schedule:
                program = day_schedule[time_slot]["program"]
                caster = day_schedule[time_slot]["caster"]
                schedule_lines.append(f"{time_slot} {program}: {caster}")
                print(f"🔍 {time_slot} {program}: {caster}")
            else:
                # 番組がない場合
                schedule_lines.append(f"{time_slot} --: 未定")
                print(f"🔍 {time_slot} データなし")
        
        schedule_text = "\n".join(schedule_lines)
        
        # 番組表ツイート
        tweet_text = f"""📺 {date_str}({weekday}) WNL番組表{date_note}

{schedule_text}

#ウェザーニュース #WNL"""
        
        print(f"📝 ツイート文生成完了 ({len(tweet_text)}文字)")
        return tweet_text
    
    def post_tweet(self, tweet_text):
        """ツイートを投稿（最小テストボットと同じ方式）"""
        try:
            print(f"📤 ツイート投稿中: {tweet_text}")
            print(f"📝 文字数: {len(tweet_text)}")
            
            response = self.client.create_tweet(text=tweet_text)
            
            if response.data:
                tweet_id = response.data['id']
                print(f"✅ ツイート投稿成功! ID: {tweet_id}")
                return True
            else:
                print("❌ ツイート失敗: レスポンスデータなし")
                return False
                
        except tweepy.Forbidden as e:
            print(f"❌ 権限エラー: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"❌ エラー詳細: {e.response.text}")
            return False
        except Exception as e:
            print(f"❌ エラー: {e}")
            return False
    
    def run_schedule_tweet(self):
        """番組表ツイートを実行（動的に今日の日付を使用）"""
        print("🚀 番組表ツイート実行開始")
        
        # 現在の日付を取得
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        print(f"🗓️ 現在の日時: {now.strftime('%Y/%m/%d %H:%M:%S')}")
        print(f"🗓️ 対象日付: {today}")
        
        # 番組表データを取得
        html_content = self.fetch_schedule_data()
        if not html_content:
            return False
        
        # データを解析（今日の日付を指定）
        schedule_data = self.parse_schedule(html_content)
        if not schedule_data:
            return False
        
        # 今日の番組表ツイートを生成
        tweet_text = self.format_schedule_tweet(schedule_data, today)
        
        if not tweet_text:
            print(f"❌ {today} の番組表データが見つかりませんでした")
            print(f"🔍 利用可能な日付: {list(schedule_data.keys())}")
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
        success = bot.run_schedule_tweet()
        
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
    main()
