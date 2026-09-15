"""翌日の番組表を、ローカル PC のブラウザから X に1日1回だけ告知する。

2026-09-11 に X API が従量課金になり（402 credits depleted）、無料では投稿
できなくなった。代わりに、@wnl_timetable でログイン済みのデバッグ用 Edge
（CDP 9333。クロストーク切り抜きの投稿と同じ窓）に Playwright で繋いで、
投稿画面に本文を入れて送る。API もクレジットも使わない。

役割分担:
  - GitHub Actions（weather_bot.py, TWEET_VIA=none）… 番組表の記録だけ続ける
  - このスクリプト（タスクスケジューラ）… 21時〜翌05時に PC が起きていたら告知1本
両者は状態を共有しない。こちらは「今日はもう告知したか」を .local/announced.json
で覚えるだけ（.gitignore 済み。git には触らない）。

    python src\\tweet_local.py            # 21時〜05時なら告知（1日1回）
    python src\\tweet_local.py --dry-run  # 本文を出すだけ
    python src\\tweet_local.py --force    # 時刻・告知済みを無視して出す（試験用）
    python src\\tweet_local.py --no-pin   # 固定ポストにしない
"""

import argparse
import json
import os
import sys
from datetime import timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import weather_bot as wb  # noqa: E402

# 置き場はリポジトリ内の .local/（.gitignore 済み）。%LOCALAPPDATA% は使わない:
# Microsoft Store 版 Python は AppData への書き込みを Packages\...\LocalCache に
# 黙って付け替えるので、別の Python から見ると「無い」ことになり二重投稿になる。
STATE = os.path.join(os.path.dirname(HERE), ".local", "announced.json")


def log(msg: str) -> None:
    wb.log(msg)


# ============================ 告知済みの記憶 ============================
def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(d: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


# ============================ ブラウザ操作 ============================
# 画面の操作は x_browser.py に移した（NAS の weather_bot.py と同じ手順を使う）。
import x_browser  # noqa: E402

x_browser.set_logger(log)


def post_in_browser(text: str, marker: str, pin: bool) -> str | None:
    return x_browser.post(text, pin=pin)


# ============================ 本体 ============================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-pin", action="store_true")
    args = ap.parse_args()

    now = wb.now_jst()
    log(f"=== 番組表の告知（ローカル） {now.strftime('%Y-%m-%d %H:%M')} ===")
    in_window = now.hour >= wb.ANNOUNCE_HOUR or now.hour < wb.DAY_START_HOUR
    if not in_window and not args.force:
        log("21時〜05時の外なので何もしない")
        return 0

    target = wb.today_bday(now) + timedelta(days=1)
    state = load_state()
    if state.get("announced_date") == target.isoformat() and not args.force:
        log(f"{target} は告知済み")
        return 0

    entries = wb.fetch_entries()
    if not entries:
        log("番組表が取得できず。次の回に回す")
        return 1
    dated = wb.assign_broadcast_dates(entries, now)
    raw = wb.lineup_for(dated, target, pad_standard=False)
    if not any(p["status"] == "confirmed" for p in raw):
        log("翌日の確定キャスターがまだ無い。次の回に回す")
        return 1
    lineup = wb.lineup_for(dated, target, pad_standard=True)
    text = wb.build_announce_tweet(target, lineup)
    marker = f"{wb.format_jp_date(target)} WNL番組表"
    log("=== 告知ツイート ===\n" + text)

    if args.dry_run:
        log("dry-run: 投稿しない")
        return 0

    sid = post_in_browser(text, marker, pin=not args.no_pin)
    if not sid:
        log("投稿できず。次の回に回す")
        return 1
    save_state({"announced_date": target.isoformat(), "status_id": sid,
                "ts": now.isoformat()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
