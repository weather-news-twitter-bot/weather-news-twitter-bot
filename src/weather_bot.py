# src/weather_bot.py
import tweepy
import os
import sys
import json
from datetime import datetime, timedelta
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
        
        # 必要な環境変数がすべて設定されているかチェック
        if not all([self.api_key, self.api_secret, self.access_token, self.access_token_secret]):
            raise ValueError("Twitter API認証情報が不足しています")
        
        # Twitter API v2クライアント初期化
        self.client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            wait_on_rate_limit=True
        )
        
        print("✅ Twitter API認証完了")
    
    def fetch_schedule_data(self):
        """番組表データを取得"""
        try:
            url = "https://minorin.jp/wnl/caster.cgi"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            print(f"📡 番組表データを取得中: {url}")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            print("✅ 番組表データ取得成功")
            return response.text
            
        except requests.RequestException as e:
            print(f"❌ 番組表データ取得失敗: {e}")
            return None
    
    def parse_schedule(self, html_content):
        """HTMLから番組表を解析"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            schedule_data = {}
            
            # テーブル行を取得
            rows = soup.find_all('tr')
            print(f"📊 {len(rows)}行のデータを解析中...")
            
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 7:
                    # 日付セルから日付を抽出
                    date_text = cells[0].get_text(strip=True)
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_text)
                    
                    if date_match:
                        current_date = date_match.group(1)
                        day_schedule = {}
                        
                        # 各時間帯のキャスター情報を抽出
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
        """キャスター名を抽出（気象予報士名などを除去）"""
        if not caster_info:
            return "none"
        
        # 改行、全角スペース、半角スペースで分割
        names = re.split(r'[　\s\n]+', caster_info)
        # 空文字列を除去して最初の名前を取得
        valid_names = [name for name in names if name.strip()]
        
        if valid_names:
            return valid_names[0]
        return "none"
    
    def format_schedule_tweet(self, schedule_data, target_date=None):
        """指定形式でツイート文を生成（現在の番組情報を強調）"""
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        if target_date not in schedule_data:
            print(f"❌ {target_date} の番組表が見つかりません")
            return None
        
        day_schedule = schedule_data[target_date]
        
        # 現在の番組情報を取得
        current_time, current_program = self.get_current_time_slot()
        current_caster = "none"
        if current_time in day_schedule:
            current_caster = day_schedule[current_time]["caster"]
        
        # 指定された順序で番組表文字列を構築
        schedule_parts = []
        time_order = ["11:00", "14:00", "17:00", "20:00", "23:00", "00:00", "05:00", "08:00", "11:00"]
        
        for time_slot in time_order:
            if time_slot in day_schedule:
                program = day_schedule[time_slot]["program"]
                caster = day_schedule[time_slot]["caster"]
                schedule_parts.append(f"{time_slot}-{program}-{caster}")
            else:
                # 23:00と00:00は番組なし
                schedule_parts.append(f"{time_slot}--none")
        
        # 日付情報の整形
        date_obj = datetime.strptime(target_date, "%Y-%m-%d")
        date_str = date_obj.strftime("%m/%d")
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays[date_obj.weekday()]
        
        # 現在時刻の情報
        now = datetime.now()
        current_time_str = now.strftime("%H:%M")
        
        # ツイート文を構築（現在の番組を強調、改行で見やすく）
        schedule_string = "\n".join(schedule_parts)  # スペースではなく改行で結合
        
        tweet_text = f"""📺 {date_str}({weekday}) ウェザーニュースLiVE番組表

🕐 現在 {current_time_str} - {current_program} ({current_caster})

{schedule_string}

#ウェザーニュース #番組表 #WNL"""
        
        print(f"📝 ツイート文生成完了 ({len(tweet_text)}文字)")
        return tweet_text
    
    def get_current_time_slot(self):
        """現在時刻に最も近い番組の時間帯を取得"""
        now = datetime.now()
        current_hour = now.hour
        
        # 3時間毎の番組スロット（JST）
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
            # 番組開始時刻の±1.5時間以内なら該当番組とする
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
    
    def post_tweet(self, tweet_text):
        """ツイートを投稿"""
        try:
            # 文字数制限チェック
            if len(tweet_text) > 280:
                print(f"⚠️  ツイートが長すぎます ({len(tweet_text)}文字). 切り詰めます...")
                tweet_text = tweet_text[:277] + "..."
            
            print(f"📤 ツイート投稿中... ({len(tweet_text)}文字)")
            print(f"内容: {tweet_text[:100]}...")
            
            response = self.client.create_tweet(text=tweet_text)
            
            if response.data:
                tweet_id = response.data['id']
                tweet_url = f"https://twitter.com/i/status/{tweet_id}"
                print(f"✅ ツイート投稿成功!")
                print(f"🔗 URL: {tweet_url}")
                return True
            else:
                print("❌ ツイート投稿失敗: レスポンスにデータがありません")
                return False
                
        except tweepy.TooManyRequests:
            print("❌ レート制限に達しました。しばらく待ってから再試行してください")
            return False
        except tweepy.Forbidden as e:
            print(f"❌ 権限エラー: {e}")
            return False
        except Exception as e:
            print(f"❌ ツイート投稿エラー: {e}")
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
