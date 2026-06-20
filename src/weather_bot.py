#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表Bot（reconcile方式 / 毎時1回実行）

1回の実行（GitHub Actions・毎時）で、状況に応じて次を行う:
  - 確定:  追跡中の放送日のラインナップを取得し、保存(baseline)を更新
  - 告知:  21時以降・未告知なら、翌日のラインナップをツイート（未定枠は「未定」表示）
  - 決定:  未定だった枠にキャスターが付いたらツイート
  - 変更:  確定キャスターが別の確定キャスターに変わったらツイート

「今日/明日」の取り違え防止は3層:
  1. now基準の放送日付与（05:00開始の放送日で各枠を区切る）
  2. git保存の target_date（＝今追っている放送日のアンカー）
  3. 番組名による判別（'・'付き=キャスター番組 / generic "ウェザーニュースLiVE"=深夜無人）

データ源:
  - 番組表JSON:  https://site.weathernews.jp/site/live/json/timetable.json
  - コード→漢字名: timetable.html の caster_trans/caster_kanji を実行時抽出（失敗時は内蔵辞書）

テスト用環境変数:
  - SKIP_TWEET_FLAG=true : 投稿・保存をスキップ（dry-run）
  - TEST_NOW=2026-06-20T21:30 : 現在時刻を上書き
  - ANNOUNCE_TEST=true : 時刻に関係なく告知判定を走らせる
