# 한양대학교 식단 파서 - 테스트 업데이트
import sys
import requests
import re
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Environment Variables
MENU_URL = os.getenv("MENU_URL", "https://fnb.hanyang.ac.kr/front/fnbmMdMenu")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "menus")
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Price Mapping (Hardcoded based on user request)
CORNER_PRICES = {
    'hanyang_plaza': {
        'western': 4800,
        'korean': 4800,
        'instant': 4800,
        'cupbap': 4800,
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

def fetch_menu_html(date_str=None):
    """
    Fetches menu HTML from the Hanyang University F&B website.
    Optionally accepts a date string (YYYY-MM-DD).
    """
    url = MENU_URL
    params = {}
    if date_str:
        params['date'] = date_str
    
    # User-Agent header to mimic a browser
    headers = {
        'User-Agent': USER_AGENT
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
    date_match = re.search(r'\d{4}-\d{2}-\d{2}', first_day_text)
    if not date_match:
        print("Error: 날짜 패턴을 찾을 수 없습니다.")
        return
        
    base_date = datetime.strptime(date_match.group(), '%Y-%m-%d')
    
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

    # 날짜별 데이터를 담을 딕셔너리
    # Type hint to resolve static analysis confusion
    daily_results: Dict[str, Dict[str, Dict[str, Any]]] = {}

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
            target_date = (base_date + timedelta(days=day_map[day_name])).strftime('%Y-%m-%d') # type: ignore
            
            if target_date not in daily_results:
                daily_results[target_date] = {} # type: ignore
            if res_id not in daily_results[target_date]: # type: ignore
                daily_results[target_date][res_id] = {} # type: ignore

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
                # Try to find a title element (often main menu name for Hanyang Plaza / Breakfast)
                title_elem = item.select_one('.content-item-title')
                title_text = title_elem.get_text(strip=True) if title_elem else ""

                # Modified: Ramen corner logic
                if c_id == 'ramen':
                    # User Request: Ramen corner should have full text in mainMenuName
                    # e.g. "부대라면(공기밥 +500원)" should not be split
                    main_menu = raw_desc.replace(',', ' ').strip()
                    sub_items = []
                else:
                    parts = raw_desc.replace(',', ' ').split()
                    main_menu = parts[0] if parts else "운영없음"
                    sub_items = parts[1:] if len(parts) > 1 else []
                variants = []

                # --- Issue 1: Hanyang Plaza General Logic (Side Dishes) ---
                if res_id == 'hanyang_plaza' and c_id != 'breakfast_1000':
                    # Hanyang Plaza: Main menu is often in .content-item-title
                    # Description contains side dishes.
                    # If title exists, use it as main_menu.
                    if title_text:
                        main_menu = title_text
                        # Description text becomes the items list
                        if raw_desc:
                            sub_items = raw_desc.replace(',', ' ').split()
                        else:
                            sub_items = []
                    else:
                        # Fallback if no title element found (use existing logic)
                        pass

                # --- Issue 2: Breakfast 1000 Variants Logic ---
                if c_id == 'breakfast_1000':
                    main_menu = "천원의 아침밥"
                    sub_items = ["A/B 메뉴 중 선택"]
                    
                    # Combine title and desc to catch all variants (Baekban + Ganpyeon)
                    # Often title has one, desc has the other, or both mixed.
                    # We'll parse the combined text.
                    combined_text = f"{title_text} {raw_desc}"
                    
                    # Remove '★품절' and other noise
                    clean_text = combined_text.replace('★품절', '').strip()
                    
                    # Regex: Matches [Marker] followed by content
                    # e.g., [백반식 130식]... [간편식 70식]...
                    pattern = r'(\[[^\]]+\])([^\[]*)'
                    matches = re.findall(pattern, clean_text)
                    
                    if matches:
                        for marker, content in matches:
                            content_parts = content.strip().replace(',', ' ').split()
                            if content_parts:
                                # Variant Main Menu: Marker + First Item (e.g., [백반식]쌀밥)
                                # Or just Marker if user prefers.
                                # User requested: "[백반식 130식]잡곡밥" as mainMenuName
                                v_main = f"{marker}{content_parts[0]}"
                                v_items = content_parts[1:]
                                variants.append({
                                    "mainMenuName": v_main,
                                    "items": v_items
                                })
                            else:
                                # Case where content is empty -> just marker
                                variants.append({
                                    "mainMenuName": marker,
                                    "items": []
                                })
                    else:
                        # Fallback: No markers found
                        if clean_text:
                            # Try to split by known keywords if regex fails?
                            # For now, just treat as single variant to avoid data loss
                            parts = clean_text.replace(',', ' ').split()
                            variants.append({
                                "mainMenuName": parts[0] if parts else clean_text,
                                "items": parts[1:] if len(parts) > 1 else []
                            })

                # Price Logic
                price = 0
                if c_id == 'breakfast_1000':
                    price = 1000
                elif res_id in CORNER_PRICES and c_id in CORNER_PRICES[res_id]: # type: ignore
                    price = CORNER_PRICES[res_id][c_id] # type: ignore

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

                if variants:
                    menu_data["variants"] = variants

                daily_results[target_date][res_id][c_id] = menu_data

    # --- New Logic: Iterative Daily Enrichment (Weekly + Daily Checks) ---
    # Loop through all dates identified in the Weekly view.
    # Fetch the specific daily page for each date to get detailed info (sides, variants).
    
    print("\n--- Starting Daily Enrichment (Fetching detailed data for each day) ---")
    
    # Sort dates to process in order
    sorted_dates = sorted(daily_results.keys())
    
    for today_date in sorted_dates:
        print(f"[{today_date}] Fetching detailed metadata...")
        daily_html = fetch_menu_html(today_date)
        if not daily_html:
            print(f"[{today_date}] Failed to fetch HTML. Skipping.")
            continue
            
        day_soup = BeautifulSoup(daily_html, 'html.parser')
        
        # 1. Enrich General Corners from #today slider
        today_section = day_soup.select_one('#today')
        if today_section:
            # Verify date matches (just in case)
            date_elem = today_section.select_one('.date')
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                # Ensure we are looking at the right day
                if today_date not in date_text:
                    print(f"[{today_date}] Date mismatch in #today section ({date_text}). Skipping.")
                    continue

            today_slides = today_section.select('.menu-slide-item')
            for slide in today_slides:
                shop_id = slide.get('id', '')
                res_id = restaurant_map.get(shop_id)
                if not res_id: continue
                
                # USER FEEDBACK: Skip Materials and Life Science for daily enrichment.
                # Weekly parsing works fine for them, and daily enrichment breaks the item separation.
                if res_id in ['materials', 'life_science']:
                    continue

                # Ensure dict exists (it should from weekly parsing)
                if res_id not in daily_results[today_date]:
                    daily_results[today_date][res_id] = {}

                menu_items = slide.select('li > .wrapper')
                for item in menu_items:
                    cat = item.select_one('.category').get_text(strip=True)
                    
                    # Life Science Logic
                    if res_id == 'life_science':
                            if "중식" in cat and "Dam-A" in cat: c_id = "dam_a_lunch"
                            elif "중식" in cat and "Pangeos" in cat: c_id = "pangeos_lunch"
                            elif "석식" in cat and "Dam-A" in cat: c_id = "dam_a_dinner"
                            else: c_id = "unknown"
                    else:
                        c_id = corner_map.get(cat, "unknown")
                    
                    if c_id == "unknown": continue

                    title_elem = item.select_one('.title')
                    desc_elem = item.select_one('.desc')
                    
                    daily_title = title_elem.get_text(strip=True) if title_elem else ""
                    daily_desc = desc_elem.get_text(strip=True) if desc_elem else ""
                    if daily_desc == "-": daily_desc = ""

                    # Existing data from weekly
                    existing_data = daily_results[today_date][res_id].get(c_id, {})
                    
                    if c_id == 'ramen':
                         # If Ramen, combine title and desc into Main Menu Name if needed
                         # But often Daily View has Title="Ramen Name", Desc="Option"
                         # We want "Ramen Name(Option)"
                         if daily_desc:
                              # If daily_desc starts with '(', just append. Otherwise, maybe verify format?
                              # For now, append as requested.
                              daily_title = f"{daily_title}{daily_desc}"
                              items_fixed = []
                         else:
                              items_fixed = []
                    else:
                        # Daily view structure: Title = Main, Desc = Items (Sides)
                        items_fixed = daily_desc.replace(',', ' ').split() if daily_desc else []
                    
                    # Update fields
                    existing_data.update({
                        "restaurantId": res_id,
                        "cornerId": c_id,
                        "cornerDisplayName": cat,
                        "mainMenuName": daily_title,
                        "items": items_fixed
                    })
                    
                    # Price fix
                    if "priceWon" not in existing_data or existing_data["priceWon"] == 0:
                        price = 0
                        if res_id in CORNER_PRICES and c_id in CORNER_PRICES[res_id]:
                            price = CORNER_PRICES[res_id][c_id]
                        existing_data["priceWon"] = price

                    daily_results[today_date][res_id][c_id] = existing_data

        # 2. Enrich Breakfast 1000 from #donation section
        # The #donation section ALWAYS shows the data for the 'date' parameter passed in URL
        donation_section = day_soup.select_one('#donation')
        if donation_section:
            res_id = 'hanyang_plaza'
            c_id = 'breakfast_1000'
            
            # Use 'today_date' (outer loop variable) directly
            
            if res_id not in daily_results[today_date]:
                daily_results[today_date][res_id] = {}

            donation_item = donation_section.select_one('.menu-donation')
            if donation_item:
                title_elem = donation_item.select_one('.title')
                desc_elem = donation_item.select_one('.desc')
                
                d_title = title_elem.get_text(strip=True) if title_elem else ""
                d_desc = desc_elem.get_text(strip=True) if desc_elem else ""
                
                combined_text = f"{d_title} {d_desc}"
                
                variants = []
                clean_text = combined_text.replace('★품절', '').strip()
                pattern = r'(\[[^\]]+\])([^\[]*)'
                matches = re.findall(pattern, clean_text)
                
                if matches:
                    for marker, content in matches:
                        content_parts = content.strip().replace(',', ' ').split()
                        if content_parts:
                            v_main = f"{marker}{content_parts[0]}"
                            v_items = content_parts[1:]
                            variants.append({"mainMenuName": v_main, "items": v_items})
                        else:
                            variants.append({"mainMenuName": marker, "items": []})
                
                if variants:
                    existing = daily_results[today_date][res_id].get(c_id, {
                        "restaurantId": res_id, 
                        "cornerId": c_id, 
                        "cornerDisplayName": "천원의 아침밥",
                        "priceWon": 1000,
                        "items": ["A/B 메뉴 중 선택"]
                    })
                    existing["variants"] = variants
                    daily_results[today_date][res_id][c_id] = existing

    print("--- Daily Enrichment Completed ---\n") # type: ignore

    # 4. 파일 저장 (menus/ 디렉토리)
    output_dir = OUTPUT_DIR
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
    # fetch_menu("2024-05-20") # Example usage
    html_data = fetch_menu_html(target_date) # Defaults to current week (default)
    
    if html_data:
        # Debug: Save to file to inspect content (Optional, keeping for safety)
        # with open('debug_menu.html', 'w', encoding='utf-8') as f:
        #     f.write(html_data)
            
        extract_hyeat_data(html_data)
    else:
        print("Failed to retrieve menu data.")