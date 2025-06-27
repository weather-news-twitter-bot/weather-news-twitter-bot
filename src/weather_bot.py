# minimal_test_bot.py
import tweepy
import os
from datetime import datetime

def minimal_test():
    """最小限のテストツイート"""
    try:
        # 認証設定
        client = tweepy.Client(
            consumer_key=os.environ.get('TWITTER_API_KEY'),
            consumer_secret=os.environ.get('TWITTER_API_SECRET'),
            access_token=os.environ.get('TWITTER_ACCESS_TOKEN'),
            access_token_secret=os.environ.get('TWITTER_ACCESS_TOKEN_SECRET'),
            wait_on_rate_limit=True
        )
        
        # 認証テスト
        user = client.get_me()
        print(f"✅ 認証成功: @{user.data.username}")
        
        # 最小限のテストツイート（ASCII文字のみ）
        now = datetime.now()
        test_text = f"Test bot {now.strftime('%H:%M')} #test"
        
        print(f"📤 テストツイート投稿中: {test_text}")
        print(f"📝 文字数: {len(test_text)}")
        
        response = client.create_tweet(text=test_text)
        
        if response.data:
            tweet_id = response.data['id']
            print(f"✅ テストツイート成功! ID: {tweet_id}")
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

if __name__ == "__main__":
    if minimal_test():
        print("🎉 最小限テスト成功！")
    else:
        print("💥 テスト失敗")