"""
import os
import re
import sys
import json
import time
import urllib.request
from datetime import datetime, date, timezone, timedelta
from typing import Optional

# ============================ 定数 ============================
JST = timezone(timedelta(hours=9))
TIMETABLE_JSON_URL = "https://site.weathernews.jp/site/live/json/timetable.json"
TIMETABLE_HTML_URL = "https://weathernews.jp/wnl/timetable.html"
DATA_FILE = 'schedule_data.json'

# 翌日告知を出す時刻（JST）。この時刻以降の最初の実行で告知する。
ANNOUNCE_HOUR = 21
# 放送日の境界（05:00開始）
DAY_START_HOUR = 5

MAX_RETRIES = 5
RETRY_DELAY_SEC = 15
HTTP_TIMEOUT_SEC = 30
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

# 標準枠（告知時に未定プレースホルダを埋めるため）
STANDARD_SLOTS = {
    '05:00': 'ウェザーニュースLiVE・モーニング',
    '08:00': 'ウェザーニュースLiVE・サンシャイン',
    '11:00': 'ウェザーニュースLiVE・コーヒータイム',
    '14:00': 'ウェザーニュースLiVE・アフタヌーン',
    '17:00': 'ウェザーニュースLiVE・イブニング',
    '20:00': 'ウェザーニュースLiVE・ムーン',
}

# キャスターコード正規化 / 漢字名表のフォールバック（ページ抽出失敗時に使用）
FALLBACK_CASTER_TRANS = {
    'ailin': 'yamagishi', 'hiyama2018': 'hiyama', 'izumin': 'maie',
    'komaki2018': 'komaki', 'matsu': 'matsuyuki', 'ohshima': 'oshima',
    'sayane': 'egawa', 'yuki': 'uchida', 'aohara2023': 'aohara',
    'okamoto2023': 'okamoto', 'tanabe2025': 'tanabe', 'matsumoto2025': 'matsumoto',
}
FALLBACK_CASTER_KANJI = {
    'yamagishi': '山岸 愛梨', 'egawa': '江川 清音', 'maie': '眞家 泉',
    'matsuyuki': '松雪 彩花', 'shirai': '白井 ゆかり', 'takayama': '高山 奈々',
    'hiyama': '檜山 沙耶', 'komaki': '駒木 結衣', 'uchida': '内田 侑希',
    'oshima': '大島 璃音', 'tokita': '戸北 美月', 'kawabata': '川畑 玲',
    'kobayashi': '小林 李衣奈', 'ogawa': '小川 千奈', 'uozumi': '魚住 茉由',
    'aohara': '青原 桃香', 'okamoto': '岡本 結子 リサ', 'fukuyoshi': '福吉 貴文',
    'tanabe': '田辺 真南葉', 'matsumoto': '松本 真央',
}
_CASTER_MAPS = None


# ============================ ユーティリティ ============================
def log(message: str) -> None:
    """タイムスタンプ付きでstderrにログ出力する。"""
    print(f"[{now_jst().strftime('%H:%M:%S')}] {message}", file=sys.stderr)


def now_jst() -> datetime:
    """
    現在の日本時間を返す。TEST_NOW があればそれを使う（テスト用）。

    Examples:
        >>> os.environ['TEST_NOW'] = '2026-06-20T21:30'
        >>> now_jst().hour
        21
    """
    override = os.getenv('TEST_NOW')
    if override:
        try:
            dt = datetime.fromisoformat(override)
            return dt.replace(tzinfo=JST) if dt.tzinfo is None else dt.astimezone(JST)
        except ValueError:
            log(f"TEST_NOW の形式が不正: {override}")
    return datetime.now(JST)


def is_dry_run() -> bool:
    """動作確認モード（投稿・保存をスキップ）かどうか。"""
    return os.getenv('SKIP_TWEET_FLAG') == 'true'


def format_jp_date(d: date) -> str:
    """date を「2026年06月21日」形式にする。"""
    return f"{d.year}年{d.month:02d}月{d.day:02d}日"


def slot_minutes(hhmm: str) -> int:
    """'HH:MM' を 0時起点の分に変換する。"""
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


# ============================ HTTP / キャスター対応表 ============================
def http_get(url: str, cache_bust: bool = True) -> str:
    """URLをGETして本文(UTF-8)を返す。cache_bust=True でキャッシュ回避クエリを付与。"""
    if cache_bust:
        sep = '&' if '?' in url else '?'
        url = f"{url}{sep}tm={int(time.time() * 1000)}"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return resp.read().decode('utf-8', errors='replace')


def parse_js_caster_map(html: str, func_name: str) -> dict:
    """
    ページJSの caster_trans()/caster_kanji() のような
    `if(x == "key"){ ret_name = "value"; }` 形式の対応表を抽出する。
    """
    start = html.find(f'function {func_name}(')
    if start == -1:
        return {}
    end = html.find('function ', start + len(f'function {func_name}('))
    body = html[start:end] if end != -1 else html[start:start + 8000]
    pairs = re.findall(
        r'==\s*"([^"]+)"\s*\)\s*\{\s*ret_name\s*=\s*"([^"]+)"',
        body
    )
    return {k: v for k, v in pairs}


def get_caster_maps() -> tuple[dict, dict]:
    """
    キャスターコード正規化表 / 漢字名表を取得する（プロセス内キャッシュ）。
    まず timetable.html から動的抽出し、失敗時はフォールバック辞書を使う。
    """
    global _CASTER_MAPS
    if _CASTER_MAPS is not None:
        return _CASTER_MAPS

    trans_map, kanji_map = {}, {}
    try:
        html = http_get(TIMETABLE_HTML_URL)
        trans_map = parse_js_caster_map(html, 'caster_trans')
        kanji_map = parse_js_caster_map(html, 'caster_kanji')
        log(f"キャスター対応表を抽出: 正規化{len(trans_map)}件 / 漢字{len(kanji_map)}件")
    except Exception as e:
        log(f"キャスター対応表の抽出に失敗: {e}")

    if not kanji_map:
        log("ページからの抽出に失敗 → ハードコード辞書を使用")
        trans_map = dict(FALLBACK_CASTER_TRANS)
        kanji_map = dict(FALLBACK_CASTER_KANJI)

    _CASTER_MAPS = (trans_map, kanji_map)
    return _CASTER_MAPS


def resolve_caster_name(code: str) -> tuple[str, str]:
    """
    キャスターコードを (漢字名, プロフィールURL) に解決する。
    サイトと同じ2段変換（caster_trans → caster_kanji）。未知コードは漢字名にコードを返す。
    """
    trans_map, kanji_map = get_caster_maps()
    normalized = trans_map.get(code, code)
    name = kanji_map.get(normalized)
    profile_url = f"https://weathernews.jp/wnl/caster/{normalized}.html"
    if not name:
        log(f"未知のキャスターコード: '{code}' (正規化: '{normalized}')")
        name = normalized
    return name, profile_url


# ============================ 取得 & 放送日付与 ============================
def fetch_entries() -> Optional[list[dict]]:
    """
    JSON APIから生の番組表エントリ列を取得する（リトライ付き）。

    Returns:
        [{hour, title, caster}, ...]（時系列）。総失敗時は None。
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = http_get(TIMETABLE_JSON_URL)
            entries = json.loads(raw)
            if isinstance(entries, list) and entries:
                log(f"JSON API: {len(entries)}エントリ取得")
                return entries
            log("JSON APIのデータが空")
        except Exception as e:
            log(f"JSON API取得エラー: {e}")

        if attempt < MAX_RETRIES:
            log(f"{RETRY_DELAY_SEC}秒後にリトライ ({attempt}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY_SEC)

    return None


def today_bday(now: datetime) -> date:
    """
    「今 進行中の放送日」を返す（放送日は 05:00 開始）。
    05:00以降なら当日、05:00前なら前日。

    Examples:
        >>> today_bday(datetime(2026,6,20,21,0,tzinfo=JST))
        datetime.date(2026, 6, 20)
        >>> today_bday(datetime(2026,6,21,2,0,tzinfo=JST))
        datetime.date(2026, 6, 20)
    """
    return now.date() if now.hour >= DAY_START_HOUR else now.date() - timedelta(days=1)


def assign_broadcast_dates(entries: list[dict], now: datetime) -> list[dict]:
    """
    時系列エントリ列の各枠に「放送日(bday)」を付与する。

    放送日は 05:00 区切り。先頭(進行中の放送日)を today_bday とし、
    リスト中で 05:00 を跨ぐ度に翌放送日へ繰り上げる。キャスター枠(05:00〜20:00)は
    同一放送日内に収まるので、これで各枠の表示日付が一意に定まる。

    Returns:
        [{hour, title, caster, bday(date)}, ...]
    """
    out = []
    cur = today_bday(now)
    for e in entries:
        hour = (e.get('hour') or '').strip()
        if not re.match(r'^\d{2}:\d{2}$', hour):
            continue
        if hour == '05:00':
            # 05:00 を跨ぐ度に翌放送日へ（先頭=進行中の放送日からの最初の05:00を含む）
            cur = cur + timedelta(days=1)
        out.append({
            'hour': hour,
            'title': (e.get('title') or '').strip(),
            'caster': (e.get('caster') or '').strip(),
            'bday': cur,
        })
    return out


def is_caster_program(title: str) -> bool:
    """
    キャスターが付く番組か（'・'付きの番組名）。
    深夜の無人枠は generic "ウェザーニュースLiVE"（'・'なし）なので除外できる。
    """
    return '・' in title


def lineup_for(dated: list[dict], target: date, pad_standard: bool) -> list[dict]:
    """
    指定放送日のラインナップを組む。

    各枠: {time, caster(確定時は漢字名/未定はNone), status('confirmed'|'undecided'),
           program, profile_url}

    Args:
        pad_standard: True なら標準6枠に満たない分を「未定」で埋める（告知用）

    Returns:
        時刻順のラインナップ
    """
    by_time = {}
    for e in dated:
        if e['bday'] != target:
            continue
        if not is_caster_program(e['title']):
            continue  # 深夜無人枠はスキップ
        t = e['hour']
        if e['caster']:
            name, url = resolve_caster_name(e['caster'])
            by_time[t] = {'time': t, 'caster': name, 'status': 'confirmed',
                          'program': e['title'], 'profile_url': url}
        else:
            by_time.setdefault(t, {'time': t, 'caster': None, 'status': 'undecided',
                                   'program': e['title'], 'profile_url': ''})

    if pad_standard:
        for t, prog in STANDARD_SLOTS.items():
            by_time.setdefault(t, {'time': t, 'caster': None, 'status': 'undecided',
                                   'program': prog, 'profile_url': ''})

    return sorted(by_time.values(), key=lambda p: slot_minutes(p['time']))


def filter_upcoming(programs: list[dict], target: date, now: datetime) -> list[dict]:
    """
    放送済み枠を除外する（追跡日が今日の場合のみ）。翌日分は全て返す。
    """
    if target != today_bday(now):
        return programs
    out = []
    for p in programs:
        slot_dt = datetime.combine(target, datetime.min.time(), JST) + timedelta(minutes=slot_minutes(p['time']))
        if slot_dt >= now:
            out.append(p)
    return out


# ============================ 差分検出 ============================
def diff_lineup(baseline: list[dict], current_upcoming: list[dict]) -> tuple[list, list]:
    """
    保存baseline と 現在の未放送枠 を突き合わせ、決定/変更を抽出する。

    判定（現在が確定キャスターの枠のみ対象）:
        - 前回 未定/無 → 今回 確定 = 決定
        - 前回 確定A   → 今回 確定B = 変更
        - 同じ                     = 何もしない

    Returns:
        (decisions, changes)
        decisions: [(time, new_name), ...]
        changes:   [(time, old_name, new_name), ...]
    """
    base = {p['time']: p for p in baseline}
    decisions, changes = [], []
    for p in current_upcoming:
        if p['status'] != 'confirmed':
            continue
        t = p['time']
        prev = base.get(t)
        # baseline側は status に頼らず caster 値で「確定済みか」を判定
        # （旧フォーマット=status無し、との後方互換のため）
        prev_name = None
        if prev:
            pc = prev.get('caster')
            if pc and pc != '未定':
                prev_name = pc
        if prev_name is None:
            decisions.append((t, p['caster']))     # 未定/無 → 確定 = 決定
        elif prev_name != p['caster']:
            changes.append((t, prev_name, p['caster']))  # 確定A → 確定B = 変更
    return decisions, changes


def merge_baseline(baseline: list[dict], current: list[dict]) -> list[dict]:
    """
    baseline を現在の枠で更新する（同時刻は上書き、放送済みで消えた枠は前回値を保持）。
    """
    base = {p['time']: p for p in baseline}
    for p in current:
        base[p['time']] = p
    return sorted(base.values(), key=lambda p: slot_minutes(p['time']))


def programs_equal(a: list[dict], b: list[dict]) -> bool:
    """2つのラインナップが（時刻・キャスター・状態の観点で）同一かどうか。"""
    def key(progs):
        return [(p['time'], p.get('caster'), p.get('status'))
                for p in sorted(progs, key=lambda p: slot_minutes(p['time']))]
    return key(a) == key(b)


# ============================ ツイート生成 ============================
def build_announce_tweet(target: date, lineup: list[dict]) -> str:
    """翌日告知ツイートを生成する。未定枠は「未定」と表示。"""
    lines = [f"📺 {format_jp_date(target)} WNL番組表", ""]
    for p in lineup:
        name = p['caster'].replace(' ', '') if p['status'] == 'confirmed' else '未定'
        lines.append(f"{p['time']}- {name}")
    lines += ["", "#ウェザーニュース #番組表"]
    return "\n".join(lines)


def build_change_tweet(target: date, decisions: list, changes: list, detect_time: str) -> str:
    """決定/変更の通知ツイートを生成する（変化した枠のみ）。"""
    items = []
    for t, new in decisions:
        items.append((t, f"{t}- {new.replace(' ', '')} (未定から決定:{detect_time})"))
    for t, old, new in changes:
        items.append((t, f"{t}- {new.replace(' ', '')} ({old.replace(' ', '')}から変更:{detect_time})"))
    items.sort(key=lambda x: slot_minutes(x[0]))

    header = "📢 【番組表変更のお知らせ】\n\n"
    body = [f"📺 {format_jp_date(target)} WNL番組表(更新)", ""]
    body += [line for _, line in items]
    body += ["", "#ウェザーニュース #番組表"]
    return header + "\n".join(body)


# ============================ Twitter投稿 ============================
def post_to_twitter(tweet_text: str) -> bool:
    """ツイートを投稿する。環境変数のAPIキーで認証。成功でTrue。"""
    try:
        import tweepy
        client = tweepy.Client(
            consumer_key=os.getenv('TWITTER_API_KEY'),
            consumer_secret=os.getenv('TWITTER_API_SECRET'),
            access_token=os.getenv('TWITTER_ACCESS_TOKEN'),
            access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET'),
            wait_on_rate_limit=True
        )
        response = client.create_tweet(text=tweet_text)
        if response.data:
            log(f"ツイート成功: https://twitter.com/i/web/status/{response.data['id']}")
            return True
    except Exception as e:
        log(f"ツイートエラー: {e}")
        if hasattr(e, 'response') and e.response is not None:
            log(f"詳細: {e.response.text}")
    return False


# ============================ 永続化 ============================
def save_data(target: date, programs: list[dict], announced_date: Optional[str]) -> None:
    """
    追跡状態を保存する。

    Args:
        target: 追跡中の放送日
        programs: その日の baseline ラインナップ
        announced_date: 最後に告知した放送日(ISO) ※idempotency用
    """
    data = {
        'target_date': target.isoformat(),
        'target_date_str': format_jp_date(target),
        'announced_date': announced_date,
        'programs': programs,
        'timestamp': now_jst().isoformat(),
    }
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"保存: target={target.isoformat()} / {len(programs)}枠 / announced={announced_date}")
    except Exception as e:
        log(f"保存エラー: {e}")


