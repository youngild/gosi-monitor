"""
고시 내용 요약 — 의사랑 EMR 적용 이슈 기준
- ANTHROPIC_API_KEY 환경변수가 있으면 Claude API (고품질)
- 없으면 로컬 규칙 기반 추출 (API 키 불필요)
"""
import os
import re
import zipfile
import xml.etree.ElementTree as ET
import pdfplumber

CLAUDE_MODEL = "claude-sonnet-4-6"


# ══════════════════════════════════════════════════════
#  텍스트 추출
# ══════════════════════════════════════════════════════

def extract_text_from_pdf(file_path: str) -> str:
    text = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages[:40]:
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
                        for elem in tree.getroot().iter():
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
    elif ext == 'txt':
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            return f.read()
    return ''


# ══════════════════════════════════════════════════════
#  텍스트 정제
# ══════════════════════════════════════════════════════

def _clean(text: str) -> str:
    text = re.sub(r'\(cid:\d+\)', '', text)
    text = re.sub(r'발\s*간\s*등\s*록\s*번\s*호[^\n]*', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ══════════════════════════════════════════════════════
#  섹션 추출 (번호 접두어 포함 지원)
# ══════════════════════════════════════════════════════

def _extract_section(text: str, *keywords: str, max_chars: int = 600) -> str:
    """
    '1. 개정이유', '가. 주요내용' 등 번호 접두어가 붙은 헤더도 인식.
    헤더 이후 내용을 최대 max_chars 글자까지 수집.
    """
    pattern = (
        r'(?:^|\n)'                          # 줄 시작
        r'[ \t]*(?:\d+\.|[가-힣]\.|[①-⑳])?' # 선택적 번호
        r'[ \t]*(?:' + '|'.join(keywords) + r')'
        r'[ \t]*[：:\.]?\s*\n?'
        r'([\s\S]{10,})'
    )
    m = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return ''

    raw = m.group(1)
    lines = []
    total = 0
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        # 다음 섹션 헤더가 나오면 중단
        if re.match(
            r'^(?:\d+\.|[가-힣]\.|[①-⑳]|○|■|▶|※|제\d+조|붙임|부칙|별표|별첨|참고|합\s*의|예산)',
            s
        ):
            if lines:  # 첫 줄이 아닌 경우만 중단
                break
        lines.append(s)
        total += len(s)
        if total >= max_chars:
            break

    result = ' '.join(lines).strip()
    # 한글이 충분히 있어야 유효
    if len(re.findall(r'[가-힣]', result)) < 10:
        return ''
    return result[:max_chars]


def _extract_date(text: str) -> str:
    patterns = [
        r'이\s*(?:규정|고시|지침|훈령|예규)은?\s*([\d]{4}년\s*\d+월\s*\d+일)\s*부터?\s*시행',
        r'시행일\s*[：:]\s*([^\n]{5,60})',
        r'(\d{4}년\s*\d+월\s*\d+일)\s*부터\s*시행',
        r'공포한?\s*날부터\s*시행',
        r'공포일부터\s*시행',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            g = m.group(0) if '공포' in p else m.group(1)
            return g.strip()[:80]
    return ''


def _extract_target(text: str) -> str:
    return _extract_section(
        text,
        r'적용\s*대상', r'지원\s*대상', r'대상\s*기관', r'이용\s*대상',
        max_chars=150
    )


# ══════════════════════════════════════════════════════
#  EMR 영향 분석 (키워드 기반)
# ══════════════════════════════════════════════════════

# (키워드, EMR 영향 설명, 모듈)
EMR_IMPACT_RULES = [
    (r'수가|행위\s*코드|급여\s*기준|비급여',  '수가코드·급여기준 변경 → 수가 테이블 업데이트 필요', '청구/수납'),
    (r'처방전|처방\s*전달|처방\s*코드',       '처방 관련 변경 → 처방 모듈 검토 필요', '처방'),
    (r'의약품|약품\s*코드|급여\s*중지|급여\s*중지\s*해제', '의약품 코드·급여 변동 → 약품 마스터 업데이트', '처방/약품'),
    (r'서식|기재\s*항목|필수\s*입력|진료\s*기록|의무\s*기록', '서식·필수 기재항목 변경 → 화면·서식 수정 필요', '의무기록'),
    (r'전자\s*바우처|바우처\s*결제|전자\s*청구',  '전자바우처 처리 절차 변경 → 수납/청구 연동 확인', '수납/청구'),
    (r'청구|심사\s*청구|요양\s*급여\s*비용',     '청구 방식·코드 변경 → 청구 모듈 검토 필요', '청구'),
    (r'신고|통보\s*의무|보고\s*의무',            '신고·통보 의무 추가·변경 → 신고 기능 확인', '신고/보고'),
    (r'인터페이스|연동|API|표준\s*코드',         '시스템 연동·인터페이스 변경 가능성', '연동'),
    (r'동의서|설명문|동의\s*서식',               '동의서 서식 변경 → 동의서 모듈 확인', '동의서'),
    (r'원무|수납|납부',                          '원무·수납 프로세스 변경 가능성', '원무/수납'),
]


def _analyze_emr_impact(text: str) -> list[str]:
    """텍스트에서 EMR 영향 키워드를 찾아 이슈 목록 반환."""
    hits = []
    seen_modules = set()
    for pattern, message, module in EMR_IMPACT_RULES:
        if re.search(pattern, text) and module not in seen_modules:
            hits.append(f"• [{module}] {message}")
            seen_modules.add(module)
    return hits


# ══════════════════════════════════════════════════════
#  로컬 요약 (EMR 이슈 기준)
# ══════════════════════════════════════════════════════

def _local_summarize(title: str, content: str) -> str:
    text = _clean(content)
    if len(text) < 50:
        return "[텍스트 내용이 너무 짧아 요약할 수 없습니다]"

    sections = []

    # ① 개정이유 / 제정이유
    reason = _extract_section(text, r'개정\s*이유', r'제정\s*이유', max_chars=400)
    if reason:
        sections.append(f"📌 개정이유\n{reason}")

    # ② 주요내용
    main = _extract_section(text, r'주요\s*내용', r'개정\s*주요내용', max_chars=500)
    if main:
        sections.append(f"📋 주요내용\n{main}")

    # ③ 목적 (개정이유·주요내용 없는 지침류)
    if not reason and not main:
        purpose = _extract_section(text, r'목\s*적', r'사업\s*목적', r'추진\s*배경', max_chars=300)
        if purpose:
            sections.append(f"🎯 목적 / 추진배경\n{purpose}")

    # ④ EMR 영향 분석
    emr_hits = _analyze_emr_impact(text)
    if emr_hits:
        sections.append("🏥 EMR 적용 검토 항목\n" + '\n'.join(emr_hits))
    else:
        sections.append("🏥 EMR 적용 검토 항목\n• 직접적인 EMR 시스템 변경 키워드 미감지\n• 원문 확인 후 업무 프로세스 변경 여부 확인 권장")

    # ⑤ 시행일
    date = _extract_date(text)
    if date:
        sections.append(f"📅 시행일\n{date}")

    # ⑥ 적용 대상
    target = _extract_target(text)
    if target:
        sections.append(f"👥 적용 대상\n{target}")

    # 아무것도 못 찾은 경우
    if len(sections) <= 1:  # EMR 항목만 있는 경우
        sections.insert(0,
            f"📄 문서 유형\n{_doc_type_desc(title)}\n\n"
            "⚠️ 이 문서는 비교표·목록 형식으로 자동 추출이 어렵습니다.\n"
            "첨부파일 원문을 직접 확인하세요."
        )

    sections.append(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ ANTHROPIC_API_KEY 설정 시 Claude AI가 EMR 적용 사항을 상세 분석합니다."
    )

    return '\n\n'.join(sections)


def _doc_type_desc(title: str) -> str:
    t = re.sub(r'새글|\[.*?\]|「|」', '', title).strip()
    if '일부개정' in title:  return f'고시 일부개정 — {t[:60]}'
    if '전부개정' in title:  return f'고시 전부개정 — {t[:60]}'
    if '제정' in title:       return f'신규 제정 고시 — {t[:60]}'
    if '폐지' in title:       return f'고시 폐지 — {t[:60]}'
    if '급여중지' in title:   return f'보험급여 급여중지 안내 — {t[:60]}'
    if '해제' in title:       return f'급여중지 해제 안내 — {t[:60]}'
    return t[:80]


# ══════════════════════════════════════════════════════
#  Claude API 요약 (EMR PM 전용 프롬프트)
# ══════════════════════════════════════════════════════

def _claude_summarize(title: str, content: str, api_key: str) -> str:
    import anthropic

    text = _clean(content)
    if len(text) > 12000:
        text = text[:8000] + '\n\n...(중략)...\n\n' + text[-3000:]

    prompt = f"""당신은 "의사랑" EMR(전자의무기록) 시스템의 PM입니다.
아래 보건의료 고시/지침 문서를 분석하여, **EMR 제품에 적용해야 하는 이슈** 중심으로 정리하세요.
없는 항목은 반드시 생략하고, 있는 항목만 간결하게 작성하세요.

제목: {title}

문서 내용:
{text}

---
## 출력 형식 (해당 항목만 작성)

📌 개정이유
(한 줄로 핵심만)

📋 주요 변경 내용
- (변경사항 bullet)

🏥 EMR 적용 필요 사항
- [모듈명] 변경 내용 및 조치 사항
  예) [청구] 수가코드 XXX 신설 → 청구 코드 테이블 추가
      [처방] 처방 서식 필수항목 변경 → 입력화면 수정
      [의무기록] 기재 의무 항목 추가
      [수납] 바우처 처리 방식 변경

⚠️ 미적용 시 위험
- (청구 오류, 법적 의무 위반 등 구체적 위험)

📅 시행일 / 대응 기한
- (날짜 및 EMR 반영 기한)

👥 적용 대상 기관
- (해당 의료기관 유형)"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text
    except Exception as e:
        return f"[Claude 오류: {e}]"


# ══════════════════════════════════════════════════════
#  공개 인터페이스
# ══════════════════════════════════════════════════════

def summarize(title: str, content: str) -> str:
    if not content or not content.strip():
        return "[첨부파일에서 텍스트를 추출할 수 없습니다]"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        print("    (Claude API - EMR 분석)")
        return _claude_summarize(title, content, api_key)
    else:
        print("    (로컬 규칙 기반 - EMR 이슈 추출)")
        return _local_summarize(title, content)
