#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表取得＆Twitter投稿ボット

機能:
    - ウェザーニュースLiVEの番組表を公開JSON APIから取得
    - 担当キャスター情報をTwitterに投稿
    - 番組表の変更を検出して更新通知

データ源:
    - 番組表: https://site.weathernews.jp/site/live/json/timetable.json
      （サイトのVue.jsが描画に使う真のデータ源。caster は識別コード）
    - キャスターコード→漢字名: timetable.html の caster_trans()/caster_kanji()
      を実行時に抽出（新キャスター追加にも追従。失敗時はハードコード辞書）

実行モード (EXECUTION_MODE):
    - post:  番組表を取得してツイート投稿 (schedule-tweet.yml に指定の時刻)
    - watch: 前回データと比較し、変更があれば更新通知 (hourly_checker.yml に指定の間隔)

動作確認モード (SKIP_TWEET_FLAG=true):
    - 全処理を実行するが、ツイート投稿とコミットをスキップ
"""
import os
import json
import sys
import re
import asyncio
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Optional

# =============================================================================
# 定数
# =============================================================================
JST = timezone(timedelta(hours=9))

# 番組表の真のデータ源（サイトのVue.jsが描画に使う公開JSON）と、
# キャスターコード→漢字名の対応表を持つHTMLページ。
TIMETABLE_JSON_URL = "https://site.weathernews.jp/site/live/json/timetable.json"
TIMETABLE_HTML_URL = "https://weathernews.jp/wnl/timetable.html"
DATA_FILE = 'schedule_data.json'

# 放送日は 05:00 を境界に区切られる（05:00開始が1日の始まり）。
# 取得枠は固定しない（12:30 等の変則枠にも追従する）。標準枠はフォールバック生成にのみ使う。
STANDARD_TIME_SLOTS = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']

# 取得設定（JSON APIは安定しているのでリトライは控えめ）
MAX_RETRIES = 5
RETRY_DELAY_SEC = 15
HTTP_TIMEOUT_SEC = 30
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

# キャスターコードの正規化表 / 漢字名表のフォールバック。
# 通常はページJSから動的抽出するが、抽出失敗時はこのスナップショットを使う。
# （出典: timetable.html の caster_trans() / caster_kanji()）
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

# キャスター対応表のキャッシュ（プロセス内で1回だけ取得）
_CASTER_MAPS = None


# =============================================================================
# メイン処理
# =============================================================================
async def main():
    """
    エントリーポイント。

    2つの環境変数で動作を制御する:

    軸1: 何をするか (EXECUTION_MODE)
        - post:  番組表を取得してツイート投稿 (schedule-tweet.yml に指定の時刻)
        - watch: 前回と比較し、変更があれば更新ツイート (hourly_checker.yml に指定の間隔)

    軸2: 本当に投稿するか (SKIP_TWEET_FLAG)
        - false または未設定: 本番モード（実際に投稿）
        - true: 動作確認モード（投稿・コミットをスキップ）

    Environment Variables:
        EXECUTION_MODE: 'post'(デフォルト) or 'watch'
        SKIP_TWEET_FLAG: 'true' で動作確認モード
    """
    log("=== ウェザーニュースボット開始 ===")
    log(f"現在時刻: {now_jst().strftime('%Y-%m-%d %H:%M:%S')}")

    mode = os.getenv('EXECUTION_MODE', 'post').lower()
    log(f"実行モード: {mode}")

    if mode == 'watch':
        success = await run_watch_mode()
    else:
        success = await run_post_mode()

    # 結果ファイル出力
    result = {
        'success': success,
        'mode': mode,
        'timestamp': now_jst().isoformat()
    }
    with open('bot_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    sys.exit(0 if success else 1)


async def run_post_mode() -> bool:
    """
    投稿モード: 番組表を取得してツイート投稿。

    処理フロー:
        1. 対象日を決定
        2. 番組表を取得
        3. 対象日のデータを抽出
        4. 有効なキャスターがいればツイート投稿
        5. データを保存

    Returns:
        処理成功ならTrue
    """
    log("=== 投稿モード開始 ===")

    # 1. 対象日を決定
    target_date, target_date_str = get_target_date()

    # 2. 取得
    all_programs = await fetch_schedule()

    # 3. 対象日のデータを抽出
    programs = extract_target_day_programs(all_programs, target_date)

    if not programs:
        log("対象日のデータが取得できませんでした")
        programs = create_fallback_schedule()

    # ログ出力
    log("=== 取得データ ===")
    for p in programs:
        log(f"  {p['time']} - {p['caster']}")

    # 4. 有効なキャスターチェック
    source = 'json_api' if has_valid_caster(programs) else 'fallback'

    if not has_valid_caster(programs):
        log("有効なキャスター情報なし。ツイートをスキップ")
        save_data(programs, target_date_str, source)
        return False

    # 5. 放送済み除外 & ツイート生成
    upcoming = filter_upcoming_programs(programs, target_date)
    tweet_text = build_schedule_tweet(upcoming, target_date_str)

    # 6. ツイート投稿
    if is_dry_run():
        log("動作確認モード: ツイート投稿をスキップ")
        log("=== 生成されるツイート ===\n" + tweet_text)
        save_data(programs, target_date_str, source)
        return True

    success = post_to_twitter(tweet_text)

    # 7. データ保存
    save_data(programs, target_date_str, source)

    log(f"=== 投稿モード完了: {'成功' if success else '失敗'} ===")
    return success


async def run_watch_mode() -> bool:
    """
    監視モード: 前回データと比較し、変更があれば更新通知。

    処理フロー:
        1. 前回データを読み込み（なければ投稿モードへ）
        2. 番組表を取得
        3. 有効なキャスターチェック
        4. 変更を検出
        5. 変更があれば更新ツイート投稿
        6. データを保存

    Returns:
        処理成功ならTrue
    """
    log("=== 監視モード開始 ===")

    # 1. 前回データを読み込み
    saved = load_saved_data()
    if not saved:
        log("前回データなし。投稿モードで実行")
        return await run_post_mode()

    target_date, _ = get_target_date()
    target_date_str = saved.get('target_date_str', '日付不明')

    # 2. 取得
    all_programs = await fetch_schedule()
    programs = extract_target_day_programs(all_programs, target_date)

    if not programs:
        log("データ取得失敗。スキップ")
        return False

    # 3. 有効なキャスターチェック
    if not has_valid_caster(programs):
        log("有効なキャスター情報なし。更新チェックをスキップ")
        return False

    # 4. 変更検出 & ツイート生成
    tweet_text = build_change_tweet(
        saved['programs'],
        programs,
        target_date,
        target_date_str
    )

    if not tweet_text:
        log("変更なし")
        return True

    log("変更を検出。更新ツイートを投稿")

    # 5. ツイート投稿
    if is_dry_run():
        log("動作確認モード: ツイート投稿をスキップ")
        log("=== 生成されるツイート ===\n" + tweet_text)
        save_data(programs, target_date_str, 'json_api')
        return True

    if post_to_twitter(tweet_text):
        save_data(programs, target_date_str, 'json_api')
        log("=== 監視モード完了: 更新投稿成功 ===")
        return True
    else:
        log("ツイート失敗。データは更新しない（次回リトライ）")
        return False


# =============================================================================
# 1. 対象日の決定
# =============================================================================
def get_target_date() -> tuple[datetime, str]:
    """
    ツイート対象の日付を決定する。

    決定ルール:
        1. 環境変数 SCHEDULE_TARGET_DATE があればその日付
        2. 環境変数 SCHEDULE_TARGET_MODE が 'today' or 'tomorrow' なら従う
        3. 自動モード: 18時以降なら翌日、それ以外は今日

    Returns:
        (対象日のdatetime, 表示用文字列) のタプル

    Examples:
        >>> # 15:00に実行した場合
        >>> date, date_str = get_target_date()
        >>> print(date_str)
        2025年01月15日

        >>> # 19:00に実行した場合（自動で翌日）
        >>> date, date_str = get_target_date()
        >>> print(date_str)
        2025年01月16日

    Environment Variables:
        SCHEDULE_TARGET_DATE: 直接日付指定 (例: '2025-01-15')
        SCHEDULE_TARGET_MODE: 'today', 'tomorrow', 'auto'(デフォルト)
        SCHEDULE_THRESHOLD_HOUR: 自動モードの閾値時刻 (デフォルト: 18)
    """
    current = now_jst()

    # 1. 直接日付指定
    target_date_env = os.getenv('SCHEDULE_TARGET_DATE')
    if target_date_env:
        try:
            target = datetime.strptime(target_date_env, '%Y-%m-%d').replace(tzinfo=JST)
            target_str = target.strftime('%Y年%m月%d日')
            log(f"環境変数で指定された日付を使用: {target_str}")
            return target, target_str
        except ValueError:
            log(f"環境変数SCHEDULE_TARGET_DATEの形式が不正: {target_date_env}")

    # 2. モード指定
    mode = os.getenv('SCHEDULE_TARGET_MODE', 'auto').lower()
    threshold_hour = int(os.getenv('SCHEDULE_THRESHOLD_HOUR', '18'))

    if mode == 'tomorrow':
        target = current + timedelta(days=1)
    elif mode == 'today':
        target = current
    else:  # auto
        target = current + timedelta(days=1) if current.hour >= threshold_hour else current

    target_str = target.strftime('%Y年%m月%d日')
    log(f"対象日: {target_str} (モード: {mode})")
    return target, target_str


def is_today(target_date: datetime) -> bool:
    """
    対象日が今日かどうかを判定する。

    Args:
        target_date: 判定する日付

    Returns:
        今日ならTrue

    Examples:
        >>> target, _ = get_target_date()
        >>> if is_today(target):
        ...     print("今日の番組表です")
    """
    return target_date.date() == now_jst().date()


# =============================================================================
# 2. データ取得（JSON API）
# =============================================================================
def http_get(url: str, cache_bust: bool = True) -> str:
    """
    URLをGETして本文（テキスト）を返す。

    Args:
        url: 取得先URL
        cache_bust: True ならCDNキャッシュ回避用のクエリを付与

    Returns:
        レスポンス本文（UTF-8デコード済み）
    """
    if cache_bust:
        sep = '&' if '?' in url else '?'
        url = f"{url}{sep}tm={int(time.time() * 1000)}"

    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return resp.read().decode('utf-8', errors='replace')


def parse_js_caster_map(html: str, func_name: str) -> dict:
    """
    ページJS内の caster_trans() / caster_kanji() のような
    `if(x == "key"){ ret_name = "value"; }` 形式の対応表を抽出する。

    Args:
        html: timetable.html の本文
        func_name: 'caster_trans' or 'caster_kanji'

    Returns:
        {key: value} の辞書（抽出できなければ空辞書）

    Examples:
        >>> trans = parse_js_caster_map(html, 'caster_trans')
        >>> trans['matsumoto2025']
        'matsumoto'
    """
    start = html.find(f'function {func_name}(')
    if start == -1:
        return {}

    # 次の関数定義までを当該関数の本体とみなす
    end = html.find('function ', start + len(f'function {func_name}('))
    body = html[start:end] if end != -1 else html[start:start + 8000]

    pairs = re.findall(
        r'==\s*"([^"]+)"\s*\)\s*\{\s*ret_name\s*=\s*"([^"]+)"',
        body
    )
    return {key: value for key, value in pairs}


def get_caster_maps() -> tuple[dict, dict]:
    """
    キャスターコード正規化表 / 漢字名表を取得する（プロセス内キャッシュ）。

    まず timetable.html から動的抽出を試み、新キャスター追加にも追従する。
    抽出に失敗した場合はハードコードのスナップショットにフォールバックする。

    Returns:
        (正規化表, 漢字名表) のタプル
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

    # 漢字名表が取れなければフォールバック
    if not kanji_map:
        log("ページからの抽出に失敗 → ハードコード辞書を使用")
        trans_map = dict(FALLBACK_CASTER_TRANS)
        kanji_map = dict(FALLBACK_CASTER_KANJI)

    _CASTER_MAPS = (trans_map, kanji_map)
    return _CASTER_MAPS


