"""ログイン済みのブラウザ（CDP）から X に投稿する。API もクレジットも使わない。

2026-09-11 に X API が従量課金になったので、投稿はブラウザ経由に移した。
繋ぐ先は環境変数 X_CDP（既定 http://127.0.0.1:9333）。窓は2種類ある:

  - Windows PC … @wnl_timetable でログイン済みのデバッグ用 Edge（クロストーク
    投稿と同じ窓）。居なければ隣の WeatherNewsCrosstalk/scripts/edge_up.py で起こす
  - NAS（DS220j）… Docker の chromedp/headless-shell（wnl-chrome）。cookie は
    /volume1/homes/ryo/wnl/chrome-data の profile に入れてある。起こし方・畳み方は
    環境変数 X_BROWSER_START / X_BROWSER_STOP のシェルコマンドで渡す

呼ぶ側は post() と pin() だけ見ればよい。ブラウザは最初の post() で起こし、
プロセス終了時（atexit）に、この回が起こした時に限り畳む。
"""

import atexit
import os
import re
import subprocess
import sys
from typing import Callable, Optional

CDP = os.getenv("X_CDP", "http://127.0.0.1:9333")
HANDLE = "wnl_timetable"
COMPOSE = "https://x.com/compose/post"
START_CMD = os.getenv("X_BROWSER_START")   # 例: sudo -n /usr/local/bin/docker start wnl-chrome
STOP_CMD = os.getenv("X_BROWSER_STOP")     # 例: sudo -n /usr/local/bin/docker stop -t 3 wnl-chrome

_log: Callable[[str], None] = print
_started_here = False


def set_logger(fn: Callable[[str], None]) -> None:
    global _log
    _log = fn


# ============================ ブラウザの起動・停止 ============================
def alive(timeout: float = 3) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(CDP.rstrip("/") + "/json/version", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_alive(sec: int) -> bool:
    import time
    for _ in range(sec):
        if alive():
            return True
        time.sleep(1)
    return False


def ensure_browser() -> bool:
    """CDP の窓が居なければ起こす。Returns: この回が起こしたか（True なら後で畳む）。"""
    global _started_here
    if alive():
        return False
    if START_CMD:
        _log("ブラウザを起こします: " + START_CMD)
        subprocess.run(START_CMD, shell=True, check=False, timeout=60)
        if not _wait_alive(30):
            _log("ブラウザが上がりません")
            return False
        _started_here = True
        atexit.register(close_browser)
        return True
    # Windows PC: 隣のクロストーク側の edge_up.py に任せる（無い環境では何もしない）
    sib = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "WeatherNewsCrosstalk", "scripts")
    if not os.path.exists(os.path.join(sib, "edge_up.py")):
        return False
    sys.path.insert(0, sib)
    try:
        from edge_up import ensure_edge
        if ensure_edge(log=_log, headless=True):
            _started_here = True
            atexit.register(close_browser)
            return True
    except Exception as e:
        _log(f"Edge の起動確認に失敗（そのまま繋ぎに行く）: {str(e)[:120]}")
    return False


def close_browser() -> None:
    """ensure_browser が起こした窓を畳む（人が開いていた窓には使わない）。"""
    global _started_here
    if not _started_here:
        return
    _started_here = False
    try:
        if STOP_CMD:
            subprocess.run(STOP_CMD, shell=True, check=False, timeout=60)
            return
        from tabs import shutdown  # Windows PC（edge_up.py と同じ場所）
        shutdown(log=_log)
    except Exception as e:
        _log(f"ブラウザを畳めませんでした（続けます）: {str(e)[:120]}")


# ============================ 画面操作 ============================
def type_text(page, text: str) -> None:
    box = page.locator('div[data-testid="tweetTextarea_0"]').first
    # NAS（ARM）では投稿画面が描かれるまで 15〜20 秒かかるので長めに待つ
    box.wait_for(state="visible", timeout=60000)
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


