# WORK ORDER — V2 확장 작업 지시서

> 본인 로컬에서 `cd ai-theme-dispersion-monitor && claude` 후, 이 파일을 통째로 Claude Code에 붙여넣고 "이 작업 지시서대로 step by step으로 진행해줘"라고 시작하세요. 각 단계마다 git commit을 끊어가며 진행하면 면접에서 보여줄 commit history도 깔끔해집니다.

---

## 0. 목표 (Why)

운용역의 의사결정 워크플로우를 1페이지가 아닌 **다중 페이지 대시보드**로 확장하여:
1. 홈에서 핵심 시그널을 요약 제공
2. 백테스트 페이지에서 "분산 기반 로테이션 전략"의 실증 결과 제시
3. 시그널 페이지에서 팩터 노출도와 종목별 분산 기여도 제공
4. 실제 데이터(US + Korean tickers)로 매일 GitHub Actions가 갱신

면접 어필 포인트: **multi-page SPA-like 구조, 실데이터 파이프라인, CI/CD, 한국 시장 통합**

---

## 1. 사전 점검

```bash
cd ai-theme-dispersion-monitor
git status        # working tree clean이어야 함
python -V         # 3.10 이상 권장
pip install -r requirements.txt
```

`requirements.txt`에 추가해야 할 패키지:
```
finance-datareader>=0.9.0   # KRX 한국 종목용
pykrx>=1.0.45               # KRX 백업
```

---

## 2. 작업 분할 (각 섹션 = 1 commit)

### 단계 1 — `universe.py`에 Korean tickers 추가

`AI_THEMES` 딕셔너리에 새 키 `kr_ai`를 추가합니다.

```python
AI_THEMES = {
    # ... 기존 그대로 ...
    "kr_ai": [
        "005930.KS",   # 삼성전자 — HBM, 파운드리
        "000660.KS",   # SK하이닉스 — HBM3E 선두
        "042700.KS",   # 한미반도체 — TC본더 (HBM CAPEX 수혜)
        "058470.KQ",   # 리노공업 — 반도체 테스트 소켓
    ],
}
```

`fetch.py`는 yfinance가 `.KS`/`.KQ` 접미사를 그대로 지원하니 수정 불필요. 단, 한국장은 미국장보다 휴장일이 다르므로 dispersion 계산 시 `dropna(how='any')` 대신 `dropna(how='all')`을 유지해야 함 (이미 그렇게 됨, 확인만).

**검증:**
```bash
cd src && python fetch.py
# 005930.KS 등 4개 종목 행이 찍히는지 확인
```

**Commit:** `feat(universe): add Korean AI semiconductor tickers (Samsung, SK Hynix, Hanmi Semi, Leeno)`

---

### 단계 2 — `db.py`에 백테스트·팩터 테이블 추가

`SCHEMA` 문자열 끝에 다음 추가:

```sql
CREATE TABLE IF NOT EXISTS backtest_returns (
    date     TEXT NOT NULL,
    strategy TEXT NOT NULL,
    ret      REAL NOT NULL,
    nav      REAL NOT NULL,
    PRIMARY KEY (date, strategy)
);

CREATE TABLE IF NOT EXISTS factor_exposure (
    date    TEXT NOT NULL,
    ticker  TEXT NOT NULL,
    factor  TEXT NOT NULL,
    score   REAL NOT NULL,
    PRIMARY KEY (date, ticker, factor)
);

CREATE INDEX IF NOT EXISTS idx_factor_date ON factor_exposure(date);
```

대응 upsert/loader 함수도 추가:
- `upsert_backtest_returns(df: pd.DataFrame)` — `INSERT OR REPLACE` 패턴 동일
- `upsert_factor_exposure(df: pd.DataFrame)` — long-format (date, ticker, factor, score)
- `load_backtest_returns(strategy: str | None = None) -> pd.DataFrame`
- `load_latest_factor_exposure() -> pd.DataFrame` — wide format (ticker × factor)

**검증:** `python -c "from db import connect; connect().__enter__()"` 후 sqlite3 CLI로 `.schema` 확인

**Commit:** `feat(db): add backtest_returns and factor_exposure tables with upserts`

---

### 단계 3 — `backtest.py` 신규 작성

**전략 가설:**
- 분산 높음(avg_corr 하위 30% 분위) → **모멘텀**: 직전 21일 수익률 상위 N=3 종목 동일가중
- 분산 낮음 → **동일가중 전체 유니버스** (스톡픽 알파가 잘 안 나오니까 베타로)
- 리밸런싱: 매월 첫 영업일
- 비교 벤치마크: 유니버스 동일가중 buy & hold

**핵심 함수:**
```python
def run_backtest(
    prices: pd.DataFrame,       # date × ticker, equity only
    dispersion: pd.DataFrame,   # date-indexed, avg_corr
    top_n: int = 3,
    rebalance: str = "M",       # month-end
) -> pd.DataFrame:
    """Returns df with columns: ['strategy_ret', 'bench_ret', 'strategy_nav', 'bench_nav']"""
```

