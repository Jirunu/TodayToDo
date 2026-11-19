# TodayToDo

매일 IT 뉴스에서 공부할 CS 개념을 뽑고, 그 개념과 이어지는 백준 문제를 추천받아 **1일 1CS · 1일 1솔 · 1일 1커밋**을 하는 저장소입니다.

```
③ News   네이버 뉴스 검색 API로 분야별 최신 뉴스 수집
   ↓
① CS     오늘의 커리큘럼 개념 + 뉴스에서 뽑은 개념 (Claude API)
   ↓
② Coding 개념과 이어지는 solved.ac 태그 → 내 수준의 안 푼 문제
   ↓
④ Commit 내가 쓴 요약(notes/)과 풀이(solutions/)를 커밋 → 잔디
```

## 오늘

<!-- TODAY:START -->
아직 첫 실행 전입니다.
<!-- TODAY:END -->

## 매일 하는 일

1. 07:00 KST에 GitHub Actions가 `daily/날짜.md`를 만들고 이 README를 갱신합니다.
2. 오늘의 CS를 공부하고 `notes/날짜.md`에 요약합니다. ([템플릿](notes/TEMPLATE.md))
3. 오늘의 문제를 풀고 `solutions/BOJ_번호.확장자`로 커밋합니다.

자동 커밋은 봇 계정이라 잔디에 잡히지 않습니다. 잔디는 내가 직접 한 공부 커밋으로만 채워집니다.
로컬에서 커밋하기 전에 `git pull`로 봇이 만든 파일을 먼저 받아 오세요.

## 자동으로 쌓이는 것

| 기능 | 내용 |
|---|---|
| 문제 추천 | 오늘 개념과 이어지는 태그 → 없으면 solved.ac 기준 내가 가장 적게 푼 태그 |
| 검색어 자동 확장 | 뉴스에 반복해서 나온 용어를 다음 날 검색어에 추가, 7일간 안 나오면 제외 (`data/keywords.json`) |
| 확인 퀴즈 | 오늘 개념으로 단답·O/X 3문제, 정답은 접어서 표시 |
| 중복 방지 | 최근 30일 동안 공부한 개념은 뉴스 개념으로 다시 고르지 않음 |
| 복습 | 1일, 7일, 30일 전에 공부한 개념을 오늘 페이지에 다시 표시 |
| 개념 아카이브 | 지금까지 나온 개념 전체, 반복 횟수, 과목별 개념 연결 그래프 ([concepts.md](concepts.md)) |
| 공부 잔디 | 최근 20주 동안 노트·풀이 기록을 잔디 그림으로 (`assets/heatmap.svg`) |
| 주간 리포트 | 월요일 아침에 지난주 노트·풀이·키워드·LLM 토큰 사용량 정리 (`weekly/`) |
| 디스코드 알림 | `DISCORD_WEBHOOK_URL` Secret이 있으면 아침마다 요약 전송 |

## 설정

| 항목 | 위치 |
|---|---|
| 뉴스 분야와 검색어 | `config.json`의 `field`, `fields` |
| solved.ac 아이디, 난이도 | `config.json`의 `solvedac_handle`, `tier` |
| CS 커리큘럼 | `config.json`의 `curriculum` |
| API 키 | 저장소 Settings → Secrets: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `ANTHROPIC_API_KEY` |
| 디스코드 알림 (선택) | Secrets: `DISCORD_WEBHOOK_URL` |
| 웹 페이지 (선택) | Settings → Pages → Branch `main` / `(root)` 선택. 이 README와 `daily/`가 그대로 웹 페이지가 됩니다 |

## 데이터 원칙

- 공식 API만 사용합니다 (네이버 검색 API, solved.ac API, Claude API).
- 기사 본문은 저장하지 않고 제목, 요약문, 링크만 사용합니다.