def resolve_caster_name(code: str) -> tuple[str, str]:
    """
    キャスターコードを漢字名とプロフィールURLに解決する。

    サイトと同じ2段変換: caster_trans でコード正規化 → caster_kanji で漢字名。

    Args:
        code: JSONの caster フィールド（例: 'matsumoto2025'）

    Returns:
        (漢字名, プロフィールURL) のタプル。未知のコードは漢字名にコードを返す。

    Examples:
        >>> resolve_caster_name('matsumoto2025')
        ('松本 真央', 'https://weathernews.jp/wnl/caster/matsumoto.html')
    """
    trans_map, kanji_map = get_caster_maps()
    normalized = trans_map.get(code, code)
    name = kanji_map.get(normalized)
    profile_url = f"https://weathernews.jp/wnl/caster/{normalized}.html"

    if not name:
        log(f"未知のキャスターコード: '{code}' (正規化: '{normalized}')")
        name = normalized  # 暫定でローマ字表記を使う

    return name, profile_url


async def fetch_schedule() -> list[dict]:
    """
    番組表データを取得する（JSON API、リトライ付き）。

    最大MAX_RETRIES回リトライし、全滅時はフォールバックを返す。

    Returns:
        番組データのリスト（フォールバック含め必ず返る）
        各要素: {'time': '05:00', 'caster': '名前', 'program': '番組名', 'profile_url': 'URL'}

    Examples:
        >>> programs = await fetch_schedule()
        >>> for p in programs:
        ...     print(f"{p['time']} - {p['caster']}")
    """
    for attempt in range(1, MAX_RETRIES + 1):
        programs = fetch_from_json_api()
        if programs:
            return programs

        if attempt < MAX_RETRIES:
            log(f"取得失敗。{RETRY_DELAY_SEC}秒後にリトライ ({attempt}/{MAX_RETRIES})")
            await asyncio.sleep(RETRY_DELAY_SEC)
        else:
            log("全リトライ失敗。フォールバックを使用")

    return create_fallback_schedule()


