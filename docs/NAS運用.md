# NAS（Synology DS220j）1台で回す運用

2026-09-16 から、番組表の監視・X への投稿・記録の push を **Synology NAS 1台**で
やっている。GitHub Actions の定時実行と、Windows PC のタスクはやめた。

## なぜ NAS か

- 2026-09-11 に X API が従量課金になり（`402 credits depleted`）、API では投稿しない
  ことにした。代わりにログイン済みブラウザに Playwright で繋いで打つ
- ブラウザは GitHub Actions には置けない（ログイン状態を持てない）。PC に置くと
  PC が寝ている夜は告知が飛ぶ。NAS は常時起動で、Docker が載る
- GitHub Actions の cron は「20分おき」設定でも実際は1日4回程度しか走っていなかった
  （GitHub 側で間引かれる）。NAS のタスクスケジューラは設定どおり走る

## 何がどこで動くか

```
DSM タスクスケジューラ（毎日 00:00〜23:40、20分おき、ユーザー ryo）
  └ sh /volume1/homes/ryo/wnl/repo/scripts/nas_run.sh
      ├ git pull --ff-only                … 最新のコードを取る
      ├ venv/bin/python src/weather_bot.py  … TWEET_VIA=browser
      │    ├ 番組表 JSON を取って前回ツイートと比べる（5秒。ブラウザは起こさない）
      │    └ 投稿が要る時だけ:
      │         docker start wnl-chrome → Playwright で x.com に打つ → 固定 → docker stop
      └ schedule_data.json / history.jsonl が変わっていれば commit → push（deploy key）
```

| 物 | 場所（NAS） |
|---|---|
| リポジトリの clone | `/volume1/homes/ryo/wnl/repo` |
| Python 3.9 の venv（playwright, tweepy） | `/volume1/homes/ryo/wnl/venv` |
| Chromium の profile（X の cookie が入っている） | `/volume1/homes/ryo/wnl/chrome-data` |
| ログ・ロック・失敗回数・cookie の控え | `/volume1/homes/ryo/wnl/.local/`（git の外） |
| Docker コンテナ | `wnl-chrome`（`chromedp/headless-shell:stable`、ARM64、362MB）。CDP を `127.0.0.1:9333` に出す |

`src/x_browser.py` がブラウザ操作の本体。窓の起こし方・畳み方は環境変数
`X_BROWSER_START` / `X_BROWSER_STOP`（`nas_run.sh` が docker のコマンドを渡す）。

## 実測（DS220j: ARM 4コア 1.4GHz、メモリ 1GB）

| 段階 | 経過 | コンテナのメモリ |
|---|---|---|
| Chromium 起動 | 3〜5秒 | 50MB |
| x.com/compose 読み込み | 18秒 | 165MB |
| 入力欄が押せるまで | 26秒 | 220MB 前後 |
| 投稿1件（送信・id 取得・固定込み） | 1〜2分 | 最大 260MB |

**x.com は ARM に重い。** 1280 幅＋画像ありだと 1コマ 1 秒（2コマ/2秒）で、
Playwright の「見えた」判定に 1 分かかった。**700 幅**（脇の欄が消える）にして
**画像・動画を `page.route` で読まない**と 60fps（122コマ/2秒）に戻る。
幅は `X_VIEWPORT_W`（既定 700）で変えられる。

## 初期設定の手順（作り直す時）

1. パッケージセンターで **Python 3.9 / Container Manager（Docker）/ Git Server** を入れる
2. コントロールパネル → 端末と SNMP → **SSH を有効**。管理者グループのユーザーで入る
3. Python の pip はパッケージに無いので `python3.9 -m ensurepip --user`。
   `python3.9 -m venv /volume1/homes/ryo/wnl/venv && venv/bin/pip install playwright tweepy requests-oauthlib`
   （Playwright の ARM64 ドライバはこれで入る。ブラウザ本体は Docker 側なので `playwright install` は不要）
4. docker を sudo なしで:
   `sudo sh -c 'echo "ryo ALL=(root) NOPASSWD: /usr/local/bin/docker" > /etc/sudoers.d/ryo-docker && chmod 440 /etc/sudoers.d/ryo-docker'`
5. コンテナを作る（起こすのは `nas_run.sh` がやる）:
   ```sh
   sudo docker pull chromedp/headless-shell:stable
   sudo docker create --name wnl-chrome -p 127.0.0.1:9333:9222 \
     -v /volume1/homes/ryo/wnl/chrome-data:/data --shm-size=256m \
     chromedp/headless-shell:stable --no-sandbox --user-data-dir=/data --window-size=1280,900 --lang=ja-JP
   ```
   このイメージは自分で 9223 で起動して socat で 9222 に出すので、`--remote-debugging-*` は渡さない（渡すと bind に失敗する）
