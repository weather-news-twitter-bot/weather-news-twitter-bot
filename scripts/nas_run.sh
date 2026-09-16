#!/bin/sh
# NAS（Synology DS220j）のタスクスケジューラから 20 分おきに呼ぶ入口。
#
#   番組表を取って差分を見る → 要る時だけ Docker の Chromium を起こして X に打つ
#   → schedule_data.json / history.jsonl が変わっていれば commit して push
#
# 2026-09-16 に GitHub Actions（記録だけ）＋ PC（21時の告知だけ）の二本立てを
# やめて、NAS 1台に寄せた。PC が寝ていても毎時の変更通知が出る。
#
# 置き場（NAS 側、git の外）:
#   /volume1/homes/ryo/wnl/venv         Python 3.9 の venv（playwright 入り）
#   /volume1/homes/ryo/wnl/repo         このリポジトリの clone（deploy key で push）
#   /volume1/homes/ryo/wnl/chrome-data  Chromium の profile（@wnl_timetable の cookie）
#   /volume1/homes/ryo/wnl/.local/      ログ・ロック
#
# 試験:  sh scripts/nas_run.sh --dry-run     （投稿も保存もしない）
#        sh scripts/nas_run.sh --announce    （時刻に関係なく告知判定を走らせる。--dry-run と併用）

BASE=/volume1/homes/ryo/wnl
REPO=$BASE/repo
LOCAL=$BASE/.local
LOG=$LOCAL/nas_run.log
LOCK=$LOCAL/nas_run.lock

export PATH=/usr/local/bin:/usr/bin:/bin:$PATH
export HOME=/volume1/homes/ryo
export TZ=Asia/Tokyo
export PYTHONUTF8=1
export TWEET_VIA=browser
export X_CDP=http://127.0.0.1:9333
export X_BROWSER_START="sudo -n /usr/local/bin/docker start wnl-chrome"
export X_BROWSER_STOP="sudo -n /usr/local/bin/docker stop -t 3 wnl-chrome"
export X_COOKIES=$LOCAL/x_cookies.json     # 固定は cookie 直送（ブラウザ無し）。無ければブラウザ

for a in "$@"; do
  case "$a" in
    --dry-run)  export SKIP_TWEET_FLAG=true ;;
    --announce) export ANNOUNCE_TEST=true ;;
  esac
done

mkdir -p "$LOCAL"
# 前の回がまだ走っていたら（ブラウザで2分ほどかかる）重ねない。30分以上前のロックは死骸とみなす
if [ -d "$LOCK" ]; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30)" ]; then rmdir "$LOCK"; else exit 0; fi
fi
mkdir "$LOCK" || exit 0
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# ログは 2MB を超えたら半分に切る
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 2000000 ]; then
  tail -c 1000000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

{
  echo "=== $(date '+%F %T') user=$(id -un) $* ==="
  cd "$REPO" || exit 1
  git pull -q --ff-only 2>&1
  "$BASE/venv/bin/python" src/weather_bot.py 2>&1
  rc=$?
  if [ -z "$SKIP_TWEET_FLAG" ] && ! git diff --quiet -- schedule_data.json history.jsonl; then
    git add schedule_data.json history.jsonl
    git -c user.name="WNL NAS bot" -c user.email="weather-news-twitter-bot@users.noreply.github.com" \
        commit -q -m "BOT: update schedule state" && git push -q 2>&1 && echo "push 済み"
  fi
  echo "rc=$rc"
} >> "$LOG" 2>&1

# ---- 失敗が続いた時だけ異常終了にする（DSM タスクスケジューラの「異常終了時にメール」に乗せる）----
# 1回の失敗（番組表が取れない・投稿画面が重い）は 20 分後に自分で取り返すので黙る。
# 3回続いたら1通、その後も続くなら 12 時間ごとに1通。メール本文にはログの末尾を載せる。
STREAK=$LOCAL/fail_streak
[ -n "$SKIP_TWEET_FLAG" ] && exit $rc
# メール通知の試験: .local/test_mail を置いておくと、次の回に1度だけ異常終了して消える
if [ -f "$LOCAL/test_mail" ]; then
  rm -f "$LOCAL/test_mail"
  echo "WNL 番組表 bot のメール通知の試験です（本物の失敗ではない）。ログの末尾:"
  echo
  tail -12 "$LOG"
  exit 1
fi
if [ "$rc" -eq 0 ]; then
  rm -f "$STREAK"
  exit 0
fi
n=$(( $(cat "$STREAK" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$STREAK"
if [ "$n" -eq 3 ] || [ $(( n % 36 )) -eq 0 ]; then
  echo "WNL 番組表 bot が ${n} 回続けて失敗しています（20分おき）。ログの末尾:"
  echo
  tail -40 "$LOG"
  exit 1
fi
exit 0
