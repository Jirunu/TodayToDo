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
hist = {"2026-12-08": {"problem": {"id": 1, "title": "a", "tag": "dp", "linked": True}},
        "2026-12-09": {"problem": {"id": 2, "title": "b", "tag": "dp", "linked": True}},
        "2026-12-10": {"problem": {"id": 3, "title": "c", "tag": "dp", "linked": True}},
        "2026-12-07": {"problem": None}}
assert [p["id"] for _, p in t.pending_problems(hist, {2}, d)] == [1]

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
}
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copy(t.ROOT / "README.md", tmp / "README.md")
    (tmp / "notes").mkdir()
    (tmp / "solutions").mkdir()
    today = datetime.now(t.KST).date()
    (tmp / "notes" / f"{date.fromordinal(today.toordinal() - 1)}.md").write_text("subject: 운영체제, 네트워크\n", encoding="utf-8")
    t.ROOT, t.HISTORY_FILE = tmp, tmp / "data" / "history.json"
    t.fetch_news = lambda kws: news
    t.analyze = lambda ns, c, tags: fake_result
    t.recommend_problem = lambda tag, h, tier, tags: {"id": 1920, "title": "수 찾기", "tag": tag, "linked": True}
    t.main()

    daily = (tmp / "daily" / f"{today}.md").read_text(encoding="utf-8")
    assert "BOJ 1920 수 찾기" in daily and "캐시 스탬피드" in daily and "범위 밖" not in daily
    assert "https://a.com/1" in daily and "연속 기록: 1일" in daily
    readme = (tmp / "README.md").read_text(encoding="utf-8")
    assert "아직 첫 실행 전" not in readme and "| 운영체제 |" in readme and "## 설정" in readme
    assert json.loads(t.HISTORY_FILE.read_text(encoding="utf-8"))[str(today)]["problem"]["id"] == 1920
finally:
    shutil.rmtree(tmp)

print("all checks passed")
