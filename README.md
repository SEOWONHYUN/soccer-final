# WONHYUN FOOTBALL HUB — 최종 통합본

유럽 5대 리그의 경기 일정, 관련 뉴스, 팀 스쿼드와 선수 사진을 검색하고 CSV로 저장하는 Flask 프로젝트입니다.

## 이번 최종본 반영 내용

### 디자인
- 기존 페이지 구성과 챔피언스리그 계열의 짙은 남색 테마 유지
- 그라데이션, 둥근 테두리, 그림자, 장식 아이콘 제거
- 직선 구분선과 흰색·남색·파란색만 사용한 평면형 편집 디자인
- 모바일 반응형 유지

### 뉴스
- Google News 한국어 RSS 재시도
- Bing News RSS 대체 수집
- Google News 영어 RSS 추가 대체 수집
- RSS의 `link`, `guid`, `source`, `description`을 순서대로 확인해 URL 누락 방지
- 뉴스가 한 번 실패해 빈 결과가 나오면 캐시에 저장하지 않고 다음 검색에서 재시도
- 뉴스 제목을 누르면 기사 페이지가 새 탭에서 열림

### 선수단과 선수 사진
- Wikipedia 선수단 표의 열 개수가 달라도 포지션 칸을 기준으로 선수 추출
- 기본 팀 문서의 선수 수가 부족하면 시즌 문서를 추가 확인
- 선수 사진 수집 순서:
  1. 선수단 표의 정확한 Wikipedia 문서
  2. Wikipedia 대표 이미지
  3. Wikidata P18 이미지
  4. 선수 이름과 팀명으로 Wikipedia 재검색
  5. Wikimedia Commons 재검색
- 사진 URL이 깨지면 `/player-photo` 경로에서 다른 사진을 다시 찾음
- fallback 사진은 Flask가 받아 전달하여 외부 이미지 직접 로딩 오류를 줄임

### Render
- `gunicorn` 포함
- `.python-version`으로 Python 3.12.11 고정
- `render.yaml` 포함
- `/health` 상태 확인 주소 추가
- 빈 뉴스·실패 선수단 결과를 캐시에 고정하지 않음

## 로컬 실행

```bash
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

접속 주소:

```text
http://127.0.0.1:5000
```

## Render 설정

GitHub 저장소 최상단에 `app.py`, `scrapper.py`, `requirements.txt`가 보이면 Root Directory는 비워둡니다.

```text
Service Type: Web Service
Build Command: pip install -r requirements.txt
Start Command: gunicorn --workers 1 --threads 6 --timeout 180 --bind 0.0.0.0:$PORT app:app
Health Check Path: /health
```

`render.yaml`로 새 Web Service를 만들 경우 위 설정이 자동으로 적용됩니다.

## 주의

외부 사이트의 HTML 구조나 공개 이미지 등록 상태가 바뀌면 일부 일정·선수·사진이 누락될 수 있습니다. Wikipedia, Wikidata, Wikimedia Commons 어디에도 공개 사진이 없는 선수는 `PHOTO UNAVAILABLE`로 표시됩니다.