6. GitHub へ push する鍵: `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_github`、`~/.ssh/config` に
   `Host github.com / IdentityFile ~/.ssh/id_ed25519_github`。公開鍵をリポジトリの
   **Deploy keys に書き込み可で登録**（`gh repo deploy-key add … --allow-write`）
7. `git clone git@github.com:weather-news-twitter-bot/weather-news-twitter-bot.git /volume1/homes/ryo/wnl/repo`
8. X の cookie を入れる（下の「cookie の入れ直し」）
9. タスクスケジューラに登録（下）

## タスクスケジューラの設定

コントロールパネル → タスクスケジューラ → 作成 → 予約タスク → ユーザー指定のスクリプト

| 欄 | 値 |
|---|---|
| タスク | `WNL-Timetable` |
| ユーザー | `ryo`（root にしない。root だと `~/.ssh` が `/root` になって push の鍵が見つからない） |
| スケジュール | 毎日 / 最初の実行 00:00 / **20分ごと** / 最後の実行 **23:40** |
| 実行コマンド | `sh /volume1/homes/ryo/wnl/repo/scripts/nas_run.sh` |
| 通知 | 「実行の詳細をメールで送信」＋「**スクリプトが異常終了した場合のみ**」 |

`synoschedtask --get id=N` の `User: [root]` 表示は当てにならない（実際は ryo で走る。
ログの見出し `user=ryo` が本当の値）。

## 失敗の知らせ（メール）

`nas_run.sh` は **3回続けて失敗した時だけ**異常終了する（1回の失敗は 20分後に取り返す
ので黙る）。以後も続けば 12時間ごとに 1回。異常終了の時は標準出力にログの末尾 40行を
出し、DSM がそれを本文にしてメールする:

```
[DS220j] タスク スケジューラは、予定されているタスクを完了しました
  現在のステータス：1 (中断)
  標準出力/エラー：
  WNL 番組表 bot が 3 回続けて失敗しています（20分おき）。ログの末尾:
  ...
```

DSM 側の設定: コントロールパネル → 通知 → メール。**Gmail の OAuth 連携はテストメールが
403 で送れなかった**ので、「カスタム SMTP サーバー」で `smtp.gmail.com:465`（SSL）＋
Google の**アプリ パスワード**にした。受信者は **メールアドレスを最後まで**（`.com` 抜けで
一度届かなかった）。

試験: `touch /volume1/homes/ryo/wnl/.local/test_mail` を置いて次の回を待つ（または
タスクを「実行」）。1度だけ「メール通知の試験です」で異常終了して目印は消える。

## cookie の入れ直し（「X にログインしていません」が出た時）

X のログインは数か月で切れることがある。切れると投稿が失敗し、3回目でメールが来る。

1. PC のデバッグ用 Edge（CDP 9333、@wnl_timetable でログイン済み）から x.com の cookie を取る:
   Playwright で `connect_over_cdp` → `ctx.cookies()` を `x.com` / `twitter.com` で絞って JSON に
2. NAS の `/volume1/homes/ryo/wnl/.local/x_cookies.json` に置く（`chmod 600`）
3. コンテナを起こし、`ctx.add_cookies(cookies)` で入れる（`partitionKey` は捨て、`sameSite` が
   `Strict/Lax/None` 以外なら `Lax` に）。profile に残るのでコンテナを立て直しても消えない
4. `https://x.com/home` を開いてプロフィールリンクが `/wnl_timetable` を指せば OK

## 手で確かめる

```sh
ssh ryo@ds220j
cd /volume1/homes/ryo/wnl/repo
sh scripts/nas_run.sh --dry-run              # 取得と差分だけ。投稿も保存もしない
sh scripts/nas_run.sh --dry-run --announce   # 時刻に関係なく告知の本文を組む
tail -40 /volume1/homes/ryo/wnl/.local/nas_run.log
sudo docker ps -a                            # wnl-chrome は普段 Exited でよい
```

## やめたもの

- **GitHub Actions の cron**（`bot.yml` の `schedule:`）。書き手が2つになると
  `schedule_data.json` が食い違い、NAS の `git pull --ff-only` が通らなくなる。
  手動実行（`workflow_dispatch`、`TWEET_VIA=none` の dry-run）だけ残した
- **PC のタスク `WNL-Timetable-Tweet`**（`run.cmd` → `src/tweet_local.py`）。無効化した。
  `tweet_local.py` は残っているが、画面操作は `x_browser.py` に移してあり、今は誰も呼ばない
- **tweepy（`TWEET_VIA=api`）**。コードは残してある。クレジットを入れれば戻せる
