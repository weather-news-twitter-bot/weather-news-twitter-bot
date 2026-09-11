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
import re
import sys
from datetime import timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import weather_bot as wb  # noqa: E402

CDP = os.getenv("X_CDP", "http://127.0.0.1:9333")
HANDLE = "wnl_timetable"
COMPOSE = "https://x.com/compose/post"
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
def type_text(page, text: str) -> None:
    box = page.locator('div[data-testid="tweetTextarea_0"]').first
    box.wait_for(state="visible", timeout=20000)
    box.click()
    # 改行は Enter だと送信に割り当たることがあるので、行ごとに入れる
    for i, line in enumerate(text.split("\n")):
        if i:
            page.keyboard.press("Shift+Enter")
        if line:
            page.keyboard.type(line, delay=6)
    # 末尾がハッシュタグだと候補の吹き出しが出たままになり、投稿ボタンが押せない
    # （Playwright が「安定していない」と判断して待ち続ける）。空白1つで閉じる。
    # 末尾の空白は X 側で落ちるので本文は変わらない。
    page.keyboard.type(" ")


def click_send(page) -> bool:
    for name in ("tweetButton", "tweetButtonInline"):
        try:
            btn = page.locator(f'button[data-testid="{name}"]').first
            if btn.count() and btn.is_enabled():
                btn.click(timeout=6000)
                return True
        except Exception:
            continue
    return False


def find_status_id(page, marker: str) -> str | None:
    """
    投稿直後のトーストの「表示」リンクから status id を取る。取れなければ
    プロフィールを開いて、本文に marker（日付行）を含む最新の投稿を探す。
    """
    try:
        a = page.locator('[data-testid="toast"] a[href*="/status/"]').first
        a.wait_for(state="visible", timeout=8000)
        m = re.search(r"/status/(\d+)", a.get_attribute("href") or "")
        if m:
            return m.group(1)
    except Exception:
        pass
    try:
        page.goto(f"https://x.com/{HANDLE}", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        arts = page.locator("article")
        for i in range(min(arts.count(), 8)):
            art = arts.nth(i)
            if marker not in (art.inner_text() or ""):
                continue
            links = art.locator('a[href*="/status/"]')
            for j in range(links.count()):
                m = re.search(r"/status/(\d+)", links.nth(j).get_attribute("href") or "")
                if m:
                    return m.group(1)
    except Exception as e:
        log(f"投稿の id を探せません: {str(e)[:100]}")
    return None


def pin_in_browser(page, status_id: str) -> bool:
    """投稿ページの「…」→「プロフィールに固定する」→ 確認。前の固定は自動で外れる。"""
    try:
        page.goto(f"https://x.com/{HANDLE}/status/{status_id}", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        page.locator('article [data-testid="caret"]').first.click(timeout=10000)
        item = page.locator('[role="menuitem"]', has_text=re.compile("固定|Pin")).first
        item.wait_for(state="visible", timeout=8000)
        if re.search("固定を解除|Unpin", item.inner_text() or ""):
            log("既に固定済み")
            return True
        item.click()
        page.locator('[data-testid="confirmationSheetConfirm"]').first.click(timeout=8000)
        page.wait_for_timeout(2000)
        log(f"固定ポストに設定: {status_id}")
        return True
    except Exception as e:
        log(f"固定ポスト設定に失敗（告知は成功扱い）: {str(e)[:150]}")
        return False


def post_in_browser(text: str, marker: str, pin: bool) -> str | None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP, timeout=8000)
        except Exception as e:
            log(f"ブラウザ({CDP})に繋がりません: {str(e)[:100]}")
            return None
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto(COMPOSE, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            if "login" in page.url or "i/flow" in page.url:
                log("X にログインしていません")
                return None
            type_text(page, text)
            page.wait_for_timeout(1500)
            if not click_send(page):
                log("投稿ボタンを押せませんでした")
                return None
            page.wait_for_timeout(3000)
            sid = find_status_id(page, marker)
            log(f"投稿しました: https://x.com/{HANDLE}/status/{sid or '?'}")
            if pin and sid:
                pin_in_browser(page, sid)
            elif pin:
                log("id が取れなかったので固定は見送り")
            return sid or "posted"
        finally:
            try:
                page.close()
            except Exception:
                pass


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