def fetch_from_json_api() -> Optional[list[dict]]:
    """
    公開JSON APIから番組表を取得して整形する。

    - 取得枠は固定しない → 12:30 等の変則枠もそのまま通る
    - キャスター不在枠（深夜の自動放送、caster が空）はスキップする

    Returns:
        番組データのリスト。失敗・データなしは None。
        各要素: {'time': '05:00', 'caster': '魚住 茉由', 'program': '...', 'profile_url': '...'}

    Examples:
        >>> programs = fetch_from_json_api()
        >>> if programs:
        ...     print(f"{len(programs)}枠を取得")
    """
    try:
        raw = http_get(TIMETABLE_JSON_URL)
        entries = json.loads(raw)
    except Exception as e:
        log(f"JSON API取得エラー: {e}")
        return None

    if not isinstance(entries, list) or not entries:
        log("JSON APIのデータが空")
        return None

    programs = []
    for entry in entries:
        hour = (entry.get('hour') or '').strip()
        code = (entry.get('caster') or '').strip()
        title = (entry.get('title') or '').strip()

        # 時刻形式（HH:MM）でなければスキップ
        if not re.match(r'^\d{2}:\d{2}$', hour):
            continue

        # キャスター不在枠（深夜の自動放送）はスキップ
        if not code:
            continue

        name, profile_url = resolve_caster_name(code)
        programs.append({
            'time': hour,
            'caster': name,
            'program': title,
            'profile_url': profile_url
        })

    if not programs:
        log("有効なキャスター枠が取得できず")
        return None

    log(f"JSON API: {len(programs)}枠を取得")
    return programs


