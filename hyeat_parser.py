# 한양대학교 식단 파서 - 테스트 업데이트
import sys
import requests
import re
import json
import os
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

def fetch_menu_html(date_str=None):
    """
    Fetches menu HTML from the Hanyang University F&B website.
    Optionally accepts a date string (YYYY-MM-DD).
    """
    url = "https://fnb.hanyang.ac.kr/front/fnbmMdMenu"
    params = {}
    if date_str:
        params['date'] = date_str
    
    # User-Agent header to mimic a browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        # Website returns UTF-8
        response.encoding = 'utf-8' 
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching menu data: {e}")
        return None

def extract_hyeat_data(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    first_day_element = soup.select_one('.first-day p')
    if not first_day_element:
        print("Error: '.first-day p' 요소를 찾을 수 없습니다.")
        return

    first_day_text = first_day_element.get_text(strip=True)
    base_date = datetime.strptime(re.search(r'\d{4}-\d{2}-\d{2}', first_day_text).group(), '%Y-%m-%d')
    
    # 요일 인덱스 매핑
    day_map = {'월': 0, '화': 1, '수': 2, '목': 3, '금': 4, '토': 5, '일': 6}
    
    # 2. 식당 ID 매핑 (HTML ID -> Contract ID)
    restaurant_map = {
        'shop-rR0K2hvyTkCLCDF129-HgQ': 'hanyang_plaza', # 학생식당
        'shop-mHUPfUZ9QA2TzS4tlZNJQA': 'materials',      # 신소재공학관
        'shop-UdDNmWPQS-m_vkxcSWYnvw': 'life_science'   # 생활과학관
    }

    # 3. 코너 ID 매핑 (Display Name -> Contract cornerId)
    corner_map = {
        '천원의 아침밥': 'breakfast_1000', '한식': 'korean', '양식': 'western', 
        '즉석': 'instant', '오늘의 컵밥': 'cupbap', '오늘의 라면': 'ramen',
        '정식': 'set_meal', '일품': 'single_dish', '석식': 'dinner'
    }

    # Price Mapping (Hardcoded based on user request)
    CORNER_PRICES = {
        'hanyang_plaza': {
            'western': 4200,
            'korean': 4200,
            'instant': 4500,
            'cupbap': 4500,
            'ramen': 3500,
            # breakfast_1000 is handled separately
        },
        'materials': {
            'set_meal': 6000,
            'single_dish': 6500,
            'dinner': 6000,
            'rice_bowl': 4700 # '덮밥' -> rice_bowl mapping assumed if corner_map updated
        },
        'life_science': {
            'pangeos_lunch': 6500,
            'dam_a_lunch': 6000,
            'dam_a_dinner': 6000
        }
    }

    # 날짜별 데이터를 담을 딕셔너리
    daily_results = {}

    # 주간 식단 컨테이너 탐색
    week_containers = soup.select('.shop-week-container')
    
    for container in week_containers:
        html_id = container.get('id', '')
        # 주간 메뉴 ID에서 식당 정보 추출 (shop-week-XXXX -> shop-XXXX)
        shop_id = html_id.replace('shop-week-', 'shop-')
        res_id = restaurant_map.get(shop_id)
        
        if not res_id: continue

        day_containers = container.select('.day-container')
        for day_section in day_containers:
            day_name = day_section.select_one('.day span').get_text(strip=True)
            target_date = (base_date + timedelta(days=day_map[day_name])).strftime('%Y-%m-%d')
            
            if target_date not in daily_results:
                daily_results[target_date] = {}
            if res_id not in daily_results[target_date]:
                daily_results[target_date][res_id] = {}

            # 메뉴 리스트 파싱
            items_list = day_section.select('.content-item')
            
            # 미운영 처리
            if not items_list or "등록된 메뉴가 없습니다" in day_section.get_text():
                continue

            for item in items_list:
                category = item.select_one('.category').get_text(strip=True)
                raw_desc = item.select_one('.content-item-desc p').get_text(strip=True)
                
                # Life Science Specific Logic
                if res_id == 'life_science':
                    if "중식" in category and "Dam-A" in category:
                        c_id = "dam_a_lunch"
                    elif "중식" in category and "Pangeos" in category:
                        c_id = "pangeos_lunch"
                    elif "석식" in category and "Dam-A" in category:
                        c_id = "dam_a_dinner"
                    else:
                        c_id = "unknown"
                else:
                    c_id = corner_map.get(category, "unknown")
                
                if c_id == "unknown": continue

                # 메뉴명 및 상세 아이템 분리 (기본 로직)
                parts = raw_desc.replace(',', ' ').split()
                main_menu = parts[0] if parts else "운영없음"
                sub_items = parts[1:] if len(parts) > 1 else []
                variants = []

                # Breakfast 1000 Variants Logic (Regex based)
                if c_id == 'breakfast_1000':
                    main_menu = "천원의 아침밥"
                    sub_items = ["A/B 메뉴 중 선택"]
                    
                    # Remove '★품절' and other noise
                    clean_desc = raw_desc.replace('★품절', '').strip()
                    
                    # User-requested Regex: Matches [Any Marker] followed by content
                    pattern = r'(\[[^\]]+\])([^\[]*)'
                    matches = re.findall(pattern, clean_desc)
                    
                    if matches:
                        for marker, content in matches:
                            content_parts = content.strip().replace(',', ' ').split()
                            if content_parts:
                                # Construct variant name: Marker + First Item (e.g., [백반식]쌀밥)
                                v_main = f"{marker}{content_parts[0]}"
                                v_items = content_parts[1:]
                                variants.append({
                                    "mainMenuName": v_main,
                                    "items": v_items
                                })
                            else:
                                # Case where content is empty or just spaces after marker
                                variants.append({
                                    "mainMenuName": marker,
                                    "items": []
                                })
                    else:
                        # Fallback: No markers found, treat entire description as one variant
                        # To prevent data loss
                        if clean_desc:
                            parts = clean_desc.replace(',', ' ').split()
                            variants.append({
                                "mainMenuName": parts[0] if parts else clean_desc,
                                "items": parts[1:] if len(parts) > 1 else []
                            })

                # Price Logic
                price = 0
                if c_id == 'breakfast_1000':
                    price = 1000
                elif res_id in CORNER_PRICES and c_id in CORNER_PRICES[res_id]:
                    price = CORNER_PRICES[res_id][c_id]

                menu_data = {
                    "restaurantId": res_id,
                    "cornerId": c_id,
                    "cornerDisplayName": category,
                    "mainMenuName": main_menu,
                    "priceWon": price,
                    "items": sub_items
                }
                
                if variants:
                    menu_data["variants"] = variants

                daily_results[target_date][res_id][c_id] = menu_data

    # 4. 파일 저장 (menus/ 디렉토리)
    output_dir = "menus"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    for date, data in daily_results.items():
        filename = os.path.join(output_dir, f"{date}.json")
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[Saved] {filename}")


# --- 실행부 ---
if __name__ == "__main__":
    # Command line argument for date (optional)
    target_date = None
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
        print(f"Fetching menu for date: {target_date}")
    else:
        print("Fetching menu for current week (default)")

    html_data = fetch_menu_html(target_date)
    
    if html_data:
        # Debug: Save to file to inspect content (Optional, keeping for safety)
        # with open('debug_menu.html', 'w', encoding='utf-8') as f:
        #     f.write(html_data)
            
        extract_hyeat_data(html_data)
    else:
        print("Failed to retrieve menu data.")