def load_saved_data() -> Optional[dict]:
    """保存済みの追跡状態を読み込む。無ければ None。"""
    if not os.path.exists(DATA_FILE):
        return None
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log(f"読み込みエラー: {e}")
        return None


# ============================ reconcile（中核） ============================
def reconcile() -> bool:
    """
    1回分の照合処理。告知 / 決定・変更通知 / baseline更新 を状況に応じて行う。

    Returns:
        正常終了で True
    """
    now = now_jst()
    log(f"=== reconcile 開始 {now.strftime('%Y-%m-%d %H:%M')} ===")

    entries = fetch_entries()
    if not entries:
        log("番組表が取得できず。処理中断")
        return False
    dated = assign_broadcast_dates(entries, now)

    saved = load_saved_data() or {}
    announced_date = saved.get('announced_date')
    baseline = saved.get('programs', [])

    tb = today_bday(now)
    tomorrow = tb + timedelta(days=1)
    announce_now = (now.hour >= ANNOUNCE_HOUR) or (os.getenv('ANNOUNCE_TEST') == 'true')

    # ---------- ① 告知（21時以降・未告知） ----------
    if announce_now and announced_date != tomorrow.isoformat():
        raw_lineup = lineup_for(dated, tomorrow, pad_standard=False)
        has_confirmed = any(p['status'] == 'confirmed' for p in raw_lineup)
        if has_confirmed:
            lineup = lineup_for(dated, tomorrow, pad_standard=True)
            tweet = build_announce_tweet(tomorrow, lineup)
            log("=== 告知ツイート ===\n" + tweet)
            if is_dry_run():
                log("dry-run: 告知投稿・保存スキップ")
                return True
            if post_to_twitter(tweet):
                save_data(tomorrow, lineup, announced_date=tomorrow.isoformat())
                return True
            log("告知投稿に失敗。次回リトライ")
            return False
        else:
            log("翌日の確定キャスターがまだ無い。告知保留（次回tickで再試行）")
            # 告知できないので監視へフォールスルー

    # ---------- ② 監視（決定 / 変更） ----------
    saved_target = saved.get('target_date')
    if saved_target:
        tracked = date.fromisoformat(saved_target)
        if tracked < tb:
            log(f"追跡日 {tracked} が古い → 今日 {tb} に再アンカー")
            tracked = tb
    else:
        tracked = tb

    current = lineup_for(dated, tracked, pad_standard=False)
    if not current:
        log(f"追跡日 {tracked} のデータなし。状態維持")
        return True

    upcoming = filter_upcoming(current, tracked, now)
    decisions, changes = diff_lineup(baseline, upcoming)

    posted = True
    if decisions or changes:
        tweet = build_change_tweet(tracked, decisions, changes, now.strftime('%H:%M'))
        log(f"=== 決定{len(decisions)}件 / 変更{len(changes)}件 ===\n" + tweet)
        posted = True if is_dry_run() else post_to_twitter(tweet)
    else:
        log("決定・変更なし")

    if is_dry_run():
        log("dry-run: 保存スキップ")
        return True
    if not posted:
        log("投稿失敗。baseline更新せず（次回リトライ）")
        return False

    # 状態が変わった時だけ保存（毎時commitのノイズを避ける）
    merged = merge_baseline(baseline, current)
    state_changed = (saved.get('target_date') != tracked.isoformat()
                     or not programs_equal(baseline, merged))
    if state_changed:
        save_data(tracked, merged, announced_date=announced_date)
    else:
        log("状態変化なし → 保存スキップ（commitノイズ回避）")
    return True


# ============================ エントリーポイント ============================
def main() -> None:
    log("=== ウェザーニュースBot開始 ===")
    success = reconcile()
    try:
        with open('bot_result.json', 'w', encoding='utf-8') as f:
            json.dump({'success': success, 'timestamp': now_jst().isoformat()},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"結果出力エラー: {e}")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
