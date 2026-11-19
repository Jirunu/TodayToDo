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

## 설정

| 항목 | 위치 |
|---|---|
| 뉴스 분야와 검색어 | `config.json`의 `field`, `fields` |
| solved.ac 아이디, 난이도 | `config.json`의 `solvedac_handle`, `tier` |
| CS 커리큘럼 | `config.json`의 `curriculum` |
| API 키 | 저장소 Settings → Secrets: `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `ANTHROPIC_API_KEY` |

## 데이터 원칙

- 공식 API만 사용합니다 (네이버 검색 API, solved.ac API, Claude API).
- 기사 본문은 저장하지 않고 제목, 요약문, 링크만 사용합니다.
