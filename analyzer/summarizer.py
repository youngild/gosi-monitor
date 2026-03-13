"""
고시 내용 요약
- ANTHROPIC_API_KEY 환경변수가 있으면 Claude API 사용 (고품질)
- 없으면 로컬 패턴 추출 방식 사용 (API 키 불필요)
"""
import os
import re
import zipfile
import xml.etree.ElementTree as ET
import pdfplumber

CLAUDE_MODEL = "claude-sonnet-4-6"


# ── 텍스트 추출 ──────────────────────────────────────────────

def extract_text_from_pdf(file_path: str) -> str:
    text = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages[:30]:
                t = page.extract_text()
                if t:
                    text.append(t)
    except Exception as e:
        print(f"[요약] PDF 추출 오류: {e}")
    return '\n'.join(text)


def extract_text_from_hwpx(file_path: str) -> str:
    texts = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            names = sorted([n for n in z.namelist() if n.startswith('Contents/section')])
            if not names:
                names = [n for n in z.namelist() if n.endswith('.xml')]
            for name in names[:10]:
                with z.open(name) as f:
                    try:
                        tree = ET.parse(f)
                        root = tree.getroot()
                        for elem in root.iter():
                            if elem.text and elem.text.strip():
                                texts.append(elem.text.strip())
                            if elem.tail and elem.tail.strip():
                                texts.append(elem.tail.strip())
                    except ET.ParseError:
                        pass
    except Exception as e:
        print(f"[요약] HWPX 추출 오류: {e}")
    return '\n'.join(texts)


def extract_text_from_file(file_path: str) -> str:
    ext = file_path.rsplit('.', 1)[-1].lower()
    if ext == 'pdf':
        return extract_text_from_pdf(file_path)
    elif ext == 'hwpx':
        return extract_text_from_hwpx(file_path)
    elif ext == 'hwp':
        return ''
    elif ext == 'txt':
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            return f.read()
    return ''


# ── 로컬 패턴 기반 요약 ──────────────────────────────────────

def _find_section(text: str, *headers: str, max_len: int = 300) -> str:
    """
    헤더 키워드 이후의 산문 텍스트를 추출한다.
    여러 줄에 걸쳐 있을 수 있으므로 단락 단위로 수집.
    """
    for header in headers:
        m = re.search(
            rf'(?:^|\n)\s*{header}\s*[：:\n]?\s*(.{{10,}})',
            text, re.MULTILINE
        )
        if m:
            chunk = m.group(1).strip()
            # 다음 섹션 헤더까지 수집
            lines = [chunk]
            rest = text[m.end():]
            for line in rest.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                # 다음 헤더가 나오면 중단
                if re.match(r'^(?:\d+\.|가\.|나\.|다\.|○|■|▶|※|Ⅰ|Ⅱ|붙임|부칙|별표|별첨)', stripped):
                    break
                lines.append(stripped)
                if sum(len(l) for l in lines) >= max_len:
                    break
            result = ' '.join(lines)[:max_len]
            # 너무 짧으면 skip
            if len(re.findall(r'[가-힣]', result)) >= 10:
                return result
    return ''


def _find_date(text: str) -> str:
    """시행일 패턴 탐색."""
    patterns = [
        r'이\s*(?:규정|고시|지침|훈령|예규)은?\s*([\d]{4}년\s*\d+월\s*\d+일)(?:부터)?\s*시행',
        r'시행일\s*[：:]\s*([^\n.]{5,50})',
        r'(\d{4}년\s*\d+월\s*\d+일)\s*부터\s*시행',
        r'공포일부터\s*시행',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0 if '공포일' in pat else 1).strip()[:60]
    return ''


def _is_clean(text: str, min_korean: int = 8) -> bool:
    """비교표·표 잔재가 없는 깨끗한 산문인지 확인."""
    korean = len(re.findall(r'[가-힣]', text))
    if korean < min_korean:
        return False
    # 비교표 잔재 패턴 (구 내용 / 개정 내용이 반복)
    if re.search(r'기존\s*내용|구\s*내용|신\s*구\s*조', text):
        return False
    return True


def _title_based_desc(title: str) -> str:
    """제목을 분석해 문서 유형 설명 생성."""
    clean = re.sub(r'새글|\[.*?\]', '', title).strip()
    clean = re.sub(r'「|」|\'|\'', '', clean).strip()

    if '일부개정' in title or '전부개정' in title:
        kind = '일부개정' if '일부개정' in title else '전부개정'
        return f"고시 {kind} 문서입니다.\n대상: {clean[:60]}"
    if '폐지' in title:
        return f"고시 폐지 문서입니다.\n대상: {clean[:60]}"
    if '제정' in title:
        return f"신규 제정 고시입니다.\n대상: {clean[:60]}"
    if '사업안내' in title or '지침' in title or '매뉴얼' in title:
        return f"사업 안내/지침 문서입니다.\n내용: {clean[:80]}"
    if '급여중지' in title:
        return f"보험급여 등재 약제 급여중지 안내 문서입니다.\n대상 업체: {clean[clean.rfind('(')+1:clean.rfind(')')]}"
    if '해제' in title:
        return f"급여중지 해제 안내 문서입니다.\n대상: {clean[:60]}"
    return clean[:100]


