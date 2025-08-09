# weather_bot.py
import os
import json
import asyncio
from datetime import datetime
import tweepy
from pyppeteer_weathernews_bot import PyppeteerWeatherNewsBot

class WeatherNewsTwitterBot:
    def __init__(self):
        # Twitter API認証情報を環境変数から取得
        self.api_key = os.getenv('TWITTER_API_KEY')
        self.api_secret = os.getenv('TWITTER_API_SECRET')
        self.access_token = os.getenv('TWITTER_ACCESS_TOKEN')
        self.access_token_secret = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
        
        # Twitter API v2クライアントの初期化
        self.client = tweepy.Client(
            consumer_key=self.api_key,
            consumer_secret=self.api_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            wait_on_rate_limit=True
        )
        
    def format_schedule_tweet(self, schedule_data):
        """スケジュールデータからツイート用テキストを生成"""
        today = datetime.now().strftime('%Y年%m月%d日')
        
        tweet_text = f"📺 {today} ウェザーニュースLiVE 番組表\n\n"
        
        if schedule_data['programs']:
            for program in schedule_data['programs']:
                tweet_text += f"🕐 {program['time']} {program['caster']}\n"
                if len(tweet_text) > 250:  # Twitter文字数制限対策
                    tweet_text += "...\n"
                    break
        else:
            tweet_text += "番組表の取得に失敗しました。\n"
            
        tweet_text += f"\n#ウェザーニュース #番組表 #天気予報"
        
        # Twitter文字数制限（280文字）チェック
        if len(tweet_text) > 280:
            # 長すぎる場合は切り詰める
            tweet_text = tweet_text[:270] + "...\n\n#ウェザーニュース"
            
        return tweet_text
    
    def post_tweet(self, text):
        """ツイートを投稿"""
        try:
            response = self.client.create_tweet(text=text)
            print(f"✅ ツイート投稿成功: {response.data['id']}")
            return True
        except Exception as e:
            print(f"❌ ツイート投稿失敗: {e}")
            return False
    
    async def run(self):
        """メイン実行関数"""
        try:
            # ウェザーニュースのスケジュールを取得
            print("🔄 ウェザーニュースのスケジュールを取得中...")
            bot = PyppeteerWeatherNewsBot()
            schedule_data = await bot.scrape_schedule()
            
            # 取得したデータをファイルに保存
            with open('latest_schedule.json', 'w', encoding='utf-8') as f:
                json.dump(schedule_data, f, ensure_ascii=False, indent=2)
            
            # ツイート用テキストを生成
            tweet_text = self.format_schedule_tweet(schedule_data)
            print(f"📝 生成されたツイート:\n{tweet_text}")
            
            # ツイートを投稿
            success = self.post_tweet(tweet_text)
            
            return {
                'success': success,
                'schedule_data': schedule_data,
                'tweet_text': tweet_text
            }
            
        except Exception as e:
            print(f"❌ 実行エラー: {e}")
            return {
                'success': False,
                'error': str(e)
            }

async def main():
    # 環境変数の確認
    required_env_vars = [
        'TWITTER_API_KEY',
        'TWITTER_API_SECRET', 
        'TWITTER_ACCESS_TOKEN',
        'TWITTER_ACCESS_TOKEN_SECRET'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        print(f"❌ 環境変数が設定されていません: {', '.join(missing_vars)}")
        return
    
    # ボット実行
    bot = WeatherNewsTwitterBot()
    result = await bot.run()
    
    # 結果をファイルに保存
    with open('run_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print("🏁 実行完了")

if __name__ == "__main__":
    asyncio.run(main())
