# 📈 스윙 종목 추천기 (sr2)

국장 + 미장 스윙 매매 추천. 6 에이전트 분석.

## 특징

- **자동 풀**: 매번 한투/Yahoo에서 거래대금 상위 종목 자동 추출
- **6 에이전트 분석**: 차트, 펀더, 매크로, 뉴스, 수급, 리스크
- **AI 효율화**: 차트/펀더/수급/리스크는 코드 계산. 매크로/뉴스/판정만 AI 호출 (월 5천원대)
- **다크모드 카드 UI**, 모바일 친화적
- **자동 가격 검증**: 손절 < 현재가 < 익절
- **재분석 버튼**: 카드별로 재추첨

## 로컬 설치

```cmd
cd C:\stock_recommender_v2
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# .env 만들기
copy .env.example .env
notepad .env
```

`.env`에 모든 API 키 입력 후 저장.

## 검증

```cmd
python -m tests.test_full
```

모든 [11] 단계가 ✅ 나와야 정상. Claude AI 호출 1회 = 약 0.5센트.

## 실행

```cmd
streamlit run ui/app.py
```

브라우저 자동 열림. **"추천 받기"** 클릭.

## Streamlit Cloud 배포

1. GitHub에 private repo 생성
2. `.env` 제외(자동) + 코드만 push
3. https://share.streamlit.io 가입 (GitHub 계정)
4. **New app** → 본인 repo 선택, branch `main`, file `ui/app.py`
5. **Advanced settings** → **Secrets**에 `.streamlit/secrets.toml.example` 내용 복사 + 실제 키 입력
6. **Deploy** 클릭. 5분 후 URL 발급.
7. 폰에서 URL 접속 → 홈 화면에 추가

## 비용

- AI: 추천 1회 약 30~60원
- 호스팅: Streamlit Cloud 무료
- 데이터 API: 모두 무료 (KIS/Finnhub/NewsAPI/FRED/Polygon)
- **월 평균 5,000원 이하** (하루 3회 사용 기준)

## 주의

- ⚠️ 투자 참고용. 매매 결과 책임은 본인.
- ⚠️ `.env`, `logs/`, `*.db`는 절대 GitHub에 푸시 금지 (`.gitignore` 자동 처리)
- ⚠️ Claude/한투 등 API 키 노출 즉시 재발급
