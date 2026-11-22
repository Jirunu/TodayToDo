"""네트워크 없이 도는 자가 점검: python test_todaytodo.py"""
import json
import os
import urllib.parse
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

import todaytodo as t

# GeekNews Atom 파싱: 태그 제거, 엔티티 복원, utm 없는 id를 링크로
atom = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
<entry><title>&lt;b&gt;Redis&lt;/b&gt; 장애 &amp;amp; 복구</title>
<link rel='alternate' href='https://news.hada.io/topic?id=1&amp;utm_source=x'/>
<id>https://news.hada.io/topic?id=1</id><content type='html'>&lt;p&gt;캐시 &lt;b&gt;서버&lt;/b&gt;&lt;/p&gt;</content></entry>
</feed>""".encode()
gn = t.parse_geeknews(atom)
assert gn == [{"title": "Redis 장애 & 복구", "desc": "캐시 서버", "link": "https://news.hada.io/topic?id=1", "source": "GeekNews"}]

# 태그 사이 문장이 붙지 않게
assert t.clean("<ul><li>첫 문장임</li><li>둘째 문장</li></ul>") == "첫 문장임 둘째 문장"

# 기본 모드 뉴스: 출처를 번갈아 최대 5개
mixed = [{"title": f"{s}{i}", "desc": "d", "link": f"{s}{i}", "source": s} for s in ("GeekNews", "Hacker News") for i in range(4)]
assert [mixed[n["index"]]["title"] for n in t.basic_result(mixed, t.CONFIG["curriculum"][0])["news"]] == \
    ["GeekNews0", "Hacker News0", "GeekNews1", "Hacker News1", "GeekNews2"]

# Hacker News: 스토리만, 링크 없으면 HN 글 주소
assert t.hn_story({"id": 7, "type": "story", "title": "Show HN: x &amp; y", "score": 10, "descendants": 3}) == {
    "title": "Show HN: x & y", "desc": "Hacker News 10점 · 댓글 3개", "link": "https://news.ycombinator.com/item?id=7", "source": "Hacker News"}
assert t.hn_story({"id": 8, "type": "job", "title": "hiring"}) is None
assert t.hn_story({"id": 9, "type": "story", "title": "x", "dead": True}) is None
assert t.hn_story(None) is None

# 중복 제거와 관심 키워드 정렬 (영문은 단어 단위, 동점은 원래 순서)
def N(title, link, desc=""):
    return {"title": title, "desc": desc, "link": link, "source": "GeekNews"}
news = t.dedupe([N("Redis 장애 & 복구", "https://a.com/1"), N("중복", "https://a.com/1"), N("빈 링크", "")])
assert [n["title"] for n in news] == ["Redis 장애 & 복구"]
ranked = t.rank([N("He said hi", "1"), N("Kafka 운영기", "2"), N("새 AI 모델", "3"), N("Redis와 Kafka", "4")], ["AI", "Kafka", "Redis"])
assert [n["link"] for n in ranked] == ["4", "2", "3", "1"]

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

# 태그 통계: 30개씩 나뉜 페이지를 count만큼 전부 읽는다
pages = {1: [("dp", 3), ("bfs", 1)], 2: [("math", 9)]}
def fake_stats(url):
    page = int(url.split("page=")[1])
    return {"count": 3, "items": [{"tag": {"key": k}, "solved": s} for k, s in pages.get(page, [])]}
t.get_json = fake_stats
assert t.tag_solved_counts("me") == {"dp": 3, "bfs": 1, "math": 9}

# 약점 태그 순서: 적게 푼 순, 응답에 없는 태그는 0문제
assert t.weakest_tags("me", ["dp", "bfs", "math", "kmp"]) == ["kmp", "bfs", "dp", "math"]

# 문제 추천: 약점 태그에 맞는 문제가 없으면 다음 태그로
calls = []
def fake_api(url):
    if "problem_tag_stats" in url:
        return fake_stats(url)
    calls.append(url)
    return {"items": [] if "%23kmp" in url else [{"problemId": 1000, "titleKo": "A+B"}]}
t.get_json = fake_api
p = t.recommend_problem("none", "me", "s3..g4", ["dp", "bfs", "math", "kmp"])
assert p == {"id": 1000, "title": "A+B", "tag": "bfs", "reason": "weak"} and "-s%40me" in calls[0] and "%23kmp" in calls[0]
calls.clear()
p = t.recommend_problem("hashing", "", "s3..g4", ["dp"])
assert p == {"id": 1000, "title": "A+B", "tag": "hashing", "reason": "linked"} and "%40" not in calls[0]
t.get_json = lambda url: {"count": 0, "items": []}
assert t.recommend_problem("hashing", "me", "s3..g4", ["dp"]) is None

# 백준에서 푼 추천 문제: id를 묶어서 묻고, 많으면 나눠서 묻는다
asked = []
def fake_solved(url):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]
    asked.append(q)
    return {"items": [{"problemId": p} for p in (1000, 2257) if f"id:{p}" in q]}
t.get_json = fake_solved
assert t.solved_on_boj("me", [2257, 1000, 4889, 1000], chunk=2) == {1000, 2257}
assert asked == ["(id:1000|id:2257) s@me", "(id:4889) s@me"]

# 알림: 웹훅이 없으면 아무것도 안 한다
t.notify(d, {"concepts": []}, None)

# 최근 개념: 30일 전(포함)부터 어제까지, 중복 없이
assert t.recent_concepts(hist, d) == ["스레드", "캐시", "스케줄링", "데드락", "페이징"]
assert t.recent_concepts(hist, d, days=29) == ["캐시", "스케줄링", "데드락", "페이징"]

# 개념 그래프: 과목별 묶음, 관련 개념끼리 한 번만 연결, 따옴표는 안전하게
g = t.render_graph({"2026-12-01": {"concepts": [{"name": "데드락", "subject": "운영체제", "related": []}]},
                    "2026-12-02": {"concepts": [{"name": '뮤텍스 "락"', "subject": "운영체제", "related": ["데드락", "없는개념"]},
                                                {"name": "트랜잭션", "subject": "DB", "related": ['뮤텍스 "락"']}]},
                    "2026-12-03": {"concepts": [{"name": "데드락", "subject": "운영체제", "related": ['뮤텍스 "락"']}]}})
assert g.startswith("```mermaid") and g.count("subgraph") == 2 and "뮤텍스 '락'" in g
assert g.count(" --- ") == 2 and "없는개념" not in g

# 잔디: 노트 +1, 그날 문제 풀이 +1, 미래 칸은 없음
svg = t.render_heatmap({"2026-12-09": {"problem": P(2)}, "2026-12-08": {"problem": P(1)}},
                       {date(2026, 12, 9), date(2026, 12, 7)}, {2}, d, weeks=2)
assert svg.count("<title>") == 7 + 4  # 지난주 월~일 + 이번 주 월~목
assert svg.count('fill="#30a14e"><title>2026-12-09') == 1 and 'fill="#9be9a8"><title>2026-12-07' in svg
assert 'fill="#ebedf0"><title>2026-12-08' in svg  # 노트 없고 문제도 안 풂

# 뉴스: 한 곳이 실패해도 나머지는 가져온다
def boom():
    raise OSError("boom")
t.fetch_geeknews, real_hn = boom, t.fetch_hn
t.fetch_hn = lambda: [N("Kafka 이야기", "https://h/1"), N("other", "https://h/2")]
assert [n["link"] for n in t.fetch_news(["Kafka"])] == ["https://h/1", "https://h/2"]

# README 블록 치환은 마커 사이만 바꾼다
text = "앞\n<!-- TODAY:START -->\n옛날\n<!-- TODAY:END -->\n뒤"
assert t.replace_block(text, "새것") == "앞\n<!-- TODAY:START -->\n새것\n<!-- TODAY:END -->\n뒤"

# main() 전체 흐름: 외부 호출은 가짜로 바꾸고 임시 폴더에서 실행
fake_result = {
    "news": [{"index": 0, "one_line": "캐시 장애 사례"}, {"index": 99, "one_line": "범위 밖 번호는 버림"}],
    "concepts": [
        {"name": "배열과 연결 리스트", "subject": "자료구조", "from_news": False, "news_index": -1,
         "explanation": "줄1\n줄2\n줄3", "interview_question": "차이는?", "related": []},
        {"name": "캐시 스탬피드", "subject": "백엔드", "from_news": True, "news_index": 0,
         "explanation": "줄1\n줄2\n줄3", "interview_question": "막는 법은?", "related": ["어제 개념", "지어낸 개념"]},
    ],
    "tag": "hashing",
    "trending_keywords": ["캐시", "Redis"],
    "quiz": [{"question": "해시 충돌 해결법 두 가지는?", "answer": "체이닝, 개방 주소법", "why": "버킷 연결 또는 빈 칸 탐색"}],
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
    seen_recent = []
    t.analyze = lambda ns, c, tags, recent: (seen_recent.extend(recent), (fake_result, {"model": "m", "input_tokens": 1, "output_tokens": 2}))[1]
    t.recommend_problem = lambda tag, h, tier, tags: {"id": 1920, "title": "수 찾기", "tag": tag, "reason": "linked"}
    os.environ.setdefault("ANTHROPIC_API_KEY", "test")
    t.main()

    assert "MCP" in searched  # 어제 뜬 키워드로 오늘 검색
    assert set(t.load_json(t.KEYWORDS_FILE, {})) == {"MCP", "캐시", "Redis"} - set(t.CONFIG["fields"][t.CONFIG["field"]])
    assert (tmp / "concepts.md").read_text(encoding="utf-8").count("| 어제 개념 |") == 1  # 표에 한 줄

    daily = (tmp / "daily" / f"{today}.md").read_text(encoding="utf-8")
    assert "BOJ 1920 수 찾기" in daily and "캐시 스탬피드" in daily and "범위 밖" not in daily
    assert "https://a.com/1" in daily and "연속 기록: 1일" in daily
    assert "복습할 개념" in daily and "어제 개념" in daily and "밀린 문제 1개" in daily and "BOJ 42" in daily
    assert "확인 퀴즈" in daily and "<summary>정답</summary>체이닝" in daily
    assert seen_recent == ["어제 개념"]
    saved = t.load_json(t.HISTORY_FILE, {})[str(today)]["concepts"][1]["related"]
    assert saved == ["어제 개념"]  # LLM이 지어낸 이름은 버림
    assert "```mermaid" in (tmp / "concepts.md").read_text(encoding="utf-8")
    assert (tmp / "assets" / "heatmap.svg").read_text(encoding="utf-8").startswith("<svg")
    site = t.load_json(tmp / "data" / "site.json", {})
    assert list(site["history"]) == [str(today), yesterday] and site["history"][yesterday]["concepts"][0]["name"] == "어제 개념"
    assert site["notes"] == [yesterday] and site["stats"] == {"streak": 1, "notes": 1, "solved": 0, "concepts": 3}
    assert site["graph"].startswith("graph LR") and site["updated"] == str(today)
    dj = t.load_json(tmp / "data" / "daily" / f"{today}.json", {})
    assert dj["concepts"][1]["news"] == {"title": "Redis 장애 & 복구", "link": "https://a.com/1", "source": "GeekNews"}
    assert dj["concepts"][0]["news"] is None and dj["concepts"][0]["explanation"] == ["줄1", "줄2", "줄3"]
    assert [n["one_line"] for n in dj["news"]] == ["캐시 장애 사례"] and dj["pending"][0]["problem"]["id"] == 42
    assert dj["reviews"] == [{"offset": 1, "date": yesterday, "names": ["어제 개념"]}]
    readme = (tmp / "README.md").read_text(encoding="utf-8")
    assert "아직 첫 실행 전" not in readme and "| 운영체제 |" in readme and "## 설정" in readme
    assert json.loads(t.HISTORY_FILE.read_text(encoding="utf-8"))[str(today)]["problem"]["id"] == 1920
finally:
    shutil.rmtree(tmp)

print("all checks passed")

# 커리큘럼: 모든 개념에 설명 3줄·면접 질문·퀴즈가 있고, 태그는 config 목록 안에서만
for c in t.CONFIG["curriculum"]:
    assert len(c["points"]) == 3 and c["question"] and set(c["quiz"]) == {"question", "answer", "why"}, c["name"]
    assert c["tag"] == "none" or c["tag"] in t.CONFIG["tags"], c["name"]

# 설정 점검: 분야 설정이 틀리면 멈추고, 키가 없으면 멈추지 않는다 (기본 모드)
saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
t.check_setup()
t.CONFIG["field"], real_field = "없는분야", t.CONFIG["field"]
try:
    t.check_setup()
    raise AssertionError("틀린 분야인데 통과함")
except SystemExit as e:
    assert "없는분야" in str(e)
finally:
    t.CONFIG["field"] = real_field

# 기본 모드: 키 없이 main()이 내장 커리큘럼으로 하루를 채운다
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copy(Path(__file__).parent / "README.md", tmp / "README.md")
    (tmp / "notes").mkdir()
    (tmp / "solutions").mkdir()
    t.ROOT, t.HISTORY_FILE, t.KEYWORDS_FILE = tmp, tmp / "data" / "history.json", tmp / "data" / "keywords.json"
    t.analyze = lambda *a: (_ for _ in ()).throw(AssertionError("키가 없는데 LLM을 부름"))
    picked = []
    t.recommend_problem = lambda tag, h, tier, tags: (picked.append(tag), {"id": 1000, "title": "A+B", "tag": tag, "reason": "linked"})[1]
    t.main()
    today = datetime.now(t.KST).date()
    concept = t.curriculum_concept(today)
    dj = t.load_json(tmp / "data" / "daily" / f"{today}.json", {})
    assert dj["mode"] == "basic" and dj["concepts"][0]["name"] == concept["name"]
    assert dj["concepts"][0]["explanation"] == concept["points"] and dj["quiz"] == [concept["quiz"]]
    assert picked == [concept["tag"]] and len(dj["news"]) == 1
    assert t.load_json(t.HISTORY_FILE, {})[str(today)]["usage"] == {}
    print("basic mode passed")

    # 같은 날 다시 실행: 뉴스·문제는 그대로 두고 노트·연속 기록만 갱신
    (tmp / "notes" / f"{today}.md").write_text("subject: 자료구조\n", encoding="utf-8")
    t.fetch_news = lambda kws: (_ for _ in ()).throw(AssertionError("갱신인데 뉴스를 다시 모음"))
    t.recommend_problem = lambda *a: (_ for _ in ()).throw(AssertionError("갱신인데 문제를 다시 고름"))
    t.main()
    again = t.load_json(tmp / "data" / "daily" / f"{today}.json", {})
    assert again["streak"] == 1 and again["concepts"] == dj["concepts"] and again["news"] == dj["news"]
    site = t.load_json(tmp / "data" / "site.json", {})
    assert site["notes"] == [str(today)] and site["stats"]["streak"] == 1
    print("refresh passed")
finally:
    shutil.rmtree(tmp)
    if saved_key is not None:
        os.environ["ANTHROPIC_API_KEY"] = saved_key