**메트릭 함수:**
```python
def metrics(ret: pd.Series) -> dict:
    # CAGR, Sharpe(연환산, rf=0), MDD, hit_rate, vol
```

**main():** prices/dispersion 로드 → backtest → metrics 출력 → `upsert_backtest_returns` (strategy in {'rotation', 'benchmark'})

**검증:** `python backtest.py` 출력에 Sharpe ≥ 0, NAV 시리즈 길이 일치

**Commit:** `feat(backtest): dispersion-conditional rotation strategy + benchmark`

---

### 단계 4 — `factors.py` 신규 작성

**5개 팩터 (수익률 기반 프록시, 단순함 우선):**

| 팩터 | 계산 |
|---|---|
| `momentum` | 직전 252일 수익률 − 직전 21일 수익률 (12-1 momentum) |
| `lowvol` | −1 × 직전 60일 일수익률 표준편차 (낮을수록 점수 ↑) |
| `quality` | 252일 수익률 / 252일 변동성 (정보비율 프록시) |
| `size` | −1 × log(현재 close) (낮은 가격일수록 score↑) ⚠ proper market cap이 아니므로 V3에서 보강 노트 |
| `reversal` | −1 × 직전 21일 수익률 (단기 평균회귀) |

**Cross-section z-score** 정규화 후 저장 (날짜별 각 팩터 평균 0, std 1).

```python
def compute_factors(prices: pd.DataFrame) -> pd.DataFrame:
    """returns long-format df: (date, ticker, factor, score)"""
```

**main():** 마지막 252일 윈도우로 계산 → 가장 최근 30일치만 DB에 저장 (저장 비용 절약).

**검증:** 한 날짜에 대해 각 팩터의 mean ≈ 0, std ≈ 1

**Commit:** `feat(factors): cross-sectional z-score for momentum/lowvol/quality/size/reversal`

---

### 단계 5 — `visualize.py`를 멀티페이지로 리팩터링

`src/visualize.py` 하나가 `docs/`에 3개 HTML을 만들도록 변경:

```
docs/
├── index.html       # 홈: KPI 카드 + 상관 차트 + regime ribbon (현재 차트의 간소 버전)
├── backtest.html    # NAV 곡선, drawdown, 메트릭 테이블, 리밸 시점 마커
└── signals.html     # 팩터 히트맵 (ticker × factor) + 분산 기여도 막대
```

**공통 nav HTML 스니펫 (Russian real-estate 사이트처럼 깔끔한 상단 메뉴):**

```html
<style>
  body{font-family:-apple-system,sans-serif;margin:0;background:#f5f7fa;color:#1a1f2c}
  .nav{display:flex;gap:24px;padding:18px 32px;background:#fff;
       border-bottom:1px solid #e4e7ec;align-items:center}
  .nav .brand{font-weight:700;font-size:18px}
  .nav a{color:#3a4554;text-decoration:none;font-size:14px}
  .nav a.active{color:#1f6feb;font-weight:600}
  .container{max-width:1200px;margin:24px auto;padding:0 24px}
  .kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}
  .kpi .card{background:#fff;padding:20px;border-radius:12px;
             box-shadow:0 1px 3px rgba(0,0,0,.06)}
  .kpi .label{font-size:12px;color:#6b7280;text-transform:uppercase}
  .kpi .value{font-size:24px;font-weight:700;margin-top:6px}
  .kpi .delta.up{color:#10b981} .kpi .delta.down{color:#ef4444}
</style>
<nav class="nav">
  <div class="brand">AI Theme Dispersion Monitor</div>
  <a href="index.html"    class="{ACTIVE_HOME}">Overview</a>
  <a href="backtest.html" class="{ACTIVE_BT}">Backtest</a>
  <a href="signals.html"  class="{ACTIVE_SIG}">Signals</a>
  <span style="margin-left:auto;font-size:12px;color:#6b7280">
    Updated <span id="ts"></span>
  </span>
</nav>
<script>document.getElementById('ts').textContent=new Date().toISOString().slice(0,10)</script>
```

`visualize.py`에 `_wrap(plotly_fig_html: str, active: str, kpis: dict) -> str` 헬퍼를 만들고 3개 페이지에서 재사용.

**각 페이지 콘텐츠:**

**index.html (Overview):**
- KPI 카드 4개: 최신 avg_corr, return_std, 현재 regime 라벨, 최근 30일 spread 평균
- 분산 3개 지표 시계열 (현재 visualize.py의 row 1+2)
- regime band 오버레이 유지

**backtest.html:**
- KPI 카드 4개: Strategy CAGR, Sharpe, MDD, Hit rate
- NAV 곡선 (strategy vs benchmark)
- Drawdown 차트
- 월별 수익률 히트맵 (year × month)

