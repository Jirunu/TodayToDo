"""TodayToDo: 매일 기술 뉴스(GeekNews, Hacker News) -> 오늘의 CS 개념 -> 백준 문제 추천 -> daily/ + data/ + README 갱신."""
import html
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).parent
KST = timezone(timedelta(hours=9))
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
# 개념마다 핵심 3줄·면접 질문·퀴즈·연결 태그가 들어 있어 API 키 없이도 하루를 채울 수 있다
CONFIG["curriculum"] = json.loads((ROOT / "curriculum.json").read_text(encoding="utf-8"))
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
    # 태그 자리를 공백으로 바꿔 "</li><li>"처럼 붙은 문장이 이어 붙지 않게 한다
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


# ---------- ③ News ----------
# GeekNews: robots.txt가 RSS 수집과 AI 입력(ai-input=yes)을 허용. Hacker News: 공식 API(MIT).
GEEKNEWS_FEED = "https://news.hada.io/rss/news"
HN_API = "https://hacker-news.firebaseio.com/v0/"
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def get_bytes(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
        return r.read()


def parse_geeknews(raw):
    root = ET.fromstring(raw)
    return [{"title": clean(e.findtext("a:title", "", ATOM)),
             "desc": clean(e.findtext("a:content", "", ATOM))[:300],
             "link": e.findtext("a:id", "", ATOM).strip(),
             "source": "GeekNews"} for e in root.findall("a:entry", ATOM)]


def fetch_geeknews():
    return parse_geeknews(get_bytes(GEEKNEWS_FEED))


def hn_story(it):
    if not it or it.get("type") != "story" or not it.get("title") or it.get("dead") or it.get("deleted"):
        return None
    return {"title": clean(it["title"]),
            "desc": f"Hacker News {it.get('score', 0)}점 · 댓글 {it.get('descendants', 0)}개",
            "link": it.get("url") or f"https://news.ycombinator.com/item?id={it['id']}",
            "source": "Hacker News"}


def fetch_hn(limit=60):
    ids = get_json(HN_API + "topstories.json")[:limit]
    with ThreadPoolExecutor(8) as ex:
        items = ex.map(lambda i: get_json(f"{HN_API}item/{i}.json"), ids)
        return [s for s in map(hn_story, items) if s]


def dedupe(items):
    seen, out = set(), []
    for it in items:
        if it["link"] and it["link"] not in seen:
            seen.add(it["link"])
            out.append(it)
    return out


def rank(items, keywords):
    """관심 키워드가 많이 들어간 글을 앞으로. 동점이면 원래 순서(인기·최신순) 유지."""
    # 영문 키워드는 영문·숫자 경계로 ("AI"가 "said"에 안 걸리고 "Redis와"에는 걸리게), 한글은 부분 일치
    pats = [re.compile(rf"(?<![a-z0-9]){re.escape(k.lower())}(?![a-z0-9])") if k.isascii() else re.compile(re.escape(k))
            for k in keywords]
    return sorted(items, key=lambda n: -sum(bool(p.search(f"{n['title']} {n['desc']}".lower())) for p in pats))


def fetch_news(keywords):
    items = []
    for name, fetch in (("GeekNews", fetch_geeknews), ("Hacker News", fetch_hn)):
        try:
            items += fetch()
        except Exception as e:  # 한 곳이 실패해도 나머지로 진행. 전부 실패하면 main에서 멈춘다
            print(f"뉴스 수집 실패 ({name}): {e}", file=sys.stderr)
    return rank(dedupe(items), keywords)


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


def recent_concepts(history, today, days=30):
    return list(dict.fromkeys(c["name"] for k, v in sorted(history.items())
                              if today - timedelta(days=days) <= date.fromisoformat(k) < today for c in v["concepts"]))


def analyze(news, concept, tags, recent):
    """LLM은 뉴스 '번호'와 정해진 태그 목록 안에서만 고른다. 링크·문제번호를 지어낼 수 없게."""
    import anthropic

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["news", "concepts", "tag", "trending_keywords", "quiz"],
        "properties": {
            "news": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["index", "one_line"],
                "properties": {"index": {"type": "integer"}, "one_line": {"type": "string"}}}},
            "concepts": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "subject", "from_news", "news_index", "explanation", "interview_question", "related"],
                "properties": {
                    "name": {"type": "string"}, "subject": {"type": "string"},
                    "from_news": {"type": "boolean"}, "news_index": {"type": "integer"},
                    "explanation": {"type": "string"}, "interview_question": {"type": "string"},
                    "related": {"type": "array", "items": {"type": "string"}}}}},
            "tag": {"type": "string", "enum": tags + ["none"]},
            "trending_keywords": {"type": "array", "items": {"type": "string"}},
            "quiz": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["question", "answer", "why"],
                "properties": {"question": {"type": "string"}, "answer": {"type": "string"}, "why": {"type": "string"}}}},
        },
    }
    news_text = "\n".join(f"[{i}] ({n['source']}) {n['title']} — {n['desc']}" for i, n in enumerate(news))
    recent_text = ", ".join(recent) if recent else "(없음)"
    prompt = f"""너는 취업 준비 중인 개발자의 CS 공부 코치다. 관심 분야는 "{CONFIG['field']}"이다.
아래는 오늘 GeekNews와 Hacker News에서 수집한 기술 뉴스 목록이다 (영어 제목도 있다).

{news_text}

최근 30일 동안 이미 공부한 개념: {recent_text}

다음을 모두 한국어로 만들어라.
1. news: 관심 분야 개발자가 볼 만한 핫한 뉴스 5개. index는 위 목록 번호, one_line은 무슨 내용이고 왜 중요한지 한 줄.
2. concepts: 정확히 2개.
   - 첫째는 오늘의 커리큘럼 개념 "{concept['name']}" (subject "{concept['subject']}", from_news false). 관련 뉴스가 있으면 news_index에 번호, 없으면 -1.
   - 둘째는 뉴스에서 뽑은 공부할 만한 CS 개념 (from_news true, news_index는 근거 뉴스 번호). 최근 공부한 개념과 겹치지 않게.
   - explanation은 핵심 3줄(줄바꿈 구분), interview_question은 실제 면접에서 나올 질문 1개.
   - related는 '최근 공부한 개념' 목록에 있는 이름 중 이 개념과 직접 관련된 것만 그대로 적는다 (최대 3개, 없으면 빈 배열).
3. tag: 두 개념 중 하나와 '자연스럽게' 이어지는 solved.ac 알고리즘 태그. 억지로 연결해야 하면 "none".
4. trending_keywords: 여러 뉴스에 반복해서 나온 기술 용어 최대 3개 (예: "MCP", "HBM"). 한 단어 위주로 짧게.
5. quiz: 오늘 두 개념으로 확인 문제 3개. 한 줄 단답이나 O/X로 답할 수 있게. why는 정답 이유 한 줄.
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


def basic_result(news, concept):
    """API 키가 없을 때: 내장 커리큘럼 설명과 관심 키워드 상위 뉴스로 analyze()와 같은 모양을 만든다."""
    # 출처별로 번갈아 고른다 (관심 키워드 순으로 정렬된 상태라 각 출처의 상위 글이 뽑힌다)
    by_source = {}
    for i, n in enumerate(news):
        by_source.setdefault(n["source"], []).append(i)
    picks = [i for group in zip_longest(*by_source.values()) for i in group if i is not None][:5]
    return {
        "news": [{"index": i, "one_line": news[i]["desc"][:120]} for i in picks],
        "concepts": [{"name": concept["name"], "subject": concept["subject"], "from_news": False, "news_index": -1,
                      "explanation": "\n".join(concept["points"]), "interview_question": concept["question"], "related": []}],
        "tag": concept["tag"],
        "trending_keywords": [],
        "quiz": [concept["quiz"]],
    }


def valid_index(i, news):
    return 0 <= i < len(news)


# ---------- ② Coding ----------
def tag_solved_counts(handle, max_pages=20):
    """solved.ac 태그별 푼 문제 수. 응답이 30개씩 페이지로 나뉘어 오므로 count만큼 전부 읽는다."""
    solved, page = {}, 1
    while page <= max_pages:
        url = "https://solved.ac/api/v3/user/problem_tag_stats?" + urllib.parse.urlencode({"handle": handle, "page": page})
        data = get_json(url)
        items = data.get("items", [])
        solved.update({it["tag"]["key"]: it["solved"] for it in items})
        if not items or len(solved) >= data.get("count", 0):
            break
        page += 1
    return solved


def weakest_tags(handle, tags):
    """config의 태그를 내가 적게 푼 순서로. 동률끼리는 무작위로 섞는다."""
    solved = tag_solved_counts(handle)
    return sorted(random.sample(tags, len(tags)), key=lambda t: solved.get(t, 0))


def solved_on_boj(handle, ids, chunk=40):
    """추천했던 문제 중 백준에서 실제로 푼 것. solutions/에 파일을 안 올려도 풀었음으로 잡힌다."""
    solved, ids = set(), sorted(set(ids))
    for i in range(0, len(ids), chunk):
        group = "|".join(f"id:{p}" for p in ids[i:i + chunk])
        url = "https://solved.ac/api/v3/search/problem?" + urllib.parse.urlencode({"query": f"({group}) s@{handle}"})
        solved |= {p["problemId"] for p in get_json(url).get("items", [])}
    return solved


def search_problem(tag, handle, tier):
    query = f"#{tag} *{tier} s#500.." + (f" -s@{handle}" if handle else "")
    url = "https://solved.ac/api/v3/search/problem?" + urllib.parse.urlencode({"query": query, "sort": "random"})
    items = get_json(url).get("items", [])
    return items[0] if items else None


def recommend_problem(tag, handle, tier, tags, tries=5):
    """개념과 이어지는 태그 → 없으면 약점 태그 순서로 → 그 난이도에 문제가 없으면 다음 태그로."""
    if tag != "none":
        candidates = [(tag, "linked")]
    else:
        order, reason = random.sample(tags, len(tags)), "random"
        if handle:
            try:
                order, reason = weakest_tags(handle, tags), "weak"
            except Exception as e:
                print(f"약점 태그 조회 실패, 랜덤 태그 사용: {e}", file=sys.stderr)
        candidates = [(t, reason) for t in order[:tries]]
    for t, reason in candidates:
        if p := search_problem(t, handle, tier):
            return {"id": p["problemId"], "title": p["titleKo"], "tag": t, "reason": reason}
    return None


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


def news_ref(item):
    return {"title": item["title"], "link": item["link"], "source": item["source"]}


def daily_data(day, news, result, problem, pending, reviews, cur_streak):
    """하루치 결과를 웹 페이지(data/daily/날짜.json)와 마크다운이 같이 쓰는 형태로 정리."""
    return {
        "date": str(day),
        "streak": cur_streak,
        "concepts": [{
            "name": c["name"], "subject": c["subject"], "from_news": c["from_news"],
            "explanation": [l.strip() for l in c["explanation"].splitlines() if l.strip()],
            "interview_question": c["interview_question"],
            "news": news_ref(news[c["news_index"]]) if valid_index(c["news_index"], news) else None,
        } for c in result["concepts"]],
        "quiz": result.get("quiz", []),
        "reviews": [{"offset": off, "date": d, "names": names} for off, d, names in reviews],
        "problem": problem,
        "pending": [{"date": d, "problem": p} for d, p in pending],
        "news": [{**news_ref(news[n["index"]]), "one_line": n["one_line"]} for n in result["news"] if valid_index(n["index"], news)],
    }


def render_daily(data):
    day = data["date"]
    lines = [f"# {day} TodayToDo", "", "## ① 오늘의 CS", ""]
    for c in data["concepts"]:
        badge = "📰 뉴스에서" if c["from_news"] else "📚 커리큘럼"
        lines += [f"### {c['name']} ({c['subject']}) · {badge}", ""]
        lines += [f"- {l}" for l in c["explanation"]]
        lines += ["", f"> 💬 면접 질문: {c['interview_question']}"]
        if c["news"]:
            lines += [">", f"> 🔗 관련 뉴스 ({c['news']['source']}): [{c['news']['title']}]({c['news']['link']})"]
        lines.append("")
    if data["reviews"]:
        lines += ["**🔁 복습할 개념**", ""]
        lines += [f"- {r['offset']}일 전 ([{r['date']}]({r['date']}.md)): {', '.join(r['names'])}" for r in data["reviews"]]
        lines.append("")
    if data["quiz"]:
        lines += ["**🧠 확인 퀴즈**", ""]
        for i, q in enumerate(data["quiz"], 1):
            lines += [f"{i}. {q['question']}", f"<details><summary>정답</summary>{q['answer']} — {q['why']}</details>", ""]
    lines += ["## ② 오늘의 문제", "", problem_line(data["problem"]), ""]
    if data["pending"]:
        lines += [f"**밀린 문제 {len(data['pending'])}개**", ""] + [f"- {x['date']}: {boj(x['problem'])}" for x in data["pending"]] + [""]
    lines += ["## ③ 오늘의 뉴스", ""]
    lines += [f"- [{n['title']}]({n['link']}) `{n['source']}` — {n['one_line']}" for n in data["news"]]
    lines += ["", "## ④ 오늘의 기록", "", f"- 🔥 연속 기록: {data['streak']}일",
              f"- 공부한 내용은 `notes/{day}.md`에, 풀이는 `solutions/BOJ_번호.확장자`로 커밋하세요.", ""]
    return "\n".join(lines)


def graph_mermaid(history, limit=60):
    """최근 개념 limit개를 과목별로 묶고, LLM이 고른 관련 개념끼리 잇는 Mermaid 그래프 본문."""
    entries = [(c["name"], c["subject"], c.get("related", [])) for _, v in sorted(history.items()) for c in v["concepts"]]
    names = list(dict.fromkeys(n for n, _, _ in entries))[-limit:]
    ids = {n: f"n{i}" for i, n in enumerate(names)}
    subject = {n: s for n, s, _ in entries}
    edges = sorted({tuple(sorted((n, r))) for n, _, rel in entries for r in rel if n in ids and r in ids and r != n})
    lines = ["graph LR"]
    for si, s in enumerate(sorted({subject[n] for n in names})):
        lines.append(f'  subgraph s{si} ["{s.replace(chr(34), chr(39))}"]')
        lines += [f'    {ids[n]}["{n.replace(chr(34), chr(39))}"]' for n in names if subject[n] == s]
        lines.append("  end")
    lines += [f"  {ids[a]} --- {ids[b]}" for a, b in edges]
    return "\n".join(lines)


def render_graph(history, limit=60):
    return f"```mermaid\n{graph_mermaid(history, limit)}\n```"


def render_heatmap(history, dates, solved, today, weeks=20):
    """노트를 쓴 날 +1, 그날 추천 문제를 푼 날 +1. GitHub 잔디처럼 월요일부터 세로로 7칸."""
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    colors = ["#ebedf0", "#9be9a8", "#30a14e"]
    cells = []
    for i in range((today - start).days + 1):
        d = start + timedelta(days=i)
        p = history.get(str(d), {}).get("problem")
        level = (d in dates) + bool(p and p["id"] in solved)
        cells.append(f'<rect x="{i // 7 * 14}" y="{i % 7 * 14 + 4}" width="11" height="11" rx="2" fill="{colors[level]}"><title>{d}</title></rect>')
    w = weeks * 14
    legend = "".join(f'<rect x="{w - 70 + j * 14}" y="108" width="11" height="11" rx="2" fill="{c}"/>' for j, c in enumerate(colors))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="124" font-family="sans-serif" font-size="10">'
            f'<rect width="100%" height="100%" fill="#ffffff"/>{"".join(cells)}{legend}'
            f'<text x="{w - 74}" y="117" fill="#57606a" text-anchor="end">적음</text>'
            f'<text x="{w - 28}" y="117" fill="#57606a">많음</text></svg>\n')


def render_archive(history):
    counts = Counter(c["name"] for v in history.values() for c in v["concepts"])
    lines = ["# 개념 아카이브", "", f"지금까지 공부한 개념 {len(counts)}개 (×N은 다시 나온 횟수)", "",
             "## 개념 연결 그래프", "", render_graph(history), "", "## 전체 목록", "",
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
             problem_line(problem), "", f"🔥 연속 {cur_streak}일 · 📝 누적 노트 {total_notes}개", "",
             "![공부 잔디](assets/heatmap.svg)", ""]
    if counts:
        top = max(counts.values())
        lines += ["| 과목 | 학습량 |", "|---|---|"]
        lines += [f"| {s} | {'█' * max(1, round(n / top * 20))} {n} |" for s, n in counts.most_common()]
    return "\n".join(lines)


def site_data(history, dates, solved, today, cur_streak):
    """github.io 페이지(index.html)가 처음에 읽는 목차와 통계."""
    recommended = {p["id"] for v in history.values() if (p := v.get("problem"))}
    return {
        "updated": str(today),
        "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        "field": CONFIG["field"],
        "stats": {"streak": cur_streak, "notes": len(dates), "solved": len(recommended & solved),
                  "concepts": len({c["name"] for v in history.values() for c in v["concepts"]})},
        "notes": sorted(str(d) for d in dates),
        "solved": sorted(solved),
        "weeks": sorted((f.stem for f in (ROOT / "weekly").glob("*.md")), reverse=True),
        "history": {k: {"concepts": [{"name": c["name"], "subject": c["subject"]} for c in v["concepts"]],
                        "problem": v.get("problem")} for k, v in sorted(history.items(), reverse=True)},
        "graph": graph_mermaid(history),
    }


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
    if "/" in repo:
        owner, name = repo.split("/", 1)
        lines.append(f"https://{owner.lower()}.github.io/{name}/#/day/{day}")
    req = urllib.request.Request(url, data=json.dumps({"content": "\n".join(lines)[:1900]}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"디스코드 알림 실패: {e}", file=sys.stderr)


def check_setup():
    """실행 전에 빠진 설정을 찾아, Actions 로그 첫 줄에서 바로 원인이 보이게 한다."""
    problems = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("참고: ANTHROPIC_API_KEY가 없어 기본 모드(내장 커리큘럼)로 실행합니다. "
              "Settings → Secrets and variables → Actions에 등록하면 뉴스에서 뽑은 개념이 추가됩니다.", file=sys.stderr)
    if CONFIG["field"] not in CONFIG["fields"]:
        problems.append(f"config.json의 field \"{CONFIG['field']}\"가 fields에 없습니다. 가능한 값: {', '.join(CONFIG['fields'])}")
    if not CONFIG["solvedac_handle"]:
        print("참고: config.json의 solvedac_handle이 비어 있어서 이미 푼 문제를 거르지 못하고 약점 태그도 쓰지 않습니다.", file=sys.stderr)
    if problems:
        sys.exit("설정이 필요합니다:\n- " + "\n- ".join(problems))


def main():
    check_setup()
    today = datetime.now(KST).date()
    base = CONFIG["fields"][CONFIG["field"]]
    dynamic = load_json(KEYWORDS_FILE, {})
    news = fetch_news(base + [k for k in dynamic if k not in base])
    if not news:
        sys.exit("뉴스를 한 건도 가져오지 못했습니다")
    history = load_json(HISTORY_FILE, {})
    recent = recent_concepts(history, today)
    concept = curriculum_concept(today)
    mode = "ai" if os.environ.get("ANTHROPIC_API_KEY") else "basic"
    if mode == "ai":
        result, usage = analyze(news[:150], concept, CONFIG["tags"], recent)
        if result["tag"] == "none":
            result["tag"] = concept["tag"]  # LLM이 연결을 못 찾으면 커리큘럼에 정해 둔 태그
    else:
        result, usage = basic_result(news, concept), {}
    dynamic = update_keywords(dynamic, result["trending_keywords"], today, base)
    save_json(KEYWORDS_FILE, dynamic)

    try:
        problem = recommend_problem(result["tag"], CONFIG["solvedac_handle"], CONFIG["tier"], CONFIG["tags"])
    except Exception as e:  # 문제 추천이 실패해도 오늘의 CS·뉴스는 남긴다
        print(f"문제 추천 실패: {e}", file=sys.stderr)
        problem = None

    history[str(today)] = {
        "concepts": [{"name": c["name"], "subject": c["subject"],
                      "related": [r for r in c["related"] if r in recent]}  # 목록 밖 이름은 버린다
                     for c in result["concepts"]],
        "problem": problem,
        "keywords_added": [k for k in result["trending_keywords"] if k.strip() in dynamic],
        "usage": usage,
    }
    save_json(HISTORY_FILE, history)

    dates, solved = note_dates(), solved_ids()
    if CONFIG["solvedac_handle"]:
        recommended = [p["id"] for v in history.values() if (p := v.get("problem"))]
        try:
            solved |= solved_on_boj(CONFIG["solvedac_handle"], recommended)
        except Exception as e:  # solved.ac가 안 되면 solutions/ 파일만으로 판단
            print(f"solved.ac 풀이 기록 조회 실패: {e}", file=sys.stderr)
    cur_streak = streak(dates, today)
    data = daily_data(today, news, result, problem, pending_problems(history, solved, today),
                      review_concepts(history, today), cur_streak)
    data["mode"] = mode
    (ROOT / "daily").mkdir(exist_ok=True)
    (ROOT / "daily" / f"{today}.md").write_text(render_daily(data), encoding="utf-8")
    (ROOT / "data" / "daily").mkdir(parents=True, exist_ok=True)
    save_json(ROOT / "data" / "daily" / f"{today}.json", data)
    (ROOT / "concepts.md").write_text(render_archive(history), encoding="utf-8")
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "heatmap.svg").write_text(render_heatmap(history, dates, solved, today), encoding="utf-8")
    if today.weekday() == 0:  # 월요일 아침에 지난주 리포트
        title, text = render_weekly(history, solved, dates, today)
        (ROOT / "weekly").mkdir(exist_ok=True)
        (ROOT / "weekly" / f"{title}.md").write_text(text, encoding="utf-8")

    save_json(ROOT / "data" / "site.json", site_data(history, dates, solved, today, cur_streak))

    readme = ROOT / "README.md"
    readme.write_text(replace_block(readme.read_text(encoding="utf-8"),
                                    render_readme_block(today, problem, cur_streak, subject_counts(), len(dates))), encoding="utf-8")
    notify(today, result, problem)
    print(f"done: daily/{today}.md")


if __name__ == "__main__":
    main()