def find_status_id(page, marker: str) -> Optional[str]:
    """
    投稿直後のトーストの「表示」リンクから status id を取る。取れなければ
    プロフィールを開いて、本文に marker（日付行）を含む最新の投稿を探す。
    プロフィールの先頭は固定ポスト（前回の同じ日付の通知かもしれない）なので飛ばす。
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
            body = art.inner_text() or ""
            if marker not in body or art.locator('[data-testid="socialContext"]').count():
                continue
            links = art.locator('a[href*="/status/"]')
            for j in range(links.count()):
                m = re.search(r"/status/(\d+)", links.nth(j).get_attribute("href") or "")
                if m:
                    return m.group(1)
    except Exception as e:
        _log(f"投稿の id を探せません: {str(e)[:100]}")
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
            _log("既に固定済み")
            return True
        item.click()
        page.locator('[data-testid="confirmationSheetConfirm"]').first.click(timeout=8000)
        page.wait_for_timeout(2000)
        _log(f"固定ポストに設定: {status_id}")
        return True
    except Exception as e:
        _log(f"固定ポスト設定に失敗（投稿は成功扱い）: {str(e)[:150]}")
        return False


# ============================ 入口 ============================
def marker_of(text: str) -> str:
    """本文から「2026年06月21日 WNL番組表」の行を取る（プロフィールで探す時の目印）。"""
    m = re.search(r"\d{4}年\d{2}月\d{2}日 WNL番組表", text)
    return m.group(0) if m else text.split("\n")[0]


def _open(p):
    try:
        browser = p.chromium.connect_over_cdp(CDP, timeout=20000)
    except Exception as e:
        _log(f"ブラウザ({CDP})に繋がりません: {str(e)[:100]}")
        return None, None
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.new_page()
    # NAS（DS220j, ARM 1.4GHz）は x.com の描画が重く、1280 幅＋画像ありだと
    # 1コマ 1 秒（Playwright の「見えた」判定が 1 分待ち）。700 幅で脇の欄を消し、
    # 画像・動画を読まなければ 60fps に戻る（2026-09-16 実測: 入力欄まで 26 秒）。
    page.set_viewport_size({"width": int(os.getenv("X_VIEWPORT_W", "700")), "height": 900})
    page.route(re.compile(r"\.(png|jpe?g|gif|webp|mp4|m3u8|ts)(\?|$)|/video/|pbs\.twimg\.com|video\.twimg\.com"),
               lambda r: r.abort())
    return browser, page


def post(text: str, pin: bool = False) -> Optional[str]:
    """本文を投稿して status id を返す（取れなければ 'posted'、失敗は None）。"""
    from playwright.sync_api import sync_playwright
    ensure_browser()
    marker = marker_of(text)
    with sync_playwright() as p:
        _, page = _open(p)
        if page is None:
            return None
        try:
            page.goto(COMPOSE, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            if "login" in page.url or "i/flow" in page.url or "mode=login" in page.url:
                _log("X にログインしていません")
                return None
            type_text(page, text)
            page.wait_for_timeout(1500)
            if not click_send(page):
                _log("投稿ボタンを押せませんでした")
                return None
            page.wait_for_timeout(3000)
            sid = find_status_id(page, marker)
            _log(f"投稿しました: https://x.com/{HANDLE}/status/{sid or '?'}")
            if pin and sid:
                pin_in_browser(page, sid)
            elif pin:
                _log("id が取れなかったので固定は見送り")
            return sid or "posted"
        finally:
            try:
                page.close()
            except Exception:
                pass


def pin(status_id: str) -> bool:
    """既にある投稿を固定ポストにする。"""
    if not status_id or not status_id.isdigit():
        _log("id が無いので固定は見送り")
        return False
    from playwright.sync_api import sync_playwright
    ensure_browser()
    with sync_playwright() as p:
        _, page = _open(p)
        if page is None:
            return False
        try:
            return pin_in_browser(page, status_id)
        finally:
            try:
                page.close()
            except Exception:
                pass