def create_fallback_schedule() -> list[dict]:
    """
    取得失敗時のフォールバック用スケジュールを生成する。

    標準枠を全て「未定」で返す。これにより has_valid_caster() が
    Falseを返し、ツイートはスキップされる（誤投稿防止）。

    Returns:
        全枠「未定」の番組データリスト

    Examples:
        >>> fallback = create_fallback_schedule()
        >>> print(fallback[0]['caster'])
        未定
    """
    log("フォールバック: 全枠「未定」のスケジュールを生成")

    program_names = {
        '05:00': 'ウェザーニュースLiVE・モーニング',
        '08:00': 'ウェザーニュースLiVE・サンシャイン',
        '11:00': 'ウェザーニュースLiVE・コーヒータイム',
        '14:00': 'ウェザーニュースLiVE・アフタヌーン',
        '17:00': 'ウェザーニュースLiVE・イブニング',
        '20:00': 'ウェザーニュースLiVE・ムーン'
    }

    return [
        {'time': t, 'caster': '未定', 'program': program_names[t], 'profile_url': ''}
        for t in STANDARD_TIME_SLOTS
    ]


# =============================================================================
# 3. データ加工
# =============================================================================
def extract_target_day_programs(all_programs: list[dict], target_date: datetime) -> list[dict]:
    """
    取得した全データから対象日の番組データのみを抽出する。

    サイトは「現在放送中～未来」の枠を時系列で表示する。
    05:00を1日の境界として、今日/明日のデータを判別する。

    Args:
        all_programs: 取得した全番組データ（時系列順）
        target_date: 抽出したい日付

    Returns:
        対象日の番組データリスト（枠数は固定しない）

    Examples:
        >>> # 18時以降に実行（今日の残り + 明日の全枠が並ぶ）
        >>> all_data = await fetch_schedule()
        >>> target, _ = get_target_date()  # 翌日が対象
        >>> tomorrow_programs = extract_target_day_programs(all_data, target)
    """
    if not all_programs:
        return []

    # 最初の 05:00 を境界として分割
    split_index = -1
    for i, program in enumerate(all_programs):
        if program['time'] == '05:00':
            split_index = i
            break

    if split_index == -1:
        # 05:00が見つからない場合は全データを返す
        day1_programs = all_programs
        day2_programs = []
    else:
        day1_programs = all_programs[:split_index]  # 05:00より前（今日の残り）
        day2_programs = all_programs[split_index:]  # 05:00以降（翌日 or 今日の全体）

    log(f"データ分割: Day1={len(day1_programs)}枠, Day2={len(day2_programs)}枠")

    # 対象日に応じて選択
    is_tomorrow = (target_date.date() - now_jst().date()).days >= 1

    if is_tomorrow:
        selected = day2_programs
        log("翌日が対象 → Day2を選択")
        # 翌々日（次の05:00以降）が混ざらないよう1放送日分に絞る
        for j in range(1, len(selected)):
            if selected[j]['time'] == '05:00':
                log(f"翌々日分を除外: {len(selected) - j}枠")
                selected = selected[:j]
                break
    else:
        selected = day1_programs if day1_programs else day2_programs
        log(f"今日が対象 → {'Day1' if day1_programs else 'Day2(補完)'}を選択")

    return selected


