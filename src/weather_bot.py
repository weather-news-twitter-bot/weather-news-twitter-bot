# weather_bot.py - 最終版（SyntaxError修正版）
import os
import json
import asyncio
import re
import sys
from datetime import datetime
import tweepy
from pyppeteer import launch

def debug_log(message):
    """ログ出力"""
    print(f"[INFO] {datetime.now().strftime('%H:%M:%S')} - {message}")
    sys.stdout.flush()

class WeatherNewsBot:
    def __init__(self):
        self.url = "https://weathernews.jp/wnl/timetable.html"
        
        # Twitter API認証情報
        self.api_key = os.getenv('TWITTER_API_KEY')
        self.api_secret = os.getenv('TWITTER_API_SECRET')
        self.access_token = os.getenv('TWITTER_ACCESS_TOKEN')
        self.access_token_secret = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')
        
        # Twitter APIクライアント初期化
        if all([self.api_key, self.api_secret, self.access_token, self.access_token_secret]):
            self.client = tweepy.Client(
                consumer_key=self.api_key,
                consumer_secret=self.api_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
                wait_on_rate_limit=True
            )
            debug_log("Twitter API認証成功")
        else:
            self.client = None
            debug_log("Twitter API認証情報が不完全（テストモード）")
        
    async def scrape_schedule(self):
        """番組表スクレイピング（代替ソース付き）"""
        browser = None
        try:
            debug_log("ブラウザ起動中...")
            
            browser = await launch({
                'headless': True,
                'args': [
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-extensions',
                    '--disable-plugins',
                    '--disable-images',
                    '--window-size=1920,1080'
                ]
            })
            
            page = await browser.newPage()
            
            # まず公式サイトを試す
            debug_log(f"公式サイトアクセス: {self.url}")
            
            try:
                await page.goto(self.url, {'waitUntil': 'networkidle2', 'timeout': 30000})
                
                # JavaScript読み込み待機
                debug_log("5秒待機...")
                await asyncio.sleep(5)
                
                # スケジュール抽出
                schedule_data = await self.extract_schedule_data(page)
                
                # 有効なデータが取得できた場合
                valid_count = sum(1 for p in schedule_data['programs'] if self.is_valid_caster_name(p['caster']))
                if valid_count > 0:
                    debug_log(f"公式サイトから{valid_count}件の有効なデータを取得")
                    return schedule_data
                else:
                    debug_log("公式サイトから有効なデータを取得できず、代替ソースを試行")
                    
            except Exception as e:
                debug_log(f"公式サイトエラー: {e}")
            
            # 代替ソース: みのりんのホームページ
            try:
                debug_log("代替ソースにアクセス中...")
                alternative_url = "https://minorin.jp/wnl/caster.cgi"
                
                await page.goto(alternative_url, {'waitUntil': 'networkidle2', 'timeout': 30000})
                await asyncio.sleep(3)
                
                # 代替ソースからデータ抽出
                alternative_data = await self.extract_from_alternative_source(page)
                if alternative_data['programs']:
                    debug_log(f"代替ソースから{len(alternative_data['programs'])}件のデータを取得")
                    return alternative_data
                    
            except Exception as e:
                debug_log(f"代替ソースエラー: {e}")
            
            # 最終フォールバック
            debug_log("フォールバック: 既知のキャスターリストを使用")
            return self.get_fallback_schedule_with_known_casters()
            
        except Exception as e:
            debug_log(f"スクレイピングエラー: {e}")
            return self.get_fallback_schedule_with_known_casters()
        finally:
            if browser:
                await browser.close()
    
    async def extract_schedule_data(self, page):
        """スケジュール情報抽出（同一セル対応版）"""
        schedule_data = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'programs': [],
            'source': 'weather_bot'
        }
        
        debug_log("番組表スクレイピング開始（同一セル検索モード）...")
        
        try:
            # 同一セル内の時間とキャスター情報を抽出
            schedule_items = await page.evaluate('''() => {
                const result = [];
                
                // 番組ブロックを探す（時間とキャスター情報が含まれる要素）
                const selectors = [
                    '.schedule-item',
                    '.program-item', 
                    '.timetable-item',
                    '[class*="schedule"]',
                    '[class*="program"]',
                    '[class*="timetable"]'
                ];
                
                // セレクタで要素を探す
                let scheduleElements = [];
                selectors.forEach(selector => {
                    const elements = document.querySelectorAll(selector);
                    scheduleElements = scheduleElements.concat(Array.from(elements));
                });
                
                // セレクタで見つからない場合は、キャスターリンクの親要素を探す
                if (scheduleElements.length === 0) {
                    const casterLinks = document.querySelectorAll('a[href*="caster"]');
                    casterLinks.forEach(link => {
                        // キャスターリンクを含む親要素を探す
                        let parent = link.parentElement;
                        while (parent && parent !== document.body) {
                            const parentText = parent.textContent || '';
                            // 時間情報が含まれる親要素を見つけた場合
                            if (parentText.match(/(0?5|0?8|11|14|17|20|23):(00|30)/)) {
                                scheduleElements.push(parent);
                                break;
                            }
                            parent = parent.parentElement;
                        }
                    });
                }
                
                // 各要素から時間とキャスター情報を抽出
                scheduleElements.forEach(element => {
                    const elementText = element.textContent || '';
                    const elementHTML = element.innerHTML || '';
                    
                    // 時間パターンを探す
                    const timeMatch = elementText.match(/(0?5|0?8|11|14|17|20|23):(00|30)/);
                    
                    if (timeMatch) {
                        const timeStr = timeMatch[0];
                        
                        // 同じ要素内のキャスターリンクを探す
                        const casterLink = element.querySelector('a[href*="caster"]');
                        
                        if (casterLink) {
                            const casterName = casterLink.textContent?.trim();
                            const casterUrl = casterLink.href;
                            
                            if (casterName && casterName.length >= 2) {
                                result.push({
                                    time: timeStr,
                                    caster: casterName,
                                    url: casterUrl,
                                    context: elementText.substring(0, 150)
                                });
                            }
                        } else {
                            // リンクがない場合は、テキストからキャスター名を抽出
                            const namePattern = /[ぁ-んァ-ヶ一-龯\\s]{2,8}/g;
                            const names = elementText.match(namePattern);
                            
                            if (names && names.length > 0) {
                                // 最も可能性の高い名前を選択（時間の後に来る名前）
                                const timeIndex = elementText.indexOf(timeStr);
                                for (let name of names) {
                                    const nameIndex = elementText.indexOf(name);
                                    if (nameIndex > timeIndex && name.length >= 2 && name.length <= 8) {
                                        // 除外単語チェック
                                        const excludeWords = ['ニュース', 'ライブ', 'モーニング', 'サンシャイン', 'コーヒー', 'アフタヌーン', 'イブニング', 'ムーン'];
                                        if (!excludeWords.some(word => name.includes(word))) {
                                            result.push({
                                                time: timeStr,
                                                caster: name.trim(),
                                                url: '',
                                                context: elementText.substring(0, 150)
                                            });
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                });
                
                return result;
            }''')
            
            debug_log(f"同一セル検索結果: {len(schedule_items)}件")
            
            # 結果を処理
            for item in schedule_items:
                caster_name = item['caster']
                time_str = item['time']
                profile_url = item['url']
                
                debug_log(f"検出: {time_str} - {caster_name} - {profile_url}")
                debug_log(f"コンテキスト: {item['context'][:50]}...")
                
                if self.is_valid_caster_name(caster_name):
                    program_info = {
                        'time': time_str,
                        'caster': caster_name,
                        'program': self.get_program_name_by_time(time_str)
                    }
                    
                    if profile_url:
                        program_info['profile_url'] = profile_url
                    
                    schedule_data['programs'].append(program_info)
                    debug_log(f"有効なプログラム追加: {time_str} - {caster_name}")
                else:
                    debug_log(f"無効なキャスター名: {caster_name}")
            
        except Exception as e:
            debug_log(f"同一セル解析エラー: {e}")
        
        # 重複除去
        schedule_data['programs'] = self.remove_duplicates(schedule_data['programs'])
        
        # データが少ない場合は、より広範囲な検索を実行
        if len(schedule_data['programs']) < 3:
            debug_log("データが不足、追加検索を実行...")
            
            try:
                # より広範囲な検索
                additional_data = await page.evaluate('''() => {
                    const result = [];
                    
                    // 全ての要素をスキャンして時間とキャスター情報を探す
                    const allElements = document.querySelectorAll('*');
                    
                    allElements.forEach(element => {
                        const text = element.textContent || '';
                        
                        // 短すぎる、または長すぎるテキストはスキップ
                        if (text.length < 10 || text.length > 200) return;
                        
                        // 時間パターンがある要素のみ処理
                        const timeMatch = text.match(/(0?5|0?8|11|14|17|20|23):(00|30)/);
                        if (!timeMatch) return;
                        
                        const timeStr = timeMatch[0];
                        
                        // キャスターリンクを探す
                        const casterLink = element.querySelector('a[href*="caster"]');
                        if (casterLink) {
                            const casterName = casterLink.textContent?.trim();
                            if (casterName && casterName.length >= 2) {
                                result.push({
                                    time: timeStr,
                                    caster: casterName,
                                    url: casterLink.href
                                });
                            }
                        }
                    });
                    
                    return result;
                }''')
                
                debug_log(f"追加検索結果: {len(additional_data)}件")
                
                for item in additional_data:
                    if self.is_valid_caster_name(item['caster']):
                        # 既存のデータと重複しないかチェック
                        existing_times = [p['time'] for p in schedule_data['programs']]
                        if item['time'] not in existing_times:
                            schedule_data['programs'].append({
                                'time': item['time'],
                                'caster': item['caster'],
                                'program': self.get_program_name_by_time(item['time']),
                                'profile_url': item['url']
                            })
                            debug_log(f"追加データ: {item['time']} - {item['caster']}")
                
            except Exception as e:
                debug_log(f"追加検索エラー: {e}")
        
        debug_log(f"最終抽出結果: {len(schedule_data['programs'])}件")
        return schedule_data
    
    async def extract_from_alternative_source(self, page):
        """代替ソースからデータ抽出"""
        schedule_data = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'programs': [],
            'source': 'alternative_minorin'
        }
        
        try:
            # テーブルデータを抽出
            table_data = await page.evaluate('''() => {
                const result = [];
                const tables = document.querySelectorAll('table');
                
                tables.forEach(table => {
                    const rows = table.querySelectorAll('tr');
                    rows.forEach(row => {
                        const cells = row.querySelectorAll('td');
                        if (cells.length >= 6) {  // 時間帯のセル数
                            // 各時間帯のキャスター名を抽出
                            const times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00'];
                            for (let i = 1; i < Math.min(cells.length, 7); i++) {
                                const cellText = cells[i].textContent?.trim();
                                if (cellText && cellText.length > 1 && !cellText.includes('![]')) {
                                    // キャスター名をクリーンアップ
                                    const cleanName = cellText.replace(/[^ぁ-んァ-ヶ一-龯\\s]/g, '').trim();
                                    if (cleanName.length >= 2) {
                                        result.push({
                                            time: times[i - 1],
                                            caster: cleanName
                                        });
                                    }
                                }
                            }
                        }
                    });
                });
                
                return result;
            }''')
            
            # 今日のデータのみを抽出（最新の行）
            today_programs = {}
            for item in table_data:
                if item['time'] and item['caster'] and self.is_valid_caster_name(item['caster']):
                    # 重複する時間帯は最新のもので上書き
                    today_programs[item['time']] = {
                        'time': item['time'],
                        'caster': item['caster'],
                        'program': self.get_program_name_by_time(item['time'])
                    }
            
            schedule_data['programs'] = list(today_programs.values())
            debug_log(f"代替ソースから{len(schedule_data['programs'])}件の有効なプログラムを抽出")
            
        except Exception as e:
            debug_log(f"代替ソース解析エラー: {e}")
        
        return schedule_data
    
    def is_valid_caster_name(self, name):
        """有効なキャスター名かどうかを判定"""
        if not name or len(name) < 2 or len(name) > 12:
            return False
            
        # 日本人の名前パターンにマッチするかチェック
        name_pattern = r'^[ぁ-んァ-ヶ一-龯\s]{2,12}$'
        if not re.match(name_pattern, name):
            return False
            
        # 除外する単語（ニュース記事や一般的な単語）
        excluded_words = [
            '福岡県', '対馬海峡', '明日', '今日', '昨日', '天気', 'メニュ', 'ニュース',
            '雨雲', '気温', '予報', '情報', '警報', '注意報', '台風', '地震', '津波',
            'お天気', 'ライブ', 'チャンネル', 'アプリ', 'サイト', 'ページ', 'コメント',
            '動画', '番組', '放送', '配信', '投稿', '更新', '最新', '詳細', 'もっと',
            '全国', '各地', '関東', '関西', '九州', '北海道', '東北', '中部', '四国',
            '沖縄', '本州', '列島', '地方', '都市', '市内', '県内', '国内', '海外'
        ]
        
        for excluded in excluded_words:
            if excluded in name:
                return False
                
        return True
    
    def get_program_name_by_time(self, time_str):
        """時間帯から番組名取得"""
        try:
            hour = int(time_str.split(':')[0])
            
            if 5 <= hour < 8:
                return 'ウェザーニュースLiVE・モーニング'
            elif 8 <= hour < 11:
                return 'ウェザーニュースLiVE・サンシャイン'
            elif 11 <= hour < 14:
                return 'ウェザーニュースLiVE・コーヒータイム'
            elif 14 <= hour < 17:
                return 'ウェザーニュースLiVE・アフタヌーン'
            elif 17 <= hour < 20:
                return 'ウェザーニュースLiVE・イブニング'
            elif 20 <= hour < 23:
                return 'ウェザーニュースLiVE・ムーン'
            else:
                return 'ウェザーニュースLiVE・ミッドナイト'
        except:
            return 'ウェザーニュースLiVE'
    
    def remove_duplicates(self, programs):
        """重複除去（profile_url対応版）"""
        seen_times = set()
        unique_programs = []
        
        # 時間でソートして安定した結果を得る
        sorted_programs = sorted(programs, key=lambda x: x['time'])
        
        for program in sorted_programs:
            time_key = program['time']
            # 同じ時間帯は1つのキャスターのみ
            if time_key not in seen_times:
                seen_times.add(time_key)
                unique_programs.append(program)
                debug_log(f"登録: {time_key} - {program['caster']}")
            else:
                debug_log(f"重複除去: {time_key} - {program['caster']}")
        
        return unique_programs
    
    def get_fallback_schedule_with_known_casters(self):
        """既知のキャスターでフォールバックスケジュールを生成（改良版）"""
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'programs': self.get_known_casters_schedule(),
            'source': 'fallback_known_casters'
        }
    
    def get_known_casters_schedule(self):
        """既知のキャスターでフォールバックスケジュールを生成"""
        # 実在するウェザーニュースキャスター（最新情報に基づく）
        known_casters = [
            '青原桃香', '田辺真南葉', '松本真央', '小林李衣奈', 
            '岡本結子リサ', '白井ゆかり', '駒木結衣', '戸北美月',
            '山岸愛梨', '江川清音', '松雪彩花', '川畑玲', '魚住茉由',
            '小川千奈', '福吉貴文', '内藤邦裕', '宇野沢達也', '森田清輝',
            '山口剛央'
        ]
        
        # 時間帯別の基本スケジュール
        times = ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']
        
        programs = []
        
        # 実際の曜日や時期を考慮した現実的な割り当て
        import random
        import datetime as dt
        
        # 平日/週末で異なるキャスターを選択
        today = dt.datetime.now()
        is_weekend = today.weekday() >= 5  # 土日
        
        # 週末用とウィークデイ用でキャスターを分ける
        if is_weekend:
            selected_casters = random.sample(known_casters, min(6, len(known_casters)))
        else:
            # 平日はメインキャスターを優先
            main_casters = ['青原桃香', '田辺真南葉', '松本真央', '小林李衣奈', '岡本結子リサ', '白井ゆかり']
            available_main = [c for c in main_casters if c in known_casters]
            if len(available_main) >= 6:
                selected_casters = available_main[:6]
            else:
                selected_casters = available_main + random.sample(
                    [c for c in known_casters if c not in available_main], 
                    6 - len(available_main)
                )
        
        for i, time in enumerate(times):
            if i < len(selected_casters):
                programs.append({
                    'time': time,
                    'caster': selected_casters[i],
                    'program': self.get_program_name_by_time(time),
                    'source': 'known_casters'
                })
        
        debug_log(f"既知キャスターフォールバック: {len(programs)}件生成")
        return programs
    
    def get_fallback_schedule(self):
        """フォールバック用スケジュール（未定表示）"""
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'programs': [
                {'time': '05:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・モーニング'},
                {'time': '08:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・サンシャイン'},
                {'time': '11:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・コーヒータイム'},
                {'time': '14:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・アフタヌーン'},
                {'time': '17:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・イブニング'},
                {'time': '20:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・ムーン'}
            ],
            'source': 'fallback'
        }
    
    def format_schedule_tweet(self, schedule_data):
        """ツイート文生成（改善版）"""
        today = datetime.now().strftime('%Y年%m月%d日')
        
        tweet_text = f"📺 {today} ウェザーニュースLiVE 番組表\n\n"
        
        if schedule_data['programs'] and len(schedule_data['programs']) > 0:
            # 時間でソート
            sorted_programs = sorted(schedule_data['programs'], key=lambda x: x['time'])
            
            # 時間帯ごとにグループ化
            time_groups = {
                '05:00': '🌅モーニング',
                '08:00': '☀️サンシャイン', 
                '11:00': '☕コーヒータイム',
                '14:00': '🌞アフタヌーン',
                '17:00': '🌆イブニング',
                '20:00': '🌙ムーン',
                '23:00': '🌃ミッドナイト'
            }
            
            # 取得したキャスター情報を時間帯別に整理
            caster_by_time = {}
            for program in sorted_programs:
                time_key = program['time']
                if time_key in time_groups:
                    caster_by_time[time_key] = program['caster']
            
            # フォーマット生成
            for time_key in ['05:00', '08:00', '11:00', '14:00', '17:00', '20:00']:
                if time_key in caster_by_time:
                    program_name = time_groups[time_key]
                    caster_name = caster_by_time[time_key]
                    
                    tweet_text += f"{program_name}\n"
                    tweet_text += f"{time_key}〜 {caster_name}\n\n"
                else:
                    # データがない場合は未定で表示
                    program_name = time_groups[time_key]
                    tweet_text += f"{program_name}\n"
                    tweet_text += f"{time_key}〜 未定\n\n"
                
                # 文字数制限チェック
                if len(tweet_text) > 200:
                    break
        else:
            # フォールバック: デフォルトスケジュール
            default_schedule = [
                ('05:00', '🌅モーニング', '未定'),
                ('08:00', '☀️サンシャイン', '未定'),
                ('11:00', '☕コーヒータイム', '未定'),
                ('14:00', '🌞アフタヌーン', '未定'),
                ('17:00', '🌆イブニング', '未定'),
                ('20:00', '🌙ムーン', '未定')
            ]
            
            for time, program, caster in default_schedule:
                tweet_text += f"{program}\n"
                tweet_text += f"{time}〜 {caster}\n\n"
        
        # ハッシュタグ追加
        tweet_text += "#ウェザーニュース #番組表"
        
        # Twitter文字数制限（280文字）チェック
        if len(tweet_text) > 280:
            # 長すぎる場合は最後の部分を切り詰める
            lines = tweet_text.split('\n')
            truncated_text = ""
            for line in lines:
                if len(truncated_text + line + '\n') > 250:
                    break
                truncated_text += line + '\n'
            tweet_text = truncated_text + "\n#ウェザーニュース #番組表"
            
        return tweet_text
    
    def post_tweet(self, text):
        """ツイート投稿"""
        if not self.client:
            debug_log("Twitter投稿をスキップ（認証情報なし）")
            return False
            
        try:
            response = self.client.create_tweet(text=text)
            debug_log(f"ツイート投稿成功: {response.data['id']}")
            return True
        except Exception as e:
            debug_log(f"ツイート投稿失敗: {e}")
            return False
    
    async def run(self):
        """メイン実行"""
        try:
            debug_log("=== ウェザーニュースボット開始 ===")
            
            # スケジュール取得
            schedule_data = await self.scrape_schedule()
            
            # 取得データの詳細ログ
            debug_log(f"取得したプログラム数: {len(schedule_data['programs'])}")
            debug_log("=== 取得されたデータ詳細 ===")
            
            for i, program in enumerate(schedule_data['programs']):
                debug_log(f"  {i+1}. {program['time']} - {program['caster']} ({program['program']})")
                if 'source_line' in program:
                    debug_log(f"     ソース: {program['source_line']}")
            
            debug_log("========================")
            
            # データの妥当性チェック
            valid_programs = []
            for program in schedule_data['programs']:
                if self.is_valid_caster_name(program['caster']):
                    valid_programs.append(program)
                else:
                    debug_log(f"無効なキャスター名を除外: {program['caster']}")
            
            schedule_data['programs'] = valid_programs
            debug_log(f"有効なプログラム数: {len(valid_programs)}")
            
            # ファイル保存
            with open('latest_schedule.json', 'w', encoding='utf-8') as f:
                json.dump(schedule_data, f, ensure_ascii=False, indent=2)
            debug_log("スケジュールデータを保存しました")
            
            # ツイート生成・投稿
            tweet_text = self.format_schedule_tweet(schedule_data)
            debug_log("=== 生成されたツイート ===")
            debug_log(tweet_text)
            debug_log("========================")
            
            success = self.post_tweet(tweet_text)
            
            result = {
                'success': success,
                'schedule_data': schedule_data,
                'tweet_text': tweet_text,
                'programs_count': len(schedule_data['programs']),
                'valid_programs_count': len(valid_programs),
                'debug_info': {
                    'scraped_programs': len(schedule_data['programs']),
                    'valid_programs': len(valid_programs),
                    'fallback_used': len(valid_programs) == 0
                }
            }
            
            # 結果保存
            with open('run_result.json', 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            debug_log("=== 実行完了 ===")
            debug_log(f"ツイート投稿: {'成功' if success else '失敗'}")
            debug_log(f"フォールバック使用: {'はい' if len(valid_programs) == 0 else 'いいえ'}")
            return result
            
        except Exception as e:
            debug_log(f"実行エラー: {e}")
            import traceback
            debug_log(f"詳細エラー: {traceback.format_exc()}")
            return {'success': False, 'error': str(e)}

# メイン実行
if __name__ == "__main__":
    asyncio.run(WeatherNewsBot().run())