**signals.html:**
- 팩터 노출도 히트맵 (ticker 행 × factor 열, 색=z-score)
- 종목별 분산 기여도 막대 (∂avg_corr/∂ticker_i 근사)
- 최근 30일 팩터별 평균 노출도 라인

**Commit:** `feat(visualize): multi-page dashboard with shared nav (Overview/Backtest/Signals)`

---

### 단계 6 — GitHub Actions 일일 갱신

`.github/workflows/daily-update.yml` 작성:

```yaml
name: Daily refresh
on:
  schedule:
    - cron: "30 22 * * 1-5"   # 평일 한국시간 07:30 (UTC 22:30 전일)
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }

      - name: Install
        run: pip install -r requirements.txt

      - name: Run pipeline
        working-directory: src
        run: |
          python fetch.py
          python dispersion.py
          python regime.py
          python backtest.py
          python factors.py
          python visualize.py

      - name: Commit refreshed pages
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/ data/
          git diff --cached --quiet || git commit -m "chore: daily refresh $(date -u +%F)"
          git push
```

⚠ `data/market.db`가 `.gitignore`에 있으면 GitHub Actions에서 매일 처음부터 풀링하게 됨 — 정상. DB를 커밋하고 싶다면 `.gitignore`에서 제거하고 `git add data/market.db` 추가.

**검증:** Actions 탭에서 "Run workflow" 수동 트리거 후 docs/*.html가 갱신되어 커밋되는지 확인

**Commit:** `ci: daily pipeline refresh via GitHub Actions`

---

### 단계 7 — README 업데이트

추가할 섹션:
1. **Live dashboard** 링크: `https://chososo.github.io/ai-theme-dispersion-monitor/`
2. **Pages** 표:
   | Page | URL | What it shows |
   |---|---|---|
   | Overview | `/index.html` | Dispersion + regime |
   | Backtest | `/backtest.html` | Rotation strategy NAV |
   | Signals | `/signals.html` | Factor exposure heatmap |
3. **Architecture** 다이어그램 (mermaid):
   ```mermaid
   flowchart LR
     A[universe.py] --> B[fetch.py]
     B --> C[(SQLite)]
     C --> D[dispersion.py]
     C --> E[regime.py]
     C --> F[backtest.py]
     C --> G[factors.py]
     D & E & F & G --> H[visualize.py]
     H --> I[/docs/*.html/]
     I --> J[GitHub Pages]
   ```
4. **Interview talking points** 박스 (기존 답변표 포함)

**Commit:** `docs: README with live URL, architecture diagram, multi-page guide`

---

## 3. 통합 검증 체크리스트

로컬에서 모두 통과해야 함:

```bash
cd src
python fetch.py        # ✓ 14개 종목 + 5개 매크로
python dispersion.py   # ✓ 'wrote N rows'
python regime.py       # ✓ 'wrote N rows'
python backtest.py     # ✓ Sharpe 출력, NAV 시리즈 OK
python factors.py      # ✓ 'wrote N exposure rows'
python visualize.py    # ✓ docs/index.html, backtest.html, signals.html 생성

# 브라우저로 열어보기
open ../docs/index.html
open ../docs/backtest.html
open ../docs/signals.html
```

3페이지 모두에서:
- [ ] 상단 nav가 동일하게 표시되고 현재 페이지가 active
- [ ] 한국 종목(005930.KS 등)이 차트에 포함됨
- [ ] regime band가 오버레이됨
- [ ] 'Updated YYYY-MM-DD' 우상단 표시

---

## 4. 최종 푸시

```bash
git log --oneline    # 단계별로 7개 commit이 깔끔히 보여야 함
git push
```

GitHub Actions가 한 번 돌고 나면 commit history에 `chore: daily refresh ...`가 자동으로 쌓이기 시작합니다. **이게 면접에서 가장 강력한 자료**예요 — "운영 중인 시스템"의 증거.

---

## 5. 면접용 한 줄 요약

> "단일 페이지 PoC에서 출발해 Multi-page dashboard로 확장하면서, 한국 반도체 종목을 통합하고 분산 기반 로테이션 백테스트와 5개 팩터 노출도 모니터를 붙였습니다. 모든 갱신은 GitHub Actions로 자동화됐고, 설계 단계는 Claude(웹)와, 구현 단계는 Claude Code와 페어 프로그래밍했습니다."

---

## 6. V3 백로그 (시간 남으면 / 면접에서 "다음에는?")

- 백테스트: 거래비용 (bps), 슬리피지, 회전율 메트릭
- 시그널: 팩터 IC (Information Coefficient) 시계열
- 데이터: GPR (Geopolitical Risk Index, Caldara & Iacoviello) 외부 연동
- ML: Random Forest로 regime 분류 → rule-based 대비 OOS 성능 비교
- UI: Plotly Dash로 인터랙티브 필터 (서브테마/날짜 범위)
