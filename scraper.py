import json
import os
import re
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

DATA_PATH = "data/plates.json"
TW_TZ = timezone(timedelta(hours=8))


def load_existing_data():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"updated_at": "", "announcements": [], "bids": []}


def clean_int(text: str) -> int:
    nums = re.sub(r"[^\d]", "", text or "")
    return int(nums) if nums else 0


def scrape_announcements(page):
    """抓取標牌公告 (https://www.mvdis.gov.tw/m3-emv-plate/bid/announce)"""
    url = "https://www.mvdis.gov.tw/m3-emv-plate/bid/announce"
    page.goto(url, wait_until="networkidle", timeout=60000)

    # 若頁面需點擊「查詢」按鈕才顯示表格，可取消下面註解：
    # query_btn = page.locator("a:has-text('查詢'), input[value='查詢'], button:has-text('查詢')").first
    # if query_btn.is_visible():
    #     query_btn.click()
    #     page.wait_for_load_state("networkidle")

    results = []
    # 監理服務網表格通常在 table tbody tr 內
    rows = page.locator("table tbody tr")
    count = rows.count()

    for i in range(count):
        cols = [c.inner_text().strip() for c in rows.nth(i).locator("td").all()]
        # 依實際欄位數量微調索引 (可按 F12 確認欄位順序)
        if len(cols) >= 5:
            results.append({
                "station": cols[0],
                "vehicle_type": cols[1],
                "plate_range": cols[2],
                "start_time": cols[3],
                "end_time": cols[4],
                "status": cols[5] if len(cols) > 5 else "公告中"
            })
    return results


def scrape_bidding(page):
    """抓取競標中金額與次數 (https://www.mvdis.gov.tw/m3-emv-plate/bid/queryBiding)"""
    url = "https://www.mvdis.gov.tw/m3-emv-plate/bid/queryBiding"
    page.goto(url, wait_until="networkidle", timeout=60000)

    results = []
    rows = page.locator("table tbody tr")
    count = rows.count()

    for i in range(count):
        cols = [c.inner_text().strip() for c in rows.nth(i).locator("td").all()]
        # 依實際欄位順序微調索引：車牌、監理站、車種、金額、次數、截標時間
        if len(cols) >= 5:
            results.append({
                "plate": cols[0],
                "station": cols[1],
                "vehicle_type": cols[2],
                "price": clean_int(cols[3]),
                "bid_count": clean_int(cols[4]),
                "end_time": cols[5] if len(cols) > 5 else "",
                "status": "競標中"
            })
    return results


def merge_bids(old_bids, new_bids):
    """合併歷史與最新出價：同車牌更新為最新金額與次數，沒在最新清單的標記為歷史紀錄"""
    merged = {}
    for item in old_bids:
        item["status"] = "歷史紀錄"
        merged[item["plate"]] = item

    for item in new_bids:
        merged[item["plate"]] = item

    return list(merged.values())


def main():
    existing = load_existing_data()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            announcements = scrape_announcements(page)
        except Exception as e:
            print(f"[警告] 抓取公告失敗，保留舊資料: {e}")
            announcements = existing.get("announcements", [])

        try:
            new_bids = scrape_bidding(page)
            bids = merge_bids(existing.get("bids", []), new_bids) if new_bids else existing.get("bids", [])
        except Exception as e:
            print(f"[警告] 抓取競標行情失敗，保留舊資料: {e}")
            bids = existing.get("bids", [])

        browser.close()

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    output = {
        "updated_at": datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "announcements": announcements if announcements else existing.get("announcements", []),
        "bids": bids
    }

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"更新完成！公告 {len(output['announcements'])} 筆，行情 {len(output['bids'])} 筆。")


if __name__ == "__main__":
    main()