"""TodayToDo: 매일 IT 뉴스 -> 오늘의 CS 개념 -> 백준 문제 추천 -> daily/날짜.md + README 갱신."""
import html
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
KST = timezone(timedelta(hours=9))
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
HISTORY_FILE = ROOT / "data" / "history.json"
MODEL = "claude-opus-5-5"


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "TodayToDo/1.0", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


# ---------- ③ News ----------
def dedupe(items):
    seen, out = set(), []
    for it in items:
        link = it.get("originallink") or it["link"]
        if link in seen:
            continue
        seen.add(link)
        out.append({"title": clean(it["title"]), "desc": clean(it["description"]), "link": link})
    return out


def fetch_news(keywords, per_keyword=20):
    headers = {
        "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
    }
    items = []
    for kw in keywords:
        q = urllib.parse.urlencode({"query": kw, "display": per_keyword, "sort": "date"})
        items += get_json(f"https://openapi.naver.com/v1/search/news.json?{q}", headers)["items"]
    return dedupe(items)


# ---------- ① CS ----------
def curriculum_concept(day):
    cur = CONFIG["curriculum"]
    return cur[(day - date.fromisoformat(CONFIG["start_date"])).days % len(cur)]


def analyze(news, concept, tags):
    """LLM은 뉴스 '번호'와 정해진 태그 목록 안에서만 고른다. 링크·문제번호를 지어낼 수 없게."""
    import anthropic

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["news", "concepts", "tag"],
        "properties": {
            "news": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["index", "one_line"],
                "properties": {"index": {"type": "integer"}, "one_line": {"type": "string"}}}},
            "concepts": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "subject", "from_news", "news_index", "explanation", "interview_question"],
                "properties": {
                    "name": {"type": "string"}, "subject": {"type": "string"},
                    "from_news": {"type": "boolean"}, "news_index": {"type": "integer"},
                    "explanation": {"type": "string"}, "interview_question": {"type": "string"}}}},
            "tag": {"type": "string", "enum": tags + ["none"]},
        },
    }
    news_text = "\n".join(f"[{i}] {n['title']} — {n['desc']}" for i, n in enumerate(news))
    prompt = f"""너는 취업 준비 중인 백엔드 개발자의 CS 공부 코치다. 아래는 오늘 수집한 IT 뉴스 목록이다.

{news_text}

다음을 한국어로 만들어라.
1. news: 개발자가 볼 만한 핫한 뉴스 5개. index는 위 목록 번호, one_line은 왜 중요한지 한 줄.
2. concepts: 정확히 2개.
   - 첫째는 오늘의 커리큘럼 개념 "{concept['name']}" (subject "{concept['subject']}", from_news false). 관련 뉴스가 있으면 news_index에 번호, 없으면 -1.
   - 둘째는 뉴스에서 뽑은 공부할 만한 CS 개념 (from_news true, news_index는 근거 뉴스 번호).
   - explanation은 핵심 3줄(줄바꿈 구분), interview_question은 실제 면접에서 나올 질문 1개.
3. tag: 두 개념 중 하나와 '자연스럽게' 이어지는 solved.ac 알고리즘 태그. 억지로 연결해야 하면 "none".
"""
    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason != "end_turn":
        sys.exit(f"LLM 응답 실패: stop_reason={resp.stop_reason}")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def valid_index(i, news):
    return 0 <= i < len(news)


# ---------- ② Coding ----------
def recommend_problem(tag, handle, tier, tags):
    linked = tag != "none"
    if not linked:
        # shortcut: 약점 태그 대신 무작위 태그. solved.ac 사용자 태그 통계 연동 시 교체
        tag = random.choice(tags)
    query = f"#{tag} *{tier} s#500.." + (f" -@{handle}" if handle else "")
    url = "https://solved.ac/api/v3/search/problem?" + urllib.parse.urlencode({"query": query, "sort": "random"})
    items = get_json(url).get("items", [])
    if not items:
        return None
    p = items[0]
    return {"id": p["problemId"], "title": p["titleKo"], "tag": tag, "linked": linked}


# ---------- ④ Commit 기록 ----------
def solved_ids():
    return {int(m.group(1)) for f in (ROOT / "solutions").glob("*") if (m := re.search(r"BOJ_(\d+)", f.name))}


def note_dates():
    return {date.fromisoformat(f.stem) for f in (ROOT / "notes").glob("20??-??-??.md")}


def streak(dates, today):
    d = today if today in dates else today - timedelta(days=1)
    n = 0
    while d in dates:
        n, d = n + 1, d - timedelta(days=1)
    return n


