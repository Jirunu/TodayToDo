"""네트워크 없이 도는 자가 점검: python test_todaytodo.py"""
import json
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

import todaytodo as t

# 뉴스 정제·중복 제거
items = [
    {"title": "<b>Redis</b> 장애 &amp; 복구", "description": "캐시 <b>서버</b>", "originallink": "https://a.com/1", "link": "https://n.com/1"},
    {"title": "중복", "description": "", "originallink": "https://a.com/1", "link": "https://n.com/2"},
    {"title": "원문 없음", "description": "", "originallink": "", "link": "https://n.com/3"},
]
news = t.dedupe(items)
assert [n["link"] for n in news] == ["https://a.com/1", "https://n.com/3"]
assert news[0]["title"] == "Redis 장애 & 복구" and news[0]["desc"] == "캐시 서버"

# 커리큘럼은 시작일 기준으로 순환
start = date.fromisoformat(t.CONFIG["start_date"])
n = len(t.CONFIG["curriculum"])
assert t.curriculum_concept(start) == t.CONFIG["curriculum"][0]
assert t.curriculum_concept(date.fromordinal(start.toordinal() + n)) == t.CONFIG["curriculum"][0]

# 연속 기록: 오늘 노트가 없으면 어제부터 센다
d = date(2026, 12, 10)
days = {date(2026, 12, 9), date(2026, 12, 8), date(2026, 12, 6)}
assert t.streak(days, d) == 2
assert t.streak(days | {d}, d) == 3
assert t.streak(set(), d) == 0

# 밀린 문제: 오늘 이전, 안 푼 것만
def P(i):
    return {"id": i, "title": f"p{i}", "tag": "dp", "reason": "linked"}


def C(name):
    return [{"name": name, "subject": "운영체제"}]


hist = {"2026-12-08": {"problem": P(1), "concepts": C("데드락")},
        "2026-12-09": {"problem": P(2), "concepts": C("페이징")},
        "2026-12-10": {"problem": P(3), "concepts": C("데드락")},
        "2026-12-07": {"problem": None, "concepts": C("스케줄링")},
        "2026-11-10": {"problem": None, "concepts": C("스레드")},
        "2026-12-03": {"problem": None, "concepts": C("캐시")}}
assert [p["id"] for _, p in t.pending_problems(hist, {2}, d)] == [1]

# 복습: 1일, 7일, 30일 전
assert t.review_concepts(hist, d) == [(1, "2026-12-09", ["페이징"]), (7, "2026-12-03", ["캐시"]), (30, "2026-11-10", ["스레드"])]

# 아카이브: 최신순, 반복 횟수 표시
arch = t.render_archive(hist)
assert arch.index("2026-12-10") < arch.index("2026-12-08") and "데드락 ×2" in arch and "개념 5개" in arch

# 주간 리포트: 월요일 기준 지난 7일
mon = date(2026, 12, 14)
wh = {"2026-12-07": {"problem": P(5), "concepts": C("a"), "keywords_added": ["MCP"], "usage": {"input_tokens": 100, "output_tokens": 10}},
      "2026-12-13": {"problem": P(6), "concepts": C("b"), "keywords_added": ["MCP", "HBM"], "usage": {"input_tokens": 50, "output_tokens": 5}},
      "2026-12-14": {"problem": P(7), "concepts": C("오늘은 제외"), "usage": {"input_tokens": 9999, "output_tokens": 0}}}
title, weekly = t.render_weekly(wh, {5}, {date(2026, 12, 7), date(2026, 12, 14)}, mon)
assert title == "2026-W50" and "노트 1/7일" in weekly and "풀이 1/2문제" in weekly
assert "오늘은 제외" not in weekly and "MCP, HBM" in weekly and "입력 150" in weekly

# 검색어 확장: 기본 검색어·너무 긴 말은 제외, 7일 지나면 빠지고, 최대 개수 유지
dyn = t.update_keywords({"오래된": "2026-12-01", "최근": "2026-12-09"}, [" MCP ", "Redis", "", "x" * 21], d, ["Redis"])
assert dyn == {"MCP": "2026-12-10", "최근": "2026-12-09"}
many = t.update_keywords({}, [f"k{i}" for i in range(15)], d, [], max_n=10)
assert len(many) == 10

