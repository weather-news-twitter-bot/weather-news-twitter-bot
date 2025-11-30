#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウェザーニュース番組表スクレイピング＆Twitter投稿ボット

機能:
    - ウェザーニュースLiVEの番組表をスクレイピング
    - 担当キャスター情報をTwitterに投稿
    - 番組表の変更を検出して更新通知

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
from datetime import datetime, timezone, timedelta
from typing import Optional

# =============================================================================
# 定数
# =============================================================================
JST = timezone(timedelta(hours=9))
TIMETABLE_URL = "https://weathernews.jp/wnl/timetable.html"
DATA_FILE = 'schedule_data.json'

# キャスターが担当する有効な放送枠（05:00開始が1日の始まり）
VALID_TIME_SLOTS = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']

# スクレイピング設定
MAX_RETRIES = 10
RETRY_DELAY_SEC = 60


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
        2. 番組表をスクレイピング
        3. 対象日のデータを抽出
        4. 有効なキャスターがいればツイート投稿
        5. データを保存

    Returns:
        処理成功ならTrue
    """
    log("=== 投稿モード開始 ===")

    # 1. 対象日を決定
    target_date, target_date_str = get_target_date()

    # 2. スクレイピング
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
    source = 'web_scrape' if has_valid_caster(programs) else 'fallback'

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
        2. 番組表をスクレイピング
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

    # 2. スクレイピング
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
        save_data(programs, target_date_str, 'web_scrape')
        return True

    if post_to_twitter(tweet_text):
        save_data(programs, target_date_str, 'web_scrape')
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
# 2. データ取得（スクレイピング）
# =============================================================================
async def fetch_schedule() -> list[dict]:
    """
    番組表データを取得する（リトライ付き）。

    Playwright → Selenium → フォールバック の順で試行。
    最大MAX_RETRIES回リトライする。

    Returns:
        番組データのリスト（フォールバック含め必ず返る）

    Examples:
        >>> programs = await fetch_schedule()
        >>> for p in programs:
        ...     print(f"{p['time']} - {p['caster']}")
    """
    for attempt in range(1, MAX_RETRIES + 1):
        # Playwright を試行
        programs = await fetch_with_playwright()
        if programs:
            return programs

        # Selenium を試行
        programs = fetch_with_selenium()
        if programs:
            return programs

        # リトライ
        if attempt < MAX_RETRIES:
            log(f"スクレイピング失敗。{RETRY_DELAY_SEC}秒後にリトライ ({attempt}/{MAX_RETRIES})")
            await asyncio.sleep(RETRY_DELAY_SEC)
        else:
            log("全リトライ失敗。フォールバックを使用")

    return create_fallback_schedule()


async def fetch_with_playwright() -> Optional[list[dict]]:
    """
    Playwrightを使用して番組表データを取得する。

    Returns:
        番組データのリスト。失敗時はNone。
        各要素: {'time': '05:00', 'caster': '名前', 'program': '番組名', 'profile_url': 'URL'}

    Examples:
        >>> programs = await fetch_with_playwright()
        >>> if programs:
        ...     for p in programs:
        ...         print(f"{p['time']} - {p['caster']}")
        05:00 - 山岸愛梨
        08:00 - 檜山沙耶
    """
    try:
        from playwright.async_api import async_playwright
        log("Playwright でスクレイピング開始...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage',
                      '--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()

            await page.goto(TIMETABLE_URL, wait_until="domcontentloaded", timeout=120000)

            # キャスター情報の読み込み待機
            try:
                await page.wait_for_selector('a[href*="caster"]', timeout=30000)
                log("キャスター情報の出現を確認")
                await page.wait_for_timeout(5000)
            except Exception:
                log("キャスター情報が30秒以内に出現せず。抽出を続行")

            # データ抽出
            programs = await page.evaluate(f'''() => {{
                const result = [];
                const validSlots = {VALID_TIME_SLOTS};

                document.querySelectorAll('.boxStyle__item').forEach(item => {{
                    try {{
                        const timeText = item.querySelector('p')?.textContent?.trim() || '';
                        const timeMatch = timeText.match(/(\\d{{2}}:\\d{{2}})-/);
                        if (!timeMatch) return;

                        const timeStr = timeMatch[1];
                        if (!validSlots.includes(timeStr)) return;

                        const programEl = item.querySelector('p.bold');
                        const programName = programEl?.textContent?.trim() || 'ウェザーニュースLiVE';

                        const casterLink = item.querySelector('a[href*="caster"]');
                        const casterName = casterLink?.textContent?.trim() || '未定';
                        const casterUrl = casterLink?.href || '';

                        result.push({{
                            time: timeStr,
                            caster: casterName,
                            program: programName,
                            profile_url: casterUrl
                        }});
                    }} catch (e) {{}}
                }});
                return result;
            }}''')

            await browser.close()

            if programs and len(programs) > 0:
                log(f"Playwright: {len(programs)}枠を取得")
                return programs

            log("Playwright: データ取得なし")
            return None

    except Exception as e:
        log(f"Playwright エラー: {e}")
        return None


def fetch_with_selenium() -> Optional[list[dict]]:
    """
    Seleniumを使用して番組表データを取得する（Playwrightのフォールバック）。

    Returns:
        番組データのリスト。失敗時はNone。

    Examples:
        >>> programs = fetch_with_selenium()
        >>> if programs:
        ...     print(f"{len(programs)}枠を取得しました")
    """
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        log("Selenium でスクレイピング開始...")

        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")

        driver = uc.Chrome(options=options, headless=True)
        driver.set_page_load_timeout(120)
        driver.implicitly_wait(15)
        driver.get(TIMETABLE_URL)

        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CLASS_NAME, "boxStyle__item"))
        )
        time.sleep(15)

        programs = []
        for item in driver.find_elements(By.CLASS_NAME, "boxStyle__item"):
            try:
                time_elements = item.find_elements(By.TAG_NAME, "p")
                if not time_elements:
                    continue

                time_text = time_elements[0].text.strip()
                time_match = re.search(r'(\d{2}:\d{2})-', time_text)
                if not time_match:
                    continue

                time_str = time_match.group(1)
                if time_str not in VALID_TIME_SLOTS:
                    continue

                program_elements = item.find_elements(By.CSS_SELECTOR, "p.bold")
                program_name = program_elements[0].text.strip() if program_elements else "ウェザーニュースLiVE"

                caster_links = item.find_elements(By.CSS_SELECTOR, "a[href*='caster']")
                caster_name = caster_links[0].text.strip() if caster_links else '未定'
                caster_url = caster_links[0].get_attribute('href') if caster_links else ''

                programs.append({
                    'time': time_str,
                    'caster': caster_name,
                    'program': program_name,
                    'profile_url': caster_url
                })
            except Exception:
                continue

        driver.quit()

        if programs:
            log(f"Selenium: {len(programs)}枠を取得")
            return programs

        log("Selenium: データ取得なし")
        return None

    except Exception as e:
        log(f"Selenium エラー: {e}")
        return None


def create_fallback_schedule() -> list[dict]:
    """
    スクレイピング失敗時のフォールバック用スケジュールを生成する。

    全枠「未定」のデータを返す。これにより has_valid_caster() が
    Falseを返し、ツイートはスキップされる。

    Returns:
        全枠「未定」の番組データリスト

    Examples:
        >>> fallback = create_fallback_schedule()
        >>> print(fallback[0])
        {'time': '05:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・モーニング'}
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
        {'time': t, 'caster': '未定', 'program': program_names[t]}
        for t in VALID_TIME_SLOTS
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
        all_programs: サイトから取得した全番組データ（時系列順）
        target_date: 抽出したい日付

    Returns:
        対象日の番組データリスト（最大6枠）

    Examples:
        >>> # 18時以降に実行（サイトには今日の残り + 明日の全枠が表示）
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
    else:
        selected = day1_programs if day1_programs else day2_programs
        log(f"今日が対象 → {'Day1' if day1_programs else 'Day2(補完)'}を選択")

    # 枠数を6に制限（超過分は破棄）
    if len(selected) > len(VALID_TIME_SLOTS):
        log(f"枠数超過({len(selected)}枠)。{len(VALID_TIME_SLOTS)}枠に制限")
        selected = selected[:len(VALID_TIME_SLOTS)]

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
        source: データソース ('web_scrape' or 'fallback')

    Examples:
        >>> save_data(programs, '2025年01月15日', 'web_scrape')
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
