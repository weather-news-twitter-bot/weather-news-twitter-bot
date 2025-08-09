# selenium_weathernews_bot.py
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import json
import re
from datetime import datetime

class SeleniumWeatherNewsBot:
    def __init__(self):
        self.url = "https://weathernews.jp/wnl/timetable.html"
        self.setup_driver()
        
    def setup_driver(self):
        """ヘッドレスChromeドライバーの設定"""
        chrome_options = Options()
        chrome_options.add_argument('--headless')  # ヘッドレスモード
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        
        # GitHub Actions用の設定
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-plugins')
        chrome_options.add_argument('--disable-images')  # 高速化
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 20)
        
    def scrape_schedule(self):
        """Seleniumを使用してスケジュール情報を取得"""
        try:
            print("📱 ページにアクセス中...")
            self.driver.get(self.url)
            
            # JavaScriptの実行完了まで待機
            print("⏳ JavaScript読み込み待機中...")
            time.sleep(5)
            
            # データが読み込まれるまで待機（キャスター名が表示されるまで）
            try:
                # テンプレート記法が実際のデータに置き換わるまで待機
                self.wait.until(
                    lambda driver: not any("{{" in elem.text for elem in driver.find_elements(By.XPATH, "//*[contains(text(), 'caster')]"))
                )
                print("✅ データ読み込み完了")
            except:
                print("⚠️ データ読み込み待機タイムアウト - 現在の状態で解析を試行")
            
            # 様々なセレクタでスケジュール情報を探索
            schedule_data = self.extract_schedule_data()
            
            return schedule_data
            
        except Exception as e:
            print(f"❌ Seleniumスクレイピングエラー: {e}")
            return self.get_fallback_schedule()
        finally:
            self.driver.quit()
    
    def extract_schedule_data(self):
        """ページからスケジュール情報を抽出"""
        schedule_data = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'programs': [],
            'source': 'selenium'
        }
        
        # 複数のセレクタパターンを試行
        selectors = [
            ".timetable-item",
            ".schedule-item", 
            ".program-item",
            ".caster-schedule",
            "[data-time]",
            ".time-slot",
            "tr td",
            "li[class*='time']"
        ]
        
        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    print(f"🔍 要素発見: {selector} ({len(elements)}個)")
                    programs = self.parse_elements(elements)
                    if programs:
                        schedule_data['programs'].extend(programs)
                        break
            except Exception as e:
                print(f"⚠️ セレクタ {selector} でエラー: {e}")
                continue
        
        # フォールバック: ページ全体のテキストから時間とキャスター名を抽出
        if not schedule_data['programs']:
            print("🔄 フォールバック: ページ全体から情報を抽出")
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            schedule_data['programs'] = self.extract_from_text(page_text)
        
        # 重複除去
        schedule_data['programs'] = self.remove_duplicates(schedule_data['programs'])
        
        print(f"📊 取得した番組数: {len(schedule_data['programs'])}")
        return schedule_data
    
    def parse_elements(self, elements):
        """要素から番組情報を解析"""
        programs = []
        
        for element in elements:
            try:
                text = element.text.strip()
                if not text or "{{" in text:  # テンプレート記法が残っている場合はスキップ
                    continue
                
                # 時間とキャスター名のパターンマッチング
                time_match = re.search(r'(\d{1,2}):(\d{2})', text)
                name_match = re.search(r'([ぁ-んァ-ヶ一-龯]{2,8})', text)
                
                if time_match and name_match:
                    time_str = time_match.group(0)
                    caster_name = name_match.group(1)
                    
                    programs.append({
                        'time': time_str,
                        'caster': caster_name,
                        'program': self.get_program_name_by_time(time_str)
                    })
                    
            except Exception as e:
                continue
        
        return programs
    
    def extract_from_text(self, page_text):
        """ページ全体のテキストから時間とキャスター情報を抽出"""
        programs = []
        lines = page_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or "{{" in line:
                continue
                
            # "HH:MM キャスター名" のパターンを探す
            pattern = r'(\d{1,2}):(\d{2})\s*([ぁ-んァ-ヶ一-龯]{2,8})'
            matches = re.findall(pattern, line)
            
            for match in matches:
                time_str = f"{match[0]}:{match[1]}"
                caster_name = match[2]
                
                programs.append({
                    'time': time_str,
                    'caster': caster_name,
                    'program': self.get_program_name_by_time(time_str)
                })
        
        return programs
    
    def get_program_name_by_time(self, time_str):
        """時間帯から番組名を取得"""
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
        """重複を除去"""
        seen = set()
        unique_programs = []
        
        for program in programs:
            key = f"{program['time']}-{program['caster']}"
            if key not in seen:
                seen.add(key)
                unique_programs.append(program)
        
        return unique_programs
    
    def get_fallback_schedule(self):
        """フォールバック用固定スケジュール"""
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'programs': [
                {'time': '05:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・モーニング'},
                {'time': '08:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・サンシャイン'},
                {'time': '11:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・コーヒータイム'},
                {'time': '14:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・アフタヌーン'},
                {'time': '17:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・イブニング'},
                {'time': '20:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・ムーン'},
                {'time': '23:00', 'caster': '未定', 'program': 'ウェザーニュースLiVE・ミッドナイト'}
            ],
            'source': 'fallback'
        }

# テスト実行
if __name__ == "__main__":
    bot = SeleniumWeatherNewsBot()
    schedule = bot.scrape_schedule()
    print(json.dumps(schedule, ensure_ascii=False, indent=2))