# =============================================================================
# 4. キャスター検証
# =============================================================================
def has_valid_caster(programs: list[dict]) -> bool:
    """
    有効なキャスター情報が1人以上いるか判定する。

    「未定」以外で、2文字以上、日本語を含む名前を有効とする。

    Args:
        programs: 番組データのリスト

    Returns:
        有効なキャスターがいればTrue

    Examples:
        >>> programs = [{'time': '05:00', 'caster': '山岸愛梨', ...}]
        >>> has_valid_caster(programs)
        True

        >>> programs = [{'time': '05:00', 'caster': '未定', ...}]
        >>> has_valid_caster(programs)
        False
    """
    for p in programs:
        caster = p.get('caster', '')
        if (caster and
            caster != '未定' and
            len(caster) >= 2 and
            re.search(r'[ぁ-んァ-ヶ一-龯]', caster)):
            return True
    return False


# =============================================================================
# 5. 放送済み枠の除外
# =============================================================================
def filter_upcoming_programs(programs: list[dict], target_date: datetime) -> list[dict]:
    """
    放送済みの枠を除外し、これから放送する枠のみを返す。

    対象日が今日の場合のみフィルタリングを行う。
    翌日の番組表の場合は全枠を返す。

    Args:
        programs: 番組データのリスト
        target_date: 対象日

    Returns:
        これから放送する枠のみのリスト

    Examples:
        >>> # 14:30に実行した場合
        >>> upcoming = filter_upcoming_programs(programs, target_date)
        >>> # 05:00, 08:00, 11:00, 14:00 の枠は除外され、
        >>> # 17:00, 20:00 の枠のみ返る
    """
    if not is_today(target_date):
        return programs

    current = now_jst()
    upcoming = []

    for program in programs:
        try:
            program_time = datetime.strptime(
                f"{target_date.strftime('%Y-%m-%d')} {program['time']}",
                '%Y-%m-%d %H:%M'
            ).replace(tzinfo=JST)

            if program_time >= current:
                upcoming.append(program)
            else:
                log(f"放送済み枠を除外: {program['time']}")
        except ValueError:
            continue

    return upcoming


