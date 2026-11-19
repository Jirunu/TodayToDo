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
KEYWORDS_FILE = ROOT / "data" / "keywords.json"
MODEL = "claude-opus-5-5"
UA = "TodayToDo/1.0"
REVIEW_OFFSETS = (1, 7, 30)  # 간격 반복: 1일, 7일, 30일 전 개념 복습
REASON = {"linked": "오늘 개념과 연결", "weak": "내 약점 태그", "random": "랜덤 태그"}


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


def update_keywords(dynamic, new, today, base, max_n=10, ttl_days=7):
    """뉴스에서 뜬 용어를 다음 날 검색어에 추가. ttl_days 동안 다시 안 나오면 빠진다."""
    kept = {k: v for k, v in dynamic.items() if today - date.fromisoformat(v) <= timedelta(days=ttl_days)}
    for k in new:
        k = k.strip()
        if 0 < len(k) <= 20 and k not in base:
            kept[k] = str(today)
    return dict(sorted(kept.items(), key=lambda kv: kv[1], reverse=True)[:max_n])


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
        "required": ["news", "concepts", "tag", "trending_keywords"],
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
            "trending_keywords": {"type": "array", "items": {"type": "string"}},
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
4. trending_keywords: 여러 뉴스에 반복해서 나온 기술 용어 최대 3개 (예: "MCP", "HBM"). 한 단어 위주로 짧게.
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
    usage = {"model": resp.model, "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    return json.loads(next(b.text for b in resp.content if b.type == "text")), usage


def valid_index(i, news):
    return 0 <= i < len(news)


# ---------- ② Coding ----------
def weakest_tag(handle, tags):
    """config의 태그 중 내가 가장 적게 푼 태그. 동률이면 그중 무작위."""
    # shortcut: 응답 첫 페이지만 읽음. 페이지가 나뉘어 오면 page 파라미터로 전부 읽도록 교체
    url = "https://solved.ac/api/v3/user/problem_tag_stats?" + urllib.parse.urlencode({"handle": handle})
    solved = {it["tag"]["key"]: it["solved"] for it in get_json(url).get("items", [])}
    low = min(solved.get(t, 0) for t in tags)
    return random.choice([t for t in tags if solved.get(t, 0) == low])


def recommend_problem(tag, handle, tier, tags):
    reason = "linked"
    if tag == "none":
        reason, tag = "random", random.choice(tags)
        if handle:
            try:
                tag, reason = weakest_tag(handle, tags), "weak"
            except Exception as e:
                print(f"약점 태그 조회 실패, 랜덤 태그 사용: {e}", file=sys.stderr)
    query = f"#{tag} *{tier} s#500.." + (f" -@{handle}" if handle else "")
    url = "https://solved.ac/api/v3/search/problem?" + urllib.parse.urlencode({"query": query, "sort": "random"})
    items = get_json(url).get("items", [])
    if not items:
        return None
    p = items[0]
    return {"id": p["problemId"], "title": p["titleKo"], "tag": tag, "reason": reason}


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


def review_concepts(history, today):
    out = []
    for off in REVIEW_OFFSETS:
        d = str(today - timedelta(days=off))
        if d in history:
            out.append((off, d, [c["name"] for c in history[d]["concepts"]]))
    return out


def subject_counts():
    c = Counter()
    for f in (ROOT / "notes").glob("20??-??-??.md"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("subject:"):
                c.update(s.strip() for s in line.split(":", 1)[1].split(",") if s.strip())
    return c


# ---------- 렌더링 ----------
def boj(p):
    return f"[BOJ {p['id']} {p['title']}](https://www.acmicpc.net/problem/{p['id']})"


def problem_line(p):
    if not p:
        return "- (오늘은 추천 문제를 가져오지 못했습니다)"
    return f"- {boj(p)} `#{p['tag']}` ({REASON.get(p.get('reason'), '')})"


def render_daily(day, news, result, problem, pending, reviews, cur_streak):
    lines = [f"# {day} TodayToDo", "", "## ① 오늘의 CS", ""]
    for c in result["concepts"]:
        badge = "📰 뉴스에서" if c["from_news"] else "📚 커리큘럼"
        lines += [f"### {c['name']} ({c['subject']}) · {badge}", ""]
        lines += [f"- {l.strip()}" for l in c["explanation"].splitlines() if l.strip()]
        lines += ["", f"> 💬 면접 질문: {c['interview_question']}"]
        if valid_index(c["news_index"], news):
            n = news[c["news_index"]]
            lines += [">", f"> 🔗 관련 뉴스: [{n['title']}]({n['link']})"]
        lines.append("")
    if reviews:
        lines += ["**🔁 복습할 개념**", ""]
        lines += [f"- {off}일 전 ([{d}]({d}.md)): {', '.join(names)}" for off, d, names in reviews]
        lines.append("")
    lines += ["## ② 오늘의 문제", "", problem_line(problem), ""]
    if pending:
        lines += [f"**밀린 문제 {len(pending)}개**", ""] + [f"- {d}: {boj(p)}" for d, p in pending] + [""]
    lines += ["## ③ 오늘의 뉴스", ""]
    for n in result["news"]:
        if valid_index(n["index"], news):
            item = news[n["index"]]
            lines.append(f"- [{item['title']}]({item['link']}) — {n['one_line']}")
    lines += ["", "## ④ 오늘의 기록", "", f"- 🔥 연속 기록: {cur_streak}일",
              f"- 공부한 내용은 `notes/{day}.md`에, 풀이는 `solutions/BOJ_번호.확장자`로 커밋하세요.", ""]
    return "\n".join(lines)


def render_archive(history):
    counts = Counter(c["name"] for v in history.values() for c in v["concepts"])
    lines = ["# 개념 아카이브", "", f"지금까지 공부한 개념 {len(counts)}개 (×N은 다시 나온 횟수)", "",
             "| 날짜 | 개념 | 과목 |", "|---|---|---|"]
    for d, v in sorted(history.items(), reverse=True):
        for c in v["concepts"]:
            again = f" ×{counts[c['name']]}" if counts[c["name"]] > 1 else ""
            lines.append(f"| [{d}](daily/{d}.md) | {c['name']}{again} | {c['subject']} |")
    return "\n".join(lines) + "\n"


def render_weekly(history, solved, dates, today):
    """오늘 이전 7일(지난주 월~일)을 정리. 파일 이름은 그 주의 ISO 주차."""
    start, end = today - timedelta(days=7), today - timedelta(days=1)
    week = {k: v for k, v in sorted(history.items()) if start <= date.fromisoformat(k) <= end}
    probs = [p for v in week.values() if (p := v.get("problem"))]
    done = [p for p in probs if p["id"] in solved]
    notes = [d for d in dates if start <= d <= end]
    kws = Counter(k for v in week.values() for k in v.get("keywords_added", []))
    tok_in = sum(v.get("usage", {}).get("input_tokens", 0) for v in week.values())
    tok_out = sum(v.get("usage", {}).get("output_tokens", 0) for v in week.values())
    year, wk, _ = start.isocalendar()
    title = f"{year}-W{wk:02d}"
    lines = [f"# {title} 주간 리포트 ({start} ~ {end})", "",
             f"- 📝 노트 {len(notes)}/7일 · ✅ 풀이 {len(done)}/{len(probs)}문제", ""]
    lines += ["## 이번 주 개념", ""] + [f"- {k}: {', '.join(c['name'] for c in v['concepts'])}" for k, v in week.items()]
    lines += ["", "## 문제", ""] + [f"- {'✅' if p in done else '⬜'} {boj(p)} `#{p['tag']}`" for p in probs]
    if kws:
        lines += ["", "## 뜬 키워드", "", ", ".join(k for k, _ in kws.most_common())]
    lines += ["", f"<sub>LLM 토큰: 입력 {tok_in:,} · 출력 {tok_out:,}</sub>", ""]
    return title, "\n".join(lines)


def render_readme_block(day, problem, cur_streak, counts, total_notes):
    lines = [f"**오늘 ({day})** → [daily/{day}.md](daily/{day}.md) · [개념 아카이브](concepts.md) · [주간 리포트](weekly/)", "",
             problem_line(problem), "", f"🔥 연속 {cur_streak}일 · 📝 누적 노트 {total_notes}개", ""]
    if counts:
        top = max(counts.values())
        lines += ["| 과목 | 학습량 |", "|---|---|"]
        lines += [f"| {s} | {'█' * max(1, round(n / top * 20))} {n} |" for s, n in counts.most_common()]
    return "\n".join(lines)


def replace_block(text, block, start="<!-- TODAY:START -->", end="<!-- TODAY:END -->"):
    return re.sub(f"{start}.*?{end}", lambda _: f"{start}\n{block}\n{end}", text, flags=re.S)


# ---------- 알림 ----------
def notify(day, result, problem):
    """DISCORD_WEBHOOK_URL이 있으면 오늘의 요약을 보낸다. 실패해도 하루 작업은 계속."""
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    lines = [f"**{day} TodayToDo**"] + [f"📚 {c['name']} ({c['subject']})" for c in result["concepts"]]
    if problem:
        lines.append(f"🧩 BOJ {problem['id']} {problem['title']} https://www.acmicpc.net/problem/{problem['id']}")
    if repo:
        lines.append(f"https://github.com/{repo}/blob/main/daily/{day}.md")
    req = urllib.request.Request(url, data=json.dumps({"content": "\n".join(lines)[:1900]}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"디스코드 알림 실패: {e}", file=sys.stderr)


def main():
    today = datetime.now(KST).date()
    base = CONFIG["fields"][CONFIG["field"]]
    dynamic = load_json(KEYWORDS_FILE, {})
    news = fetch_news(base + [k for k in dynamic if k not in base])
    if not news:
        sys.exit("뉴스를 한 건도 가져오지 못했습니다")
    result, usage = analyze(news[:150], curriculum_concept(today), CONFIG["tags"])
    dynamic = update_keywords(dynamic, result["trending_keywords"], today, base)
    save_json(KEYWORDS_FILE, dynamic)

    try:
        problem = recommend_problem(result["tag"], CONFIG["solvedac_handle"], CONFIG["tier"], CONFIG["tags"])
    except Exception as e:  # 문제 추천이 실패해도 오늘의 CS·뉴스는 남긴다
        print(f"문제 추천 실패: {e}", file=sys.stderr)
        problem = None

    history = load_json(HISTORY_FILE, {})
    history[str(today)] = {
        "concepts": [{"name": c["name"], "subject": c["subject"]} for c in result["concepts"]],
        "problem": problem,
        "keywords_added": [k for k in result["trending_keywords"] if k.strip() in dynamic],
        "usage": usage,
    }
    save_json(HISTORY_FILE, history)

    dates, solved = note_dates(), solved_ids()
    cur_streak = streak(dates, today)
    (ROOT / "daily").mkdir(exist_ok=True)
    (ROOT / "daily" / f"{today}.md").write_text(
        render_daily(today, news, result, problem, pending_problems(history, solved, today),
                     review_concepts(history, today), cur_streak), encoding="utf-8")
    (ROOT / "concepts.md").write_text(render_archive(history), encoding="utf-8")
    if today.weekday() == 0:  # 월요일 아침에 지난주 리포트
        title, text = render_weekly(history, solved, dates, today)
        (ROOT / "weekly").mkdir(exist_ok=True)
        (ROOT / "weekly" / f"{title}.md").write_text(text, encoding="utf-8")

    readme = ROOT / "README.md"
    readme.write_text(replace_block(readme.read_text(encoding="utf-8"),
                                    render_readme_block(today, problem, cur_streak, subject_counts(), len(dates))), encoding="utf-8")
    notify(today, result, problem)
    print(f"done: daily/{today}.md")


if __name__ == "__main__":
    main()
