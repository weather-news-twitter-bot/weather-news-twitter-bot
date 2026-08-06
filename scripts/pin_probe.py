#!/usr/bin/env python3
"""
固定ポスト(pinned post)が API で設定できるか確かめるための使い捨て調査スクリプト。

公式 API v2 に「投稿をプロフィールに固定する」エンドポイントは無い（固定できるのはリストのみ）。
実際に使われているのは v1.1 の account/pin_tweet で、これはドキュメントに載っていない。
無料枠で通るかどうかは実際に叩かないと分からないので、ここで一度だけ確かめる。

やること:
  1. GET /2/users/me                       … 自分の user id
  2. GET /2/users/{id}/tweets              … 直近ツイート（固定する対象を選ぶ）
  3. POST /2/users/{id}/pinned_tweets      … 念のため（未文書。おそらく404）
  4. POST /1.1/account/pin_tweet.json      … 本命（未文書）

固定対象は環境変数 PIN_TWEET_ID で指定できる。無ければ直近ツイートを使う。
結果はステータスと本文をそのまま出す（判断は人間がする）。
"""
import os
import sys

from requests_oauthlib import OAuth1Session


def show(label: str, resp) -> None:
    body = resp.text
    if len(body) > 1500:
        body = body[:1500] + ' …(略)'
    print(f'--- {label}')
    print(f'    status: {resp.status_code}')
    print(f'    body  : {body}')
    print()


def main() -> int:
    session = OAuth1Session(
        client_key=os.environ['TWITTER_API_KEY'],
        client_secret=os.environ['TWITTER_API_SECRET'],
        resource_owner_key=os.environ['TWITTER_ACCESS_TOKEN'],
        resource_owner_secret=os.environ['TWITTER_ACCESS_TOKEN_SECRET'],
    )

    r = session.get('https://api.x.com/2/users/me')
    show('GET /2/users/me', r)
    if r.status_code != 200:
        print('自分の user id が取れないので中止')
        return 1
    user_id = r.json()['data']['id']
    print(f'user_id = {user_id}\n')

    target = os.getenv('PIN_TWEET_ID', '').strip()
    if not target:
        r = session.get(
            f'https://api.x.com/2/users/{user_id}/tweets',
            params={'max_results': 5, 'tweet.fields': 'created_at'},
        )
        show(f'GET /2/users/{user_id}/tweets', r)
        if r.status_code == 200 and r.json().get('data'):
            target = r.json()['data'][0]['id']
        else:
            print('直近ツイートが読めなかった。PIN_TWEET_ID を指定して再実行する。')
            return 1
    print(f'固定対象 = {target}\n')

    # 未文書。存在しない可能性が高いが、あれば公式ルートなので先に試す。
    r = session.post(
        f'https://api.x.com/2/users/{user_id}/pinned_tweets',
        json={'tweet_id': target},
    )
    show('POST /2/users/{id}/pinned_tweets （未文書）', r)
    v2_ok = r.status_code in (200, 201)

    # 本命。ブラウザの通信から見つかった未文書エンドポイント。
    r = session.post(
        'https://api.twitter.com/1.1/account/pin_tweet.json',
        data={'id': target},
    )
    show('POST /1.1/account/pin_tweet.json （未文書）', r)
    v11_ok = r.status_code == 200

    print('=' * 50)
    if v2_ok or v11_ok:
        which = 'v2 pinned_tweets' if v2_ok else 'v1.1 account/pin_tweet'
        print(f'固定できた: {which}')
        return 0
    print('どちらも通らなかった → API からの固定は不可')
    return 1


if __name__ == '__main__':
    sys.exit(main())