def pending_problems(history, solved, today, days=14):
    out = []
    for k, v in sorted(history.items()):
        p = v.get("problem")
        if p and p["id"] not in solved and today - timedelta(days=days) <= date.fromisoformat(k) < today:
            out.append((k, p))
    return out


def subject_counts():
    c = Counter()
    for f in (ROOT / "notes").glob("20??-??-??.md"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("subject:"):
                c.update(s.strip() for s in line.split(":", 1)[1].split(",") if s.strip())
    return c


# ---------- 렌더링 ----------
def problem_line(p):
    if not p:
        return "- (오늘은 추천 문제를 가져오지 못했습니다)"
    why = "오늘 개념과 연결" if p["linked"] else "연결되는 개념이 없어 랜덤 태그"
    return f"- [BOJ {p['id']} {p['title']}](https://www.acmicpc.net/problem/{p['id']}) `#{p['tag']}` ({why})"


def render_daily(day, news, result, problem, pending, cur_streak):
    lines = [f"# {day} TodayToDo", "", "## ① 오늘의 CS", ""]
    for c in result["concepts"]:
        badge = "📰 뉴스에서" if c["from_news"] else "📚 커리큘럼"
        lines += [f"### {c['name']} ({c['subject']}) · {badge}", ""]
        lines += [f"- {l.strip()}" for l in c["explanation"].splitlines() if l.strip()]
        lines += ["", f"> 💬 면접 질문: {c['interview_question']}"]
        if valid_index(c["news_index"], news):
            n = news[c["news_index"]]
            lines += [f">", f"> 🔗 관련 뉴스: [{n['title']}]({n['link']})"]
        lines.append("")
    lines += ["## ② 오늘의 문제", "", problem_line(problem), ""]
    if pending:
        lines += [f"**밀린 문제 {len(pending)}개**", ""] + [f"- {d}: [BOJ {p['id']} {p['title']}](https://www.acmicpc.net/problem/{p['id']})" for d, p in pending] + [""]
    lines += ["## ③ 오늘의 뉴스", ""]
    for n in result["news"]:
        if valid_index(n["index"], news):
            item = news[n["index"]]
            lines.append(f"- [{item['title']}]({item['link']}) — {n['one_line']}")
    lines += ["", "## ④ 오늘의 기록", "", f"- 🔥 연속 기록: {cur_streak}일",
              f"- 공부한 내용은 `notes/{day}.md`에, 풀이는 `solutions/BOJ_번호.확장자`로 커밋하세요.", ""]
    return "\n".join(lines)


def render_readme_block(day, problem, cur_streak, counts, total_notes):
    lines = [f"**오늘 ({day})** → [daily/{day}.md](daily/{day}.md)", "", problem_line(problem), "",
             f"🔥 연속 {cur_streak}일 · 📝 누적 노트 {total_notes}개", ""]
    if counts:
        top = max(counts.values())
        lines += ["| 과목 | 학습량 |", "|---|---|"]
        lines += [f"| {s} | {'█' * max(1, round(n / top * 20))} {n} |" for s, n in counts.most_common()]
    return "\n".join(lines)


def replace_block(text, block, start="<!-- TODAY:START -->", end="<!-- TODAY:END -->"):
    return re.sub(f"{start}.*?{end}", lambda _: f"{start}\n{block}\n{end}", text, flags=re.S)


def main():
    today = datetime.now(KST).date()
    news = fetch_news(CONFIG["fields"][CONFIG["field"]])
    if not news:
        sys.exit("뉴스를 한 건도 가져오지 못했습니다")
    result = analyze(news[:150], curriculum_concept(today), CONFIG["tags"])

    try:
        problem = recommend_problem(result["tag"], CONFIG["solvedac_handle"], CONFIG["tier"], CONFIG["tags"])
    except Exception as e:  # 문제 추천이 실패해도 오늘의 CS·뉴스는 남긴다
        print(f"문제 추천 실패: {e}", file=sys.stderr)
        problem = None

    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else {}
    history[str(today)] = {"concepts": [c["name"] for c in result["concepts"]], "problem": problem}
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    dates = note_dates()
    cur_streak = streak(dates, today)
    pending = pending_problems(history, solved_ids(), today)
    (ROOT / "daily").mkdir(exist_ok=True)
    (ROOT / "daily" / f"{today}.md").write_text(render_daily(today, news, result, problem, pending, cur_streak), encoding="utf-8")

    readme = ROOT / "README.md"
    readme.write_text(replace_block(readme.read_text(encoding="utf-8"),
                                    render_readme_block(today, problem, cur_streak, subject_counts(), len(dates))), encoding="utf-8")
    print(f"done: daily/{today}.md")


if __name__ == "__main__":
    main()