# =============================================================================
# 6. ツイート生成
# =============================================================================
def build_schedule_tweet(programs: list[dict], target_date_str: str) -> str:
    """
    番組表ツイートを生成する。

    Args:
        programs: 番組データのリスト（放送済み除外済み）
        target_date_str: 表示用日付文字列

    Returns:
        ツイート本文

    Examples:
        >>> tweet = build_schedule_tweet(programs, '2025年01月15日')
        >>> print(tweet)
        📺 2025年01月15日 WNL番組表

        05:00- 山岸愛梨
        08:00- 檜山沙耶
        ...

        #ウェザーニュース #番組表
    """
    lines = [f"📺 {target_date_str} WNL番組表", ""]

    for program in programs:
        caster = program['caster'].replace(' ', '')
        lines.append(f"{program['time']}- {caster}")

    lines.extend(["", "#ウェザーニュース #番組表"])
    return "\n".join(lines)


def build_change_tweet(
    previous: list[dict],
    current: list[dict],
    target_date: datetime,
    target_date_str: str
) -> Optional[str]:
    """
    キャスター変更があった場合の更新通知ツイートを生成する。

    変更がない場合はNoneを返す。

    通知判定ロジック:
        | 前回         | 今回         | 通知     |
        |--------------|--------------|----------|
        | 山岸愛梨     | 角田奈緒子   | する     |
        | 山岸愛梨     | 未定         | しない   |
        | 山岸愛梨     | None         | しない   |
        | 未定         | 角田奈緒子   | する     |
        | 未定         | 未定         | しない   |
        | None         | 角田奈緒子   | する     |
        | None         | 未定         | しない   |
        | 山岸愛梨     | 山岸愛梨     | しない   |

        ※ 今回が確定キャスターで、前回と違う場合のみ通知

    Args:
        previous: 前回の番組データ
        current: 今回の番組データ
        target_date: 対象日
        target_date_str: 表示用日付文字列

    Returns:
        変更があればツイート本文、なければNone

    Examples:
        >>> tweet = build_change_tweet(prev, curr, target, '2025年01月15日')
        >>> if tweet:
        ...     print("変更あり！")
        ...     post_to_twitter(tweet)
    """
    prev_map = {p['time']: p['caster'] for p in previous}
    detect_time = now_jst().strftime('%H:%M')

    lines = []
    changes_count = 0

    # これから放送する枠のみ対象
    upcoming = filter_upcoming_programs(current, target_date)

    for program in upcoming:
        time_str = program['time']
        curr_caster = program['caster']
        prev_caster = prev_map.get(time_str)

        # 通知判定
        # 今回: データ取得失敗 or 未定 → 通知しない
        if curr_caster is None or curr_caster == '未定':
            is_notify = False
        # 前回と同じ → 通知しない
        elif prev_caster == curr_caster:
            is_notify = False
        # 今回確定で前回と違う → 通知する
        else:
            is_notify = True

        if is_notify:
            lines.append(f"{time_str}- {curr_caster} ({prev_caster}から変更:{detect_time})")
            changes_count += 1
            log(f"変更検出: {time_str} {prev_caster} → {curr_caster}")
        else:
            lines.append(f"{time_str}- {curr_caster}")

    if changes_count == 0:
        return None

    header = f"📢 【番組表変更のお知らせ】\n\n📺 {target_date_str} WNL番組表(更新)\n\n"
    footer = "\n\n#ウェザーニュース #番組表"
    return header + "\n".join(lines) + footer


