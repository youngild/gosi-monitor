# 고시 통합 분석 시스템

## 프로젝트 개요

여러 사이트에 흩어져 있는 각종 고시를 한 곳에서 확인하고 분석하는 시스템.

1. 다양한 정부/기관 사이트에서 발표되는 고시를 하나의 웹 또는 프로그램에서 통합 조회
2. 각 고시의 첨부파일(PDF, Excel 등)에서 내용을 추출하여 AI로 요약 제공

## 기술 스택

- **프론트엔드**: HTML, CSS, JavaScript
- **자동화 스크립트**: PowerShell (Excel COM 오브젝트 활용)
- **향후 추가 예정**: 웹 크롤링, AI 요약 (Claude API)

## 수집 대상 사이트

| 사이트 | URL | 기술 방식 | 비고 |
|---|---|---|---|
| 보건복지부 훈령/예규/고시/지침 | `https://www.mohw.go.kr/board.es?mid=a10409020000&bid=0026` | 표준 HTML | requests+BeautifulSoup |
| 건강보험심사평가원 InfoBank | `https://biz.hira.or.kr/popup.ndo?formname=qya_bizcom%3A%3AInfoBank.xfdl&framename=InfoBank` | Nexacro14 JS 프레임워크 | Playwright 필요 |

**수집 기준**: 2026-03-01 이후 게시물

## 파일 구조

```
cursorproject/
├── main.py               # 실행 진입점 (crawl/summarize/serve)
├── requirements.txt      # Python 패키지 목록
├── scraper/
│   ├── mohw.py           # 보건복지부 크롤러 (requests+BeautifulSoup)
│   └── hira.py           # 심평원 크롤러 (Playwright)
├── analyzer/
│   └── summarizer.py     # Claude API 고시 요약
├── storage/
│   └── database.py       # SQLite DB (notices, attachments)
├── web/
│   ├── app.py            # Flask REST API + 서버
│   └── templates/
│       └── index.html    # 웹 UI (고시 목록/검색/상세)
├── data/                 # 런타임 생성
│   ├── notices.db        # SQLite DB 파일
│   └── files/            # 첨부파일 다운로드
│       ├── mohw/
│       └── hira/
├── index.html            # (기존) Hello World 템플릿
├── read_excel.ps1
├── read_headers.ps1
├── sort_requirements.ps1
└── CLAUDE.md
```

## 실행 방법

```bash
# 패키지 설치
pip install -r requirements.txt
playwright install chromium

# 환경변수 설정 (요약 기능 사용 시)
set ANTHROPIC_API_KEY=sk-ant-...

# 크롤링
python main.py crawl

# 요약 (크롤링 후 PDF 첨부파일 AI 요약)
python main.py summarize

# 전체 실행
python main.py all

# 웹 서버 (http://localhost:5000)
python main.py serve
```

## 데이터 구조

- `notices` 테이블: source, notice_id, category, title, issued_no, posted_date, detail_url, summary
- `attachments` 테이블: notice_id(FK), filename, file_type, download_url, local_path

## 사이트별 기술 특이사항

### 보건복지부 (MOHW)
- 목록: `table.tstyle_list > tbody > tr`
- 제목링크: `td[data-label="제목"] > a` (href에 list_no 포함)
- 첨부파일: `div.file ul.list li > a[href*="boardDownload"]`
- 다운로드: `/boardDownload.es?bid=0026&list_no={id}&seq={seq}`

### HIRA InfoBank
- Nexacro14 JavaScript 프레임워크 → 브라우저 렌더링 필수
- Playwright로 페이지 로드 후 Nexacro 데이터셋 JavaScript 접근
- 실제 컬럼명은 첫 실행 시 스크린샷(`data/files/hira/hira_screenshot.png`)으로 확인 필요