def _local_summarize(title: str, content: str) -> str:
    """문서 전체를 스캔해 신뢰도 높은 정보만 추출."""

    # 전처리
    text = re.sub(r'\(cid:\d+\)', '', content)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    lines = []

    # ① 개정이유 / 제정이유
    reason = _find_section(text, r'개정\s*이유', r'제정\s*이유', max_len=300)
    if reason and _is_clean(reason):
        lines.append(f"📌 **개정이유**\n{reason}")

    # ② 주요내용
    main = _find_section(text, r'주요\s*내용', r'개정\s*주요내용', max_len=350)
    if main and _is_clean(main):
        lines.append(f"📋 **주요내용**\n{main}")

    # ③ 시행일 (항상 신뢰도 높음)
    date = _find_date(text)
    if date:
        lines.append(f"📅 **시행일**\n{date}")

    # ④ 목적 (개정이유·주요내용 없는 경우)
    if not lines:
        purpose = _find_section(text, r'목\s*적', r'사업\s*목적', max_len=200)
        if purpose and _is_clean(purpose):
            lines.append(f"🎯 **목적**\n{purpose}")

    # 아직도 없으면 제목 기반 설명
    if not lines:
        lines.append(f"📄 **문서 유형**\n{_title_based_desc(title)}")

    # EMR 적용 관련 키워드가 본문에 있으면 추출
    emr_hits = []
    emr_keywords = {
        '수가': '수가코드 변경 가능성 — 청구 모듈 확인 필요',
        '청구': '청구 관련 변경 — 청구 모듈 검토 필요',
        '처방': '처방 관련 변경 — 처방 모듈 검토 필요',
        '서식': '서식 변경 — EMR 입력 화면 수정 필요',
        '기재': '기재 항목 변경 — 입력 양식 수정 필요',
        '전산': '전산 시스템 변경 요구 가능성',
        '코드': '코드 체계 변경 — 코드 테이블 업데이트 필요',
        '인터페이스': '인터페이스 변경 — 연동 시스템 확인 필요',
        '신고': '신고 관련 — 관련 신고 기능 확인 필요',
    }
    for kw, msg in emr_keywords.items():
        if kw in text:
            emr_hits.append(f"• {msg}")
    if emr_hits:
        lines.append("🏥 **EMR 검토 포인트** (키워드 감지)\n" + '\n'.join(emr_hits[:4]))

    lines.append("ℹ️ *Claude API 키를 설정하면 EMR 적용사항을 상세히 분석합니다.*")

    return '\n\n'.join(lines)


# ── Claude API 요약 ──────────────────────────────────────────

def _claude_summarize(title: str, content: str, api_key: str) -> str:
    import anthropic

    text = re.sub(r'\(cid:\d+\)', '', content)
    if len(text) > 10000:
        text = text[:7000] + "\n\n...(중략)...\n\n" + text[-2000:]

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""당신은 "의사랑" EMR(전자의무기록) 시스템의 PM입니다.
아래 보건의료 고시/지침 문서를 읽고, EMR 제품 운영·개발 관점에서 실무적으로 정리해 주세요.

제목: {title}

내용:
{text}

다음 항목 중 해당하는 것만 작성하세요 (없으면 생략):

📌 **개정이유 / 배경** (1~2줄)

📋 **EMR 적용 필요 사항**
- (수가코드·청구코드 변경이 있으면 명시)
- (입력 서식·필수 항목 변경이 있으면 명시)
- (기능 추가·수정이 필요한 모듈 명시: 처방/수납/청구/기록 등)
- (데이터 연동·인터페이스 변경 필요 여부)

⚠️ **주의사항 / 리스크**
- (미적용 시 청구 오류·법적 문제 등)

📅 **시행일 및 대응 기한**
- (언제까지 EMR에 반영해야 하는지)

👥 **적용 대상 기관**
- (어떤 의료기관이 해당되는지)"""

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        return f"[Claude 오류: {e}]"


# ── 공개 인터페이스 ──────────────────────────────────────────

def summarize(title: str, content: str) -> str:
    """API 키가 있으면 Claude, 없으면 로컬 패턴 추출로 요약."""
    if not content or not content.strip():
        return "[텍스트를 추출할 수 없습니다]"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        print("    (Claude API 사용)")
        return _claude_summarize(title, content, api_key)
    else:
        print("    (로컬 패턴 추출)")
        return _local_summarize(title, content)