# =============================================================================
# 7. Twitter投稿
# =============================================================================
def post_to_twitter(tweet_text: str) -> bool:
    """
    Twitterにツイートを投稿する。

    環境変数からAPIキーを取得して認証する。

    Args:
        tweet_text: 投稿する本文

    Returns:
        投稿成功ならTrue

    Examples:
        >>> if post_to_twitter("テスト投稿"):
        ...     print("投稿成功！")

    Environment Variables:
        TWITTER_API_KEY, TWITTER_API_SECRET,
        TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET
    """
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
            tweet_id = response.data['id']
            log(f"ツイート成功: https://twitter.com/i/web/status/{tweet_id}")
            return True

    except Exception as e:
        log(f"ツイートエラー: {e}")
        if hasattr(e, 'response') and e.response is not None:
            log(f"詳細: {e.response.text}")

    return False


def is_dry_run() -> bool:
    """
    動作確認モードかどうかを判定する。

    動作確認モードでは全処理を実行するが、
    実際のツイート投稿だけをスキップする。

    Returns:
        動作確認モードならTrue

    Examples:
        >>> if is_dry_run():
        ...     print("動作確認モード: ツイートをスキップ")

    Environment Variables:
        SKIP_TWEET_FLAG: 'true' で動作確認モード
    """
    return os.getenv('SKIP_TWEET_FLAG') == 'true'


# =============================================================================
# 8. データ永続化
# =============================================================================
def save_data(programs: list[dict], target_date_str: str, source: str) -> None:
    """
    番組データをファイルに保存する。

    Args:
        programs: 番組データのリスト
        target_date_str: 対象日の表示文字列
        source: データソース ('json_api' or 'fallback')

    Examples:
        >>> save_data(programs, '2025年01月15日', 'json_api')
    """
    data = {
        'programs': programs,
        'target_date_str': target_date_str,
        'source': source,
        'timestamp': now_jst().isoformat()
    }

    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log("データを保存")
    except Exception as e:
        log(f"データ保存エラー: {e}")


def load_saved_data() -> Optional[dict]:
    """
    保存済みの番組データを読み込む。

    Returns:
        保存済みデータ。ファイルがない場合はNone。

    Examples:
        >>> saved = load_saved_data()
        >>> if saved:
        ...     print(f"前回の対象日: {saved['target_date_str']}")
    """
    if not os.path.exists(DATA_FILE):
        return None

    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            log("保存済みデータを読み込み")
            return data
    except Exception as e:
        log(f"データ読み込みエラー: {e}")
        return None


# =============================================================================
# 9. ユーティリティ
# =============================================================================
def log(message: str) -> None:
    """
    タイムスタンプ付きでログを出力する。

    Args:
        message: 出力するメッセージ

    Examples:
        >>> log("処理を開始します")
        [14:30:45] 処理を開始します
    """
    now = datetime.now(JST)
    print(f"[{now.strftime('%H:%M:%S')}] {message}", file=sys.stderr)


def now_jst() -> datetime:
    """
    現在の日本時間を取得する。

    Returns:
        日本時間のdatetimeオブジェクト

    Examples:
        >>> current = now_jst()
        >>> print(current.strftime('%Y-%m-%d %H:%M'))
        2025-01-15 14:30
    """
    return datetime.now(JST)


# =============================================================================
# エントリーポイント
# =============================================================================
if __name__ == "__main__":
    asyncio.run(main())
