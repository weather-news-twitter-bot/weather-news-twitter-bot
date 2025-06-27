# src/weather_bot.py
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
        """番組表データを取得"""
        main_url = "https://minorin.jp/wnl/caster.cgi"
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            }
            
            print(f"📡 番組表データを取得中: {main_url}")
            response = requests.get(main_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            print("✅ 番組表データ取得成功")
            return response.text
            
        except requests.RequestException as e:
            print(f"❌ データ取得失敗: {e}")
            return None
    
    def parse_schedule(self, html_content):
        """HTMLから番組表を解析"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            schedule_data = {}
            
            rows = soup.find_all('tr')
            print(f"📊 {len(rows)}行のデータを解析中...")
            
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 7:
                    date_text = cells[0].get_text(strip=True)
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_text)
                    
                    if date_match:
                        current_date = date_match.group(1)
                        day_schedule = {}
                        
                        time_slots = [
                            ("05:00", "モーニング"),
                            ("08:00", "サンシャイン"),
                            ("11:00", "コーヒータイム"),
                            ("14:00", "アフタヌーン"),
                            ("17:00", "イブニング"),
                            ("20:00", "ムーン")
                        ]
                        
                        for i, (time_slot, program) in enumerate(time_slots):
                            if i + 1 < len(cells):
                                caster_info = cells[i + 1].get_text(strip=True)
                                caster_name = self.extract_caster_name(caster_info)
                                day_schedule[time_slot] = {
                                    "program": program,
                                    "caster": caster_name
                                }
                        
                        schedule_data[current_date] = day_schedule
                        print(f"📅 {current_date} の番組表を解析完了")
            
            print(f"✅ {len(schedule_data)}日分の番組表解析完了")
            return schedule_data
            
        except Exception as e:
            print(f"❌ 番組表解析エラー: {e}")
            return {}
    
    def extract_caster_name(self, caster_info):
        """キャスター名を抽出（1行目がキャスター、2行目が気象予報士）"""
        if not caster_info:
            return "未定"
        
        try:
            # デバッグ用：元データを出力
            print(f"🔍 元データ: {repr(caster_info)}")
            
            # 改行で分割して1行目を取得
            lines = caster_info.strip().split('\n')
            print(f"🔍 分割後の行数: {len(lines)}")
            
            if not lines:
                return "未定"
            
            first_line = lines[0].strip()
            print(f"🔍 1行目: {repr(first_line)}")
            
            if not first_line:
                return "未定"
            
            # (クロス)などの注釈を除去
            cleaned_name = re.sub(r'[()（）].*', '', first_line).strip()
            print(f"🔍 注釈除去後: {repr(cleaned_name)}")
            
            # 空白や特殊文字で分割（複数名の場合は最初の名前）
            names = re.split(r'[　\s]+', cleaned_name)
            valid_names = [name for name in names if name.strip() and len(name) >= 2]
            print(f"🔍 有効な名前: {valid_names}")
            
            if valid_names:
                caster_name = valid_names[0]
                print(f"🔍 最終的な名前: {repr(caster_name)}")
                
                # 文字化けチェック（簡単な方法）
                # 文字化けした文字が含まれているかチェック
                if any(char in caster_name for char in ['å', 'ã', 'ç', 'æ', 'è', 'é', 'ê', 'ë']):
                    print(f"🔍 文字化け検出: {caster_name}")
                    return "未定"
                
                # 基本的な長さチェックのみ（10文字以内）
                if len(caster_name) <= 10:
                    return caster_name
            
            return "未定"
            
        except Exception as e:
            print(f"❌ キャスター名抽出エラー: {e}, 元データ: {repr(caster_info)}")
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
        """実行日の5:00-20:00の3時間毎キャスター表を生成"""
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        if target_date not in schedule_data:
            print(f"❌ {target_date} の番組表が見つかりません")
            return None
        
        day_schedule = schedule_data[target_date]
        
        # 日付情報の整形
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        date_str = date_obj.strftime("%m/%d")
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays[date_obj.weekday()]
        
        # 5:00から20:00まで3時間毎の番組表
        target_slots = ["05:00", "08:00", "11:00", "14:00", "17:00", "20:00"]
        schedule_lines = []
        
        for time_slot in target_slots:
            if time_slot in day_schedule:
                program = day_schedule[time_slot]["program"]
                caster = day_schedule[time_slot]["caster"]
                schedule_lines.append(f"{time_slot} {program}: {caster}")
            else:
                # 番組がない場合
                schedule_lines.append(f"{time_slot} --: 未定")
        
        schedule_text = "\n".join(schedule_lines)
        
        # シンプルな番組表ツイート
        tweet_text = f"""📺 {date_str}({weekday}) WNL番組表

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
        """番組表ツイートを実行"""
        print("🚀 番組表ツイート実行開始")
        
        # 番組表データを取得
        html_content = self.fetch_schedule_data()
        if not html_content:
            return False
        
        # データを解析
        schedule_data = self.parse_schedule(html_content)
        if not schedule_data:
            return False
        
        # 今日の番組表ツイートを生成
        today = datetime.now().strftime("%Y-%m-%d")
        tweet_text = self.format_schedule_tweet(schedule_data, today)
        
        if not tweet_text:
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