# 약점 태그: 가장 적게 푼 태그, 응답에 없는 태그는 0문제로 본다
t.get_json = lambda url: {"items": [{"tag": {"key": "dp"}, "solved": 3}, {"tag": {"key": "bfs"}, "solved": 1}]}
assert t.weakest_tag("me", ["dp", "bfs"]) == "bfs"
assert t.weakest_tag("me", ["dp", "bfs", "kmp"]) == "kmp"
calls = []
t.get_json = lambda url: (calls.append(url), {"items": [{"problemId": 1000, "titleKo": "A+B"}]})[1] if "search" in url \
    else {"items": [{"tag": {"key": "dp"}, "solved": 0}]}
p = t.recommend_problem("none", "me", "s3..g4", ["dp", "bfs"])
assert p["reason"] == "weak" and p["tag"] in ("dp", "bfs") and "-%40me" in calls[0]
p = t.recommend_problem("hashing", "", "s3..g4", ["dp"])
assert p == {"id": 1000, "title": "A+B", "tag": "hashing", "reason": "linked"} and "%40" not in calls[1]

# 알림: 웹훅이 없으면 아무것도 안 한다
t.notify(d, {"concepts": []}, None)

# README 블록 치환은 마커 사이만 바꾼다
text = "앞\n<!-- TODAY:START -->\n옛날\n<!-- TODAY:END -->\n뒤"
assert t.replace_block(text, "새것") == "앞\n<!-- TODAY:START -->\n새것\n<!-- TODAY:END -->\n뒤"

# main() 전체 흐름: 외부 호출은 가짜로 바꾸고 임시 폴더에서 실행
fake_result = {
    "news": [{"index": 0, "one_line": "캐시 장애 사례"}, {"index": 99, "one_line": "범위 밖 번호는 버림"}],
    "concepts": [
        {"name": "배열과 연결 리스트", "subject": "자료구조", "from_news": False, "news_index": -1,
         "explanation": "줄1\n줄2\n줄3", "interview_question": "차이는?"},
        {"name": "캐시 스탬피드", "subject": "백엔드", "from_news": True, "news_index": 0,
         "explanation": "줄1\n줄2\n줄3", "interview_question": "막는 법은?"},
    ],
    "tag": "hashing",
    "trending_keywords": ["캐시", "Redis"],
}
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copy(t.ROOT / "README.md", tmp / "README.md")
    (tmp / "notes").mkdir()
    (tmp / "solutions").mkdir()
    today = datetime.now(t.KST).date()
    (tmp / "notes" / f"{date.fromordinal(today.toordinal() - 1)}.md").write_text("subject: 운영체제, 네트워크\n", encoding="utf-8")
    yesterday = str(date.fromordinal(today.toordinal() - 1))
    t.ROOT, t.HISTORY_FILE, t.KEYWORDS_FILE = tmp, tmp / "data" / "history.json", tmp / "data" / "keywords.json"
    t.save_json(t.HISTORY_FILE, {yesterday: {"concepts": C("어제 개념"), "problem": P(42)}})
    t.save_json(t.KEYWORDS_FILE, {"MCP": yesterday})
    searched = []
    t.fetch_news = lambda kws: (searched.extend(kws), news)[1]
    t.analyze = lambda ns, c, tags: (fake_result, {"model": "m", "input_tokens": 1, "output_tokens": 2})
    t.recommend_problem = lambda tag, h, tier, tags: {"id": 1920, "title": "수 찾기", "tag": tag, "reason": "linked"}
    t.main()

    assert "MCP" in searched  # 어제 뜬 키워드로 오늘 검색
    assert set(t.load_json(t.KEYWORDS_FILE, {})) == {"MCP", "캐시", "Redis"} - set(t.CONFIG["fields"][t.CONFIG["field"]])
    assert (tmp / "concepts.md").read_text(encoding="utf-8").count("어제 개념") == 1

    daily = (tmp / "daily" / f"{today}.md").read_text(encoding="utf-8")
    assert "BOJ 1920 수 찾기" in daily and "캐시 스탬피드" in daily and "범위 밖" not in daily
    assert "https://a.com/1" in daily and "연속 기록: 1일" in daily
    assert "복습할 개념" in daily and "어제 개념" in daily and "밀린 문제 1개" in daily and "BOJ 42" in daily
    readme = (tmp / "README.md").read_text(encoding="utf-8")
    assert "아직 첫 실행 전" not in readme and "| 운영체제 |" in readme and "## 설정" in readme
    assert json.loads(t.HISTORY_FILE.read_text(encoding="utf-8"))[str(today)]["problem"]["id"] == 1920
finally:
    shutil.rmtree(tmp)

print("all checks passed")
