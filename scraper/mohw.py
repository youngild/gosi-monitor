"""
보건복지부 훈령/예규/고시/지침 크롤러
https://www.mohw.go.kr/board.es?mid=a10409020000&bid=0026
"""
import re
import os
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime

BASE_URL = "https://www.mohw.go.kr"
LIST_URL = f"{BASE_URL}/board.es?mid=a10409020000&bid=0026"
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'files', 'mohw')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
}

FROM_DATE = date(2026, 3, 1)


def fetch_list_page(page: int) -> list[dict]:
    """목록 1페이지 크롤링. 2026-03-01 이전 날짜가 나오면 중단 신호 반환."""
    params = {"mid": "a10409020000", "bid": "0026", "act": "list", "nPage": page}
    resp = requests.get(LIST_URL, params=params, headers=HEADERS, verify=False, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'lxml')

    rows = soup.select("table.tstyle_list tbody tr")
    items = []
    stop = False

    for row in rows:
        # 미리보기 행 무시
        if row.get('id', '').startswith('preView'):
            continue

        tds = row.find_all('td')
        if len(tds) < 5:
            continue

        # 등록일 파싱
        date_str = tds[4].get_text(strip=True)  # YYYY-MM-DD
        try:
            posted = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            continue

        if posted < FROM_DATE:
            stop = True
            break

        # 제목 & 상세 링크
        title_td = row.find('td', attrs={'data-label': '제목'})
        if not title_td:
            continue
        a_tag = title_td.find('a')
        title = a_tag.get_text(strip=True)
        detail_url = BASE_URL + a_tag['href']

        # list_no 추출
        m = re.search(r'list_no=(\d+)', a_tag['href'])
        notice_id = m.group(1) if m else ''

        # 구분
        category = tds[1].get_text(strip=True) if len(tds) > 1 else ''
        # 발령번호
        issued_no = tds[2].get_text(strip=True) if len(tds) > 2 else ''

        items.append({
            'source': 'mohw',
            'notice_id': notice_id,
            'category': category,
            'title': title,
            'issued_no': issued_no,
            'posted_date': date_str,
            'detail_url': detail_url,
        })

    return items, stop


def fetch_attachments(notice_id: str) -> list[dict]:
    """상세 페이지에서 첨부파일 목록 반환."""
    url = f"{BASE_URL}/board.es?mid=a10409020000&bid=0026&act=view&list_no={notice_id}"
    resp = requests.get(url, headers=HEADERS, verify=False, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'lxml')

    attachments = []
    for li in soup.select("div.file ul.list li"):
        a_download = li.find('a', href=re.compile(r'/boardDownload\.es'))
        if not a_download:
            continue
        filename = a_download.get('title', '').strip()
        if not filename:
            # alt 텍스트에서 확장자만 있을 경우 img alt 사용
            img = li.find('img')
            filename = li.get_text(separator=' ').strip().split()[0] if img else ''
        download_url = BASE_URL + a_download['href']
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        attachments.append({
            'filename': filename,
            'file_type': ext,
            'download_url': download_url,
        })
    return attachments


def download_file(download_url: str, filename: str) -> str | None:
    """파일 다운로드 후 로컬 경로 반환."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    # 파일명 안전처리
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', filename)
    local_path = os.path.join(DOWNLOAD_DIR, safe_name)
    if os.path.exists(local_path):
        return local_path
    try:
        resp = requests.get(download_url, headers=HEADERS, verify=False, timeout=30, stream=True)
        resp.raise_for_status()
        with open(local_path, 'wb') as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return local_path
    except Exception as e:
        print(f"[MOHW] 다운로드 실패: {filename} - {e}")
        return None


def crawl(max_pages: int = 10) -> list[dict]:
    """2026-03-01 이후 게시물 전체 수집."""
    all_items = []
    for page in range(1, max_pages + 1):
        print(f"[MOHW] 페이지 {page} 크롤링 중...")
        try:
            items, stop = fetch_list_page(page)
        except Exception as e:
            print(f"[MOHW] 페이지 {page} 오류: {e}")
            break
        all_items.extend(items)
        if stop:
            print(f"[MOHW] 2026-03-01 이전 날짜 감지 - 수집 중단")
            break
    print(f"[MOHW] 총 {len(all_items)}건 수집")
    return all_items
