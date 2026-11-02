"""Social listening pipeline for the Fieldnote Apparel worked example (keeploop issue #2).

  python -X utf8 listen.py collect [reddit|appstore|wiki]   crawl public data into the sandbox (resumable)
  python -X utf8 listen.py analyze                          read the sandbox, write data/metrics.json + data/quotes.json
  python -X utf8 listen.py selfcheck                        assert-based check on a tiny fixture

Raw data lives OUTSIDE the repo (SANDBOX). Author names are replaced by a salted hash at collection
time; the salt stays in the sandbox and is never committed. Methods: data/README.md.
"""
import calendar, collections, hashlib, html, json, math, os, random, re, secrets, sys, tempfile, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SANDBOX = Path(os.environ.get("KLM_SANDBOX") or Path(tempfile.gettempdir()) / "keeploop-mr-social")
UA = "keeploop-marketing-research-example/1.0 (academic worked example, github.com keeploop issue 2; polite 1 req/s)"
ARCTIC = "https://arctic-shift.photon-reddit.com/api/"
DELAY = 1.1
WINDOW = ("2025-11-01", "2026-11-01")  # [lo, hi)
LO = calendar.timegm(time.strptime(WINDOW[0], "%Y-%m-%d"))
HI = calendar.timegm(time.strptime(WINDOW[1], "%Y-%m-%d"))

# ---------------------------------------------------------------- configuration (collection)
BRAND_SUBS = ["Aritzia", "shein", "uniqlo", "BrandyMelville", "OldNavy", "lululemon"]
GENERAL_SUBS = ["femalefashionadvice", "malefashionadvice", "OUTFITS", "PetiteFashionAdvice", "femalefashion",
                "FrugalFemaleFashion", "PlusSizeFashion", "findfashion", "frugalmalefashion", "CanadaFashion"]
SEARCH_TERMS = ["aritzia", "zara", "h&m", "shein", "uniqlo", "forever 21", "abercrombie", "lululemon",
                "old navy", "urban outfitters", "brandy melville", "temu"]
THREAD_TERMS = ["recommend"]  # time-boxed run: 'where' and 'brands' were scanned for femalefashionadvice and malefashionadvice only
CAPS = {  # items per slice; every cap is recorded in the manifest
    "brand_sub_posts_per_month": 125, "brand_sub_comments_per_month": 250,
    "keyword_posts_per_sub_term_half": 100, "keyword_comments_per_sub_term_half": 200,
    "thread_title_hits_per_sub_term_half": 100, "threads_total": 60, "comments_per_thread": 300,
}
APPS = {"Aritzia": "aritzia", "Zara": "zara", "H&M": "h&m", "Shein": "shein", "Uniqlo": "uniqlo"}
WIKI = {"Aritzia": "Aritzia", "Zara": "Zara_(retailer)", "H&M": "H%26M", "Shein": "Shein", "Uniqlo": "Uniqlo",
        "Temu": "Temu", "Forever 21": "Forever_21", "Lululemon": "Lululemon_Athletica", "Old Navy": "Old_Navy",
        "Gap": "Gap_Inc.", "Brandy Melville": "Brandy_Melville"}
ASK_RE = re.compile(r"where (do|can|should|to)|where.{0,40}(shop|buy|find|get)|recommend|\brecs?\b|favou?rite (brand|store|shop|place)s?|"
                    r"best (brand|store|shop|place|website)s?|(brands|stores|shops|places|websites|retailers) (for|to|like|that|you)|"
                    r"suggest|alternatives? (to|for)|what brands?|any (good )?(brands|stores)", re.I)
SHOP_RE = re.compile(r"brand|store|shop|buy|clothes|clothing|retailer|website|wardrobe|jeans|dress|coat|jacket|basics|staples|"
                     r"pants|trousers|shirts?|\btops?\b|sweaters?|boots|shoes", re.I)

# ---------------------------------------------------------------- brand dictionary
# mode: ci = case-insensitive; cap = exact case; ctx = exact case AND a fashion word in the same sentence
# AND previous word not a determiner ("my garage", "a mango"). Ambiguous words (gap, garage, mango, cos, simons) are ctx.
BRANDS = {
    "Aritzia": [(r"\baritzia\b", "ci")],
    "Zara": [(r"\bzara\b", "ci")],
    "H&M": [(r"\bH ?& ?M\b|\bH ?&amp; ?M\b|\bH and M\b", "cap"), (r"\bHM\b", "ctx")],
    "Shein": [(r"\bshein\b", "ci")],
    "Uniqlo": [(r"\buniqlo\b", "ci")],
    "Forever 21": [(r"\bforever ?21\b|\bf21\b", "ci")],
    "Garage": [(r"\bGarage\b", "ctx")],
    "Abercrombie": [(r"\babercrombie\b", "ci"), (r"\bA&F\b", "cap")],
    "Lululemon": [(r"\blululemon\b", "ci")],
    "Old Navy": [(r"\bold navy\b", "ci")],
    "Gap": [(r"\bGap\b", "ctx")],
    "Mango": [(r"\bMango\b", "ctx")],
    "Urban Outfitters": [(r"\burban outfitters\b", "ci"), (r"\bUO\b", "ctx")],
    "Brandy Melville": [(r"\bbrandy melville\b", "ci"), (r"\bBrandy\b", "ctx")],
    "Princess Polly": [(r"\bprincess polly\b", "ci")],
    "Temu": [(r"\btemu\b", "ci")],
    "Dynamite": [(r"\bDynamite\b", "ctx")],
    "Simons": [(r"\bSimons\b|\bLa Maison Simons\b", "ctx")],
    "Edikted": [(r"\bedikted\b", "ci")],
    "Hollister": [(r"\bhollister\b", "ci")],
    "American Eagle": [(r"\bamerican eagle\b", "ci"), (r"\bAE\b", "ctx")],
    "Free People": [(r"\bfree people\b", "ci")],
    "Everlane": [(r"\beverlane\b", "ci")],
    "COS": [(r"\bCOS\b", "ctx")],
    "Madewell": [(r"\bmadewell\b", "ci")],
    "Reformation": [(r"\bReformation\b", "ctx")],
}
CORE = ["Aritzia", "Zara", "H&M", "Shein", "Uniqlo"]
BRAND_RX = [(b, re.compile(p, re.I if m == "ci" else 0), m) for b, pats in BRANDS.items() for p, m in pats]
CTX_RE = re.compile(r"\b(jeans?|dress(es)?|tops?|shirts?|sweaters?|clothes|clothing|stores?|shop(s|ping)?|bought|buy|ordered|orders?|"
                    r"brands?|outfits?|haul|fits?|sizing|sizes?|pants|jackets?|coats?|skirts?|hoodies?|returns?|sale|mall|online|"
                    r"wear|wearing|collection|quality|cheap|affordable)\b", re.I)
DETERMINERS = {"my", "a", "an", "our", "your", "his", "her", "this", "that"}

# ---------------------------------------------------------------- attribute dictionary (sentence level, any match)
ATTRS = {
    "price/value": r"pric(e|es|ed|ey|ing)|expensive|cheap(er)?\b|afford|\bcost(s|ly)?\b|worth|\bvalue\b|budget|\$\d|\bsales?\b|discount|overpriced|bargain|\bdeals?\b|splurge",
    "quality/durability": r"quality|durab|well[- ]made|falls? apart|fell apart|pill(s|ed|ing)\b|shrunk|shrinks?\b|seams?\b|stitch|fabric|material|flimsy|cheaply made|holds? up|wear and tear|lasted|last(s)? (long|years|forever)|\bthin\b|see[- ]through",
    "fit/sizing": r"\bfit(s|ted|ting)?\b|\bsiz(e|es|ed|ing)\b|runs? (small|large|big|true)|\btts\b|petite|inseam|baggy|too tight|too (short|long)|length\b",
    "style/trend": r"\bstyle(s|d)?\b|stylish|trend(y|s|ing)?\b|\bcute\b|aesthetic|fashionable|\bchic\b|classic|design(s|er)?\b|versatile|basics?\b|gorgeous|pretty|elevated",
    "sustainability/ethics": r"sustainab|ethic(al|s)?\b|fast fashion|\beco\b|environment|\bwaste\b|labou?r|sweatshop|greenwash|recycl|organic|polyester|landfill|exploit|microplastic",
    "shipping/returns": r"\bship(s|ping|ped)?\b|deliver|\barriv|\breturn(s|ed|ing)?\b|refund|exchange|tracking|package|customs|\bduty\b|duties|tariff|delayed|\bdelay",
    "customer service": r"customer (service|care|support)|\bsupport\b|\brude\b|helpful|\bchat\b|complain|resolved|\bcs\b|contacted|called them|emailed (them|aritzia|zara|shein)",
    "store experience": r"in[- ]store|\bstores?\b|fitting rooms?|sales associate|\bstaff\b|\bmall\b|boutique|checkout line|\blocation\b|try (it|them|on) in",
}
ATTR_RX = {a: re.compile(p, re.I) for a, p in ATTRS.items()}
OWN_RX = re.compile(r"\b(?:i|we|i['’]ve|ive)\b[^.!?]{0,40}\b(?:bought|ordered|purchased|picked up|snagged|got|own|owned|returned)\b|"
                    r"\bmy\b[^.!?]{0,40}\bfrom\b|\bhaul\b|\b(?:ordered|bought|purchased|got)\b[^.!?]{0,30}\bfrom\b", re.I)

# ---------------------------------------------------------------- supplementary: funnel and brand-image dictionaries
INTENT_RX = re.compile(r"thinking (?:of|about) (?:buying|getting|ordering|trying)|should i (?:get|buy|order|try)|worth it|worth (?:the|buying)|"
                       r"\bconsidering\b|on my (?:wish ?list|list)|want to (?:buy|try|get)|planning (?:to|on) (?:buy|get|order)|debating (?:if|whether|getting|buying)", re.I)
ADV_RX = re.compile(r"highly recommend|would recommend|buy(?:ing)? again|bought again|always buy|keep buying|repurchase|go-to|obsessed with my", re.I)
FUNNEL = ["aware", "considering", "bought", "advocate"]


def funnel_sets(rows):
    """Nested author sets for one brand from its mention rows: advocate <= bought <= considering <= aware."""
    aware = {r["a"] for r in rows}
    own = {r["a"] for r in rows if r["own"]}
    adv = own & {r["a"] for r in rows if ADV_RX.search(r["s"])}
    bought = own | adv
    cons = {r["a"] for r in rows if INTENT_RX.search(r["s"])} | bought
    return {"aware": aware, "considering": cons, "bought": bought, "advocate": adv}


# Brand-image statements: neutral keyword lists, applied identically to every brand, pole pairs both present.
# valence: + favourable image, - unfavourable image, 0 neutral/descriptive (used only to label strengths/weaknesses).
IMAGES = {
    "premium/aspirational": (r"luxur|premium|high[- ]end|aspirational|investment piece|upscale|designer|splurge|fancy|looks? expensive|quiet luxury|polished|sophisticated|elevated", "+"),
    "basic/everyday": (r"\bbasics?\b|everyday|\bstaples?\b|workhorse|\bplain\b|\bsimple\b|neutrals?\b|capsule|essentials?\b", "0"),
    "trendy/fashion-forward": (r"\btrend(y|s|ing)\b|fashion[- ]forward|on[- ]trend|runway|latest (styles?|looks?|drops?)|new (collection|drop)|\bviral\b|tiktok|\bhype\b|cutting[- ]edge", "+"),
    "dated/frumpy": (r"\bdated\b|frumpy|\bboring\b|outdated|old[- ]fashioned|grandma|mumsy|stuffy|\bdrab\b|matronly|\bbland\b|old lady", "-"),
    "cheap/disposable": (r"\bcheap(ly)?\b|cheaply made|disposable|throwaway|one[- ]wear|ultra[- ]fast fashion|falls? apart|fell apart|flimsy|\bjunk\b|\btrash\b|low quality|poorly made|landfill", "-"),
    "comfortable": (r"\bcomfortable|\bcomfy\b|\bcozy\b|\bcosy\b|\bsoft(ness)?\b|stretchy|breathable|\bsnug\b", "+"),
    "uncomfortable": (r"uncomfortable|\bitchy\b|scratchy|\bstiff\b|restrictive|rough fabric|clammy|suffocat", "-"),
    "ethical/responsible": (r"\bethical(ly)?\b|sustainab|responsible|fair[- ]trade|fair wages?|b[- ]corp|transparen|recycled|organic|eco[- ]friendly|traceab|living wage", "+"),
    "unethical/exploitative": (r"unethical|exploit|sweatshop|child labou?r|forced labou?r|\bslave|greenwash|union[- ]bust|steals? (designs?|from)|stole (designs?|from)|plagiar|rip[- ]?off|overproduc", "-"),
    "reliable/consistent": (r"reliab|\bconsistent(ly)?\b|dependable|never (disappoints?|fails?|let me down)|trustworthy|holds? up|true to size|\btts\b|every time", "+"),
    "inconsistent/hit-or-miss": (r"inconsistent|hit[- ]or[- ]miss|hit and miss|unreliable|quality (has )?(dropped|declined|gone down)|gone downhill|\bvaries\b|\bvary\b|lottery|gamble|not what it used to be", "-"),
    "Canadian/local": (r"canad(a|ian)|made in canada|vancouver|toronto|montr[eé]al|homegrown|local(ly)? (brand|made|business)|small business", "0"),
    "fun/young": (r"\bfun\b|playful|youthful|\byoung\b|\bteen|gen ?z|college|quirky|bubbly|colou?rful|vibrant|girly|\by2k\b", "+"),
}
IMAGE_RX = {k: re.compile(p, re.I) for k, (p, _) in IMAGES.items()}
IMAGE_POLES = [("premium/aspirational", "cheap/disposable"), ("trendy/fashion-forward", "dated/frumpy"), ("comfortable", "uncomfortable"),
               ("ethical/responsible", "unethical/exploitative"), ("reliable/consistent", "inconsistent/hit-or-miss")]


def image_of(s):
    return [k for k, rx in IMAGE_RX.items() if rx.search(s)]


# ---------------------------------------------------------------- profiling cues
_NOUN = r"(?!\s*(?:lbs?|pounds?|kgs?|cm|%|inch(?:es)?|in\b|weeks?|months?|days?|mins?|minutes?|hours?|miles?|percent|dollars?|k\b|shoe|size|years? (?:in|into|of|ago)|yrs? (?:in|into|of)))"
AGE_RX = [
    re.compile(r"[\(\[]\s*(\d{2})\s?/?\s?([MFmf])\s*[\)\]]"),
    re.compile(r"\b(\d{2})\s?/?\s?([MF])\b(?![\w'’])"),
    re.compile(r"\b(\d{2})([mf])\b"),
    re.compile(r"\b[MF]\s?/\s?(\d{2})\b"),
    re.compile(r"\bi['’]?m\s+(\d{2})\b" + _NOUN, re.I),
    re.compile(r"\bi am\s+(\d{2})\b" + _NOUN, re.I),
    re.compile(r"\b(\d{2})\s?(?:y/?o|yo|yrs? old|years? old|year[- ]old)\b", re.I),
    re.compile(r"\bborn in (19[6-9]\d|200\d)\b", re.I),
]
GEN_RX = [
    (re.compile(r"[\(\[]\s*\d{2}\s?/?\s?([MFmf])\s*[\)\]]"), None), (re.compile(r"\b\d{2}\s?/?\s?([MF])\b(?![\w'’])"), None),
    (re.compile(r"\b\d{2}([mf])\b"), None), (re.compile(r"\b([MF])\s?/\s?\d{2}\b"), None),
    (re.compile(r"\b(?:i['’]?m|i am|as) an? (?:\d{2}[- ]?(?:year[- ]old|yo) )?(woman|girl|female|lady|man|guy|male|dude)\b", re.I), None),
]
GEN_MAP = {"f": "female", "woman": "female", "girl": "female", "female": "female", "lady": "female",
           "m": "male", "man": "male", "guy": "male", "male": "male", "dude": "male"}
CA_W = (r"canada|canadian|toronto|vancouver|montreal|montréal|ontario|alberta|calgary|ottawa|winnipeg|edmonton|halifax|"
        r"british columbia|quebec|québec|manitoba|saskatchewan|nova scotia|new brunswick|mississauga|victoria bc")
US_W = (r"usa|united states|america|california|texas|new york|nyc|florida|chicago|seattle|boston|los angeles|\bLA\b|"
        r"illinois|ohio|michigan|pennsylvania|georgia|virginia|colorado|arizona|oregon|washington state|minnesota|"
        r"massachusetts|new jersey|north carolina|tennessee|utah|nevada|wisconsin|missouri|indiana|philadelphia|houston|"
        r"dallas|atlanta|denver|portland|san francisco|brooklyn|the us|the u\.s\.|\bUS\b")
LOC = r"(?:i(?:['’]m| am)?|we)\s+(?:live|living|lived|moved|reside|am|from|based)?\s*(?:here )?(?:in|from|to)\s+(?:the )?"
CA_RX = re.compile(r"\b(?:" + LOC + r"(?:" + CA_W + r")|here in (?:" + CA_W + r")|as a canadian|i['’]?m (?:a )?canadian|canadian here)\b", re.I)
US_RX = re.compile(r"\b(?:" + LOC + r"(?:" + US_W + r")|here in (?:" + US_W + r")|as an american|i['’]?m (?:an )?american|american here)", re.I)


# ---------------------------------------------------------------- statistics helpers
def wilson(k, n, z=1.96):
    """Wilson score interval for a proportion k/n; returns (lo, hi) as fractions."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def net_sentiment(pos, neg, neu):
    """(pos - neg) / (pos + neg + neu)."""
    t = pos + neg + neu
    return (pos - neg) / t if t else None


def prop(k, n, base_name="n"):
    """Percent with Wilson 95% CI; 'base too small' when n < 30."""
    if n < 30:
        return {"k": k, "base": n, "pct": None, "status": "base too small"}
    lo, hi = wilson(k, n)
    return {"k": k, "base": n, "pct": round(100 * k / n, 1), "ci95": [round(100 * lo, 1), round(100 * hi, 1)]}


def sent_label(c):
    return "pos" if c >= 0.05 else "neg" if c <= -0.05 else "neu"


def sent_block(labels):
    """Net sentiment + Wilson CIs on pos/neg shares from a list of pos/neg/neu labels."""
    n = len(labels)
    c = collections.Counter(labels)
    if n < 30:
        return {"base": n, "status": "base too small"}
    ns = net_sentiment(c["pos"], c["neg"], c["neu"])
    return {"base": n, "net_sentiment": round(ns, 3), "pos": prop(c["pos"], n), "neg": prop(c["neg"], n),
            "neu_pct": round(100 * c["neu"] / n, 1)}


# ---------------------------------------------------------------- text helpers
def clean(t):
    t = html.unescape(t or "")
    t = re.sub(r"(?m)^\s*>.*$", "", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\b[ur]/\w+", "", t)
    t = re.sub(r"[*~`#^]+", "", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def sentences(t):
    """Yield (offset, sentence)."""
    pos = 0
    for s in re.split(r"(?<=[.!?])\s+|\n+", t):
        i = t.find(s, pos)
        pos = i + len(s) if i >= 0 else pos
        if s.strip():
            yield max(i, 0), s.strip()


def sentence_brands(s):
    """Brands mentioned in one sentence -> list of (position, brand)."""
    out = {}
    for b, rx, mode in BRAND_RX:
        for m in rx.finditer(s):
            if mode == "ctx":
                prev = re.findall(r"[A-Za-z']+", s[:m.start()])[-1:]
                prev = prev[0].lower() if prev else ""
                if prev in DETERMINERS or (b == "Garage" and prev in ("the", "in")) or not CTX_RE.search(s):
                    continue
            if b not in out or m.start() < out[b]:
                out[b] = m.start()
            break
    return sorted((p, b) for b, p in out.items())


def brand_hits(text):
    """All brand mentions in cleaned text -> list of (pos, brand, sentence)."""
    res = []
    for off, s in sentences(text):
        for p, b in sentence_brands(s):
            res.append((off + p, b, s))
    return res


def attrs_of(s):
    return [a for a, rx in ATTR_RX.items() if rx.search(s)]


def find_age(t):
    for rx in AGE_RX:
        for m in rx.finditer(t):
            a = int(m.group(1))
            if 14 <= a <= 65 or (rx is AGE_RX[-1] and 1961 <= a <= 2012):
                return 2026 - a if a > 1900 else a
    return None


def find_gender(t):
    for rx, _ in GEN_RX:
        m = rx.search(t)
        if m:
            return GEN_MAP.get(m.group(1).lower())
    return None


def find_country(t):
    ca, us = CA_RX.search(t), US_RX.search(t)
    return "Canada" if ca and not us else "US" if us and not ca else None


def generation(age):
    return None if age is None else "Gen Z (14-29)" if age <= 29 else "Millennial (30-45)" if age <= 45 else "Older (46+)"


def month_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")


# ================================================================ COLLECT
class Fail(Exception):
    pass


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as f:
        return json.loads(f.read().decode("utf-8"))


def api(path, params):
    url = ARCTIC + path + "?" + urllib.parse.urlencode(params)
    for i in range(3):  # short retries: server "Timeout" errors are transient; fetch() splits the window on persistent failure
        time.sleep(DELAY)
        try:
            j = http_json(url)
            if j.get("error"):
                raise ValueError(j["error"])
            return j["data"] or []
        except urllib.error.HTTPError as e:
            wait = 30 * (i + 1) if e.code == 429 else 3 * 2 ** i
        except Exception:
            wait = 3 * 2 ** i
        time.sleep(wait)
    raise Fail(url)


def pages(path, params, lo, hi, cap):
    out, seen, cur = [], set(), lo
    while len(out) < cap:
        d = api(path, dict(params, after=cur, before=hi, sort="asc", limit=100))
        new = [x for x in d if x["id"] not in seen]
        seen.update(x["id"] for x in new)
        out += new
        if len(d) < 100:
            break
        last = max(x["created_utc"] for x in d)
        cur = last if new else cur + 1
    return out[:cap]


def fetch(path, params, lo, hi, cap, fails):
    try:
        return pages(path, params, lo, hi, cap)
    except Fail:
        if hi - lo <= 14 * 86400:
            fails.append({"path": path, "params": params, "lo": lo, "hi": hi})
            return []
        mid = (lo + hi) // 2
        return fetch(path, params, lo, mid, cap // 2, fails) + fetch(path, params, mid, hi, cap // 2, fails)


def slices(n):
    if n == 12:
        pts = []
        y, m = 2025, 11
        for _ in range(13):
            pts.append(calendar.timegm((y, m, 1, 0, 0, 0)))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return list(zip(pts[:-1], pts[1:]))
    step = (HI - LO) // n
    return [(LO + i * step, LO + (i + 1) * step if i < n - 1 else HI) for i in range(n)]


class Store:
    """Sandbox writer: salted author hash, bots/deleted dropped, resumable task manifest."""

    def __init__(self):
        SANDBOX.mkdir(parents=True, exist_ok=True)
        sf = SANDBOX / "salt.txt"
        if not sf.exists():
            sf.write_text(secrets.token_hex(16))
        self.salt = sf.read_text().strip()
        mf = SANDBOX / "manifest.json"
        self.m = json.loads(mf.read_text("utf8")) if mf.exists() else {"tasks": {}, "threads": [], "failures": []}
        self.m.setdefault("started_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.m["caps"] = CAPS
        self.seen = set()
        for kind in ("post", "comment"):
            f = SANDBOX / f"reddit_{kind}s.jsonl"
            if f.exists():
                for line in f.open(encoding="utf8"):
                    self.seen.add((kind, json.loads(line)["id"]))

    def h(self, a):
        return hashlib.blake2b((self.salt + a).encode(), digest_size=6).hexdigest()

    def save(self):
        (SANDBOX / "manifest.json").write_text(json.dumps(self.m, indent=1), "utf8")

    def add(self, kind, rows, src):
        n = 0
        with (SANDBOX / f"reddit_{kind}s.jsonl").open("a", encoding="utf8") as f:
            for x in rows:
                a = x.get("author") or ""
                text = (x.get("title", "") + "\n" + x.get("selftext", "")).strip() if kind == "post" else x.get("body", "")
                if a in ("", "[deleted]", "AutoModerator") or text in ("[removed]", "[deleted]") or (kind, x["id"]) in self.seen:
                    continue
                self.seen.add((kind, x["id"]))
                f.write(json.dumps({"id": x["id"], "sub": x.get("subreddit"), "ts": x["created_utc"], "a": self.h(a),
                                    "text": text, "link": x.get("link_id"), "parent": x.get("parent_id"),
                                    "nc": x.get("num_comments"), "src": src}, ensure_ascii=False) + "\n")
                n += 1
        return n

    def task(self, tid, fn):
        if tid in self.m["tasks"]:
            return
        fails = []
        n = fn(fails)
        self.m["tasks"][tid] = {"items": n, "failed_windows": len(fails)}
        self.m["failures"] += fails
        self.save()
        print(tid, n, "fails", len(fails), flush=True)


def collect_reddit(st):
    P = "id,subreddit,created_utc,author,title,selftext,num_comments"
    C = "id,subreddit,created_utc,author,body,link_id,parent_id"
    for sub in BRAND_SUBS:
        def fn(fails, sub=sub):
            n = 0
            for lo, hi in slices(12):
                n += st.add("post", fetch("posts/search", {"subreddit": sub, "fields": P}, lo, hi, CAPS["brand_sub_posts_per_month"], fails), "brandsub")
                n += st.add("comment", fetch("comments/search", {"subreddit": sub, "fields": C}, lo, hi, CAPS["brand_sub_comments_per_month"], fails), "brandsub")
            return n
        st.task("brandsub:" + sub, fn)
    def kw(term):  # term-major order so every brand gets covered across subs before time runs out
        for sub in GENERAL_SUBS:
            def fn(fails, sub=sub, term=term):
                n = 0
                for lo, hi in slices(2):
                    n += st.add("post", fetch("posts/search", {"subreddit": sub, "query": term, "fields": P}, lo, hi, CAPS["keyword_posts_per_sub_term_half"], fails), "kw")
                    n += st.add("comment", fetch("comments/search", {"subreddit": sub, "body": term, "fields": C}, lo, hi, CAPS["keyword_comments_per_sub_term_half"], fails), "kw")
                return n
            st.task(f"kw:{sub}:{term}", fn)
    # order of work (time-boxed run): 1 thread discovery + replies (top-of-mind), 2 core-brand keyword search, 3 wider brands
    cand = {}
    for term in THREAD_TERMS:  # term-major: every general sub gets the first term before the next term starts
        for sub in GENERAL_SUBS:
            def fn(fails, sub=sub, term=term):
                n = 0
                for lo, hi in slices(2):
                    rows = fetch("posts/search", {"subreddit": sub, "title": term, "fields": P}, lo, hi, CAPS["thread_title_hits_per_sub_term_half"], fails)
                    n += st.add("post", rows, "thread")
                    for r in rows:
                        t = r.get("title", "")
                        if ASK_RE.search(t) and SHOP_RE.search(t) and (r.get("num_comments") or 0) >= 5:
                            st.m["threads"].append({"id": r["id"], "sub": sub, "nc": r["num_comments"], "ts": r["created_utc"]})
                return n
            st.task(f"threadscan:{sub}:{term}", fn)
    top = {t["id"]: t for t in st.m["threads"]}
    top = sorted(top.values(), key=lambda t: -t["nc"])[:CAPS["threads_total"]]
    st.m["thread_ids"] = [t["id"] for t in top]
    for t in top:
        def fn(fails, t=t):
            rows = fetch("comments/search", {"link_id": t["id"], "parent_id": "", "fields": C}, t["ts"] - 1, min(t["ts"] + 14 * 86400, HI + 14 * 86400), CAPS["comments_per_thread"], fails)
            return st.add("comment", rows, "threadreply")
        st.task("threadreplies:" + t["id"], fn)
    for term in SEARCH_TERMS:  # CORE terms first (list order), then wider brands
        kw(term)


def collect_appstore(st):
    final = SANDBOX / "appstore.jsonl"
    out = SANDBOX / "appstore.new"  # replaces appstore.jsonl only if this run fetched reviews (the RSS feed is flaky)
    out.write_text("", "utf8")
    apps = {}
    for brand, term in APPS.items():
        time.sleep(DELAY)
        res = http_json("https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": term, "entity": "software", "country": "us", "limit": 5}))["results"]
        want = {"Aritzia": "aritzia", "Zara": "zara", "H&M": "h&m", "Shein": "shein", "Uniqlo": "uniqlo"}[brand]
        pick = next((r for r in res if want in r["trackName"].lower() and
                     (want in r["sellerName"].lower() or want in r["trackName"].lower().split()[0] or brand == "H&M")), None)
        if brand == "Zara":
            pick = next((r for r in res if r["trackName"].lower().startswith("zara") and "inditex" not in r["sellerName"].lower() or "diseno" in r["sellerName"].lower()), pick)
        if brand == "H&M":
            pick = next((r for r in res if r["trackName"].lower().startswith("h&m")), pick)
        apps[brand] = {"id": pick["trackId"], "name": pick["trackName"], "seller": pick["sellerName"],
                       "rating_count_us": pick.get("userRatingCount"), "avg_rating_us": pick.get("averageUserRating")} if pick else None
    for brand, a in apps.items():  # store-level rating aggregates per storefront (lookup API works when the review RSS does not)
        for cc in ("us", "ca"):
            time.sleep(DELAY)
            try:
                r = http_json(f"https://itunes.apple.com/lookup?id={a['id']}&country={cc}")["results"][0]
                a[f"rating_count_{cc}"], a[f"avg_rating_{cc}"] = r.get("userRatingCount"), r.get("averageUserRating")
            except Exception as e:
                st.m["failures"].append({"appstore_lookup": brand, "cc": cc, "err": str(e)})
    st.m["apps"] = apps
    st.m["apps_lookup_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = collections.Counter()
    for brand, a in apps.items():
        if not a:
            continue
        for cc in ("us", "ca"):
            for page in range(1, 11):
                ent = []
                for attempt in range(4):  # the RSS endpoint intermittently returns an empty feed: retry before calling it the end
                    time.sleep(DELAY + 3 * attempt)
                    try:
                        j = http_json(f"https://itunes.apple.com/{cc}/rss/customerreviews/page={page}/id={a['id']}/sortby=mostrecent/json")
                        ent = [e for e in j.get("feed", {}).get("entry", []) if "im:rating" in e]
                    except Exception as e:
                        st.m["failures"].append({"appstore": brand, "cc": cc, "page": page, "err": str(e)})
                    if ent:
                        break
                if not ent:
                    if page == 1:
                        st.m["failures"].append({"appstore": brand, "cc": cc, "err": "review RSS returned an empty feed on page 1 after retries"})
                    break
                with out.open("a", encoding="utf8") as f:
                    for e in ent:
                        f.write(json.dumps({"brand": brand, "cc": cc, "rating": int(e["im:rating"]["label"]), "title": e["title"]["label"],
                                            "text": e["content"]["label"], "updated": e["updated"]["label"], "ver": e.get("im:version", {}).get("label")},
                                           ensure_ascii=False) + "\n")
                        n[(brand, cc)] += 1
    if n:
        out.replace(final)
        st.m["appstore_counts"] = {f"{b}|{c}": v for (b, c), v in n.items()}
    else:
        st.m["appstore_counts"] = {}
    st.m["appstore_reviews_fetched_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds") if n else None
    st.save()
    print("appstore", dict(n))


def collect_wiki(st):
    out = {}
    for brand, art in WIKI.items():
        time.sleep(DELAY)
        url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{art}/monthly/2025110100/2026103100"
        try:
            out[brand] = {i["timestamp"][:6]: i["views"] for i in http_json(url)["items"]}
        except Exception as e:
            st.m["failures"].append({"wiki": brand, "err": str(e)})
    (SANDBOX / "wiki.json").write_text(json.dumps({"articles": WIKI, "views": out}, indent=1), "utf8")
    st.m["wiki_brands"] = list(out)
    st.save()
    print("wiki", {b: len(v) for b, v in out.items()})


def collect(which):
    st = Store()
    for name, fn in (("reddit", collect_reddit), ("appstore", collect_appstore), ("wiki", collect_wiki)):
        if which in ("all", name):
            fn(st)
    st.m["collection_finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st.save()
    print("done", st.m["collection_finished_utc"])


# ================================================================ ANALYZE
def load_jsonl(p):
    return [json.loads(x) for x in p.open(encoding="utf8")] if p.exists() else []


def analyze():
    import numpy as np
    from scipy.stats import chi2
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    vader = SentimentIntensityAnalyzer()
    man = json.loads((SANDBOX / "manifest.json").read_text("utf8"))
    items = {}
    for kind in ("post", "comment"):
        for r in load_jsonl(SANDBOX / f"reddit_{kind}s.jsonl"):
            # time-boxed crawl: only femalefashionadvice got keyword search for all 5 core brands; malefashionadvice got 'aritzia' only
            # (would favour one brand), so keyword-sourced items from other subs are dropped. Thread/brand-sub items are kept.
            if r["src"] == "kw" and r["sub"].lower() != "femalefashionadvice":
                continue
            if LO <= r["ts"] < HI:
                r["kind"] = kind
                r["sub_type"] = "brand" if (r["sub"] or "").lower() in {s.lower() for s in BRAND_SUBS} else "general"
                r["month"] = month_of(r["ts"])
                r["clean"] = clean(r["text"])
                items[(kind, r["id"])] = r
    items = list(items.values())
    by_author = collections.defaultdict(list)
    for r in items:
        by_author[r["a"]].append(r)

    # --- author profiles: first self-report in time order
    prof = {}
    for a, rs in by_author.items():
        p = {"age": None, "gender": None, "country": None}
        for r in sorted(rs, key=lambda r: r["ts"]):
            p["age"] = p["age"] or find_age(r["text"])
            p["gender"] = p["gender"] or find_gender(r["text"])
            p["country"] = p["country"] or find_country(r["text"])
        p["gen"] = generation(p["age"])
        prof[a] = p

    # --- mention rows (one per brand per sentence)
    M = []
    for r in items:
        for off, s in sentences(r["clean"]):
            bs = [b for _, b in sentence_brands(s)]
            for b in bs:
                M.append({"brand": b, "a": r["a"], "item": r["id"], "kind": r["kind"], "sub": r["sub"], "sub_type": r["sub_type"],
                          "month": r["month"], "s": s, "single": len(bs) == 1, "attrs": attrs_of(s) if len(bs) == 1 else [],
                          "own": bool(OWN_RX.search(s))})
    cache = {}
    for m in M:
        if m["single"]:
            if m["s"] not in cache:
                cache[m["s"]] = vader.polarity_scores(m["s"])["compound"]
            m["c"] = cache[m["s"]]
            m["lab"] = sent_label(m["c"])
    # CEO rule: every cross-brand comparison uses GENERAL subreddits only (all brands searched the same way);
    # brand-subreddit rows (fan communities, no Zara/H&M sub) are kept only as labelled within-brand context.
    Mall = M
    M = [m for m in Mall if m["sub_type"] == "general"]
    brands_all = [b for b in BRANDS]
    mention_authors = {m["a"] for m in M}
    mention_items = {(m["kind"], m["item"]) for m in M}
    brand_items = collections.defaultdict(set)
    for m in M:
        brand_items[m["brand"]].add((m["kind"], m["item"]))

    out = {"meta": {}, "formulas": {}, "dictionaries": {}, "sample": {}, "modules": {}}
    out["meta"] = {
        "collection_started_utc": man.get("started_utc"), "collection_finished_utc": man.get("collection_finished_utc"),
        "analysis_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "window": list(WINDOW) + ["[start, end)"],
        "core_brands": CORE, "caps": man.get("caps"), "pct_rule": "percent reported only when base n >= 30, else 'base too small'",
        "sandbox_note": "raw data outside the repo; authors replaced by salted hash; salt not committed",
        "failure_records_all_sources": len(man.get("failures", [])),
        "arctic_shift_windows_given_up": sum(1 for f in man.get("failures", []) if "path" in f),
        "failures_by_source": dict(collections.Counter("arctic_shift" if "path" in f else "appstore" if any(k.startswith("appstore") for k in f) else "wiki" for f in man.get("failures", []))),
        "crawl_scope_note": "time-boxed crawl: 14 of 30 thread-discovery tasks, 6 of 120 keyword tasks and no wider-brand keyword tasks completed; see data/README.md",
    }
    out["formulas"] = {
        "wilson_95": "centre=(p+z^2/2n)/(1+z^2/n); half=z*sqrt(p(1-p)/n+z^2/4n^2)/(1+z^2/n); z=1.96",
        "net_sentiment": "(pos - neg) / (pos + neg + neu), VADER compound: pos >= 0.05, neg <= -0.05, else neu",
        "top_of_mind_first": "k = top-level replies whose first-named brand (earliest text position) is b; base = replies naming any brand; one reply per author per thread",
        "top_of_mind_total": "k = replies naming b at least once; base = replies naming any brand (multiple response, shares sum >100%)",
        "penetration_proxy": "k = distinct authors with >= 1 ownership/purchase phrase in a sentence naming b; base = distinct authors with >= 1 brand mention",
        "correspondence_analysis": "P=N/n; r,c = margins; S=(P-rc^T)/sqrt(rc^T); S=U*D*V^T; row coords=U*D/sqrt(r); col coords=V*D/sqrt(c); axis inertia=D^2; total inertia=chi2/n",
        "chi_square": "sum (O-E)^2/E, df=(R-1)(C-1), E=row*col/n",
        "adjusted_std_residual": "(O-E)/sqrt(E*(1-row/n)*(1-col/n)); flagged |z|>1.96 and, stricter, |z|> Bonferroni z for alpha=.05/cells",
        "kmeans": "repertoire vector = share of author's brand-mention sentences per brand (+ 'other') and share touching each attribute; KMeans n_init=10 seed 0; k in 2..6 by silhouette",
    }
    out["dictionaries"] = {"attributes": ATTRS, "brands": {b: [p for p, _ in pats] for b, pats in BRANDS.items()},
                           "brand_modes": {b: [m for _, m in pats] for b, pats in BRANDS.items()},
                           "ownership_phrases": OWN_RX.pattern, "context_words": CTX_RE.pattern}

    # --- sample sizes
    sub_counts = collections.Counter((r["sub"], r["kind"]) for r in items)
    subs = collections.defaultdict(dict)
    for (s, k), v in sub_counts.items():
        subs[s][k + "s"] = v
    wiki = json.loads((SANDBOX / "wiki.json").read_text("utf8")) if (SANDBOX / "wiki.json").exists() else {"views": {}}
    app_rows = load_jsonl(SANDBOX / "appstore.jsonl")
    out["sample"] = {
        "reddit_items": len(items), "reddit_posts": sum(r["kind"] == "post" for r in items),
        "reddit_comments": sum(r["kind"] == "comment" for r in items), "reddit_authors": len(by_author),
        "by_subreddit": dict(sorted(subs.items())), "items_mentioning_a_brand": len(mention_items),
        "authors_mentioning_a_brand": len(mention_authors), "mention_sentences": len(M),
        "single_brand_sentences": sum(m["single"] for m in M),
        "multi_brand_sentences_excluded_from_sentiment": sum(not m["single"] for m in M),
        "items_per_brand": {b: len(brand_items[b]) for b in brands_all if brand_items[b]},
        "sentences_per_brand": {b: sum(m["brand"] == b for m in M) for b in brands_all if any(m["brand"] == b for m in M)},
        "authors_per_brand": {b: len({m["a"] for m in M if m["brand"] == b}) for b in brands_all if any(m["brand"] == b for m in M)},
        "comparison_basis": "general subreddits only; per-brand counts below are general-sub counts",
        "mention_sentences_by_sub_type_before_filter": dict(collections.Counter(m["sub_type"] for m in Mall)),
        "appstore_reviews": {k: v for k, v in man.get("appstore_counts", {}).items()}, "apps": man.get("apps"),
        "wikipedia_series": {b: len(v) for b, v in wiki["views"].items()},
        "thread_ids_selected": len(man.get("thread_ids", [])),
    }

    # --- 1 top-of-mind
    tids = set(man.get("thread_ids", []))
    seen_ta, first, total, nrep = set(), collections.Counter(), collections.Counter(), 0
    for r in sorted(items, key=lambda r: r["ts"]):
        if r["kind"] != "comment" or not (r["link"] or "").startswith("t3_") or r["link"][3:] not in tids:
            continue
        if r["parent"] != r["link"] or (r["link"], r["a"]) in seen_ta:
            continue
        seen_ta.add((r["link"], r["a"]))
        nrep += 1
        h = brand_hits(r["clean"])
        if h:
            first[min(h)[1]] += 1
            for b in {x[1] for x in h}:
                total[b] += 1
    base = sum(first.values())
    out["modules"]["top_of_mind"] = {
        "question": "Which brands come to mind first when shoppers are asked where to shop / what to buy? (unaided awareness proxy)",
        "caveat": "replies to recommendation threads in general fashion subs; recommenders answer for the asker, so this is a proxy for salience, not self-reported unaided awareness",
        "threads_by_subreddit": dict(collections.Counter({t["id"]: t["sub"] for t in man.get("threads", [])}[i] for i in tids if i in {t["id"] for t in man.get("threads", [])})),
        "sample_composition_warning": "thread selection is by reply count; the most-replied recommendation threads are mostly menswear (malefashionadvice), so brand shares lean to menswear-friendly brands (Uniqlo, Old Navy, Abercrombie, Lululemon) and cannot be read as the Gen Z / Millennial women's market",
        "threads_with_replies": len({l for l, _ in seen_ta}), "top_level_replies": nrep, "replies_naming_a_brand": base,
        "first_mention": {b: prop(first[b], base) for b, _ in first.most_common()},
        "total_mention": {b: prop(total[b], base) for b, _ in total.most_common()}}

    # --- 2 penetration proxy
    def penetration(sel):
        base_a = {m["a"] for m in M if sel(m)}
        res = {}
        for b in brands_all:
            k = {m["a"] for m in M if sel(m) and m["brand"] == b and m["own"]}
            if k:
                res[b] = prop(len(k), len(base_a))
        return {"base_authors": len(base_a), "by_brand": dict(sorted(res.items(), key=lambda kv: -kv[1]["k"]))}
    out["modules"]["penetration_proxy"] = {
        "question": "What share of brand-mentioning authors say they own or bought each brand?",
        "disclosure": "A proxy, NOT true penetration: only authors who talked about a brand are in the base, brand subreddits over-represent their own brand, and phrase matching misses and over-catches.",
        "general_subreddits_only": penetration(lambda m: True)}

    # --- 3 profiling
    def cov(authors, key):
        k = sum(prof[a][key] is not None for a in authors)
        return prop(k, len(authors))
    ma = sorted(mention_authors)
    allau = list(by_author)
    gens = collections.Counter(prof[a]["gen"] for a in ma if prof[a]["gen"])
    mix_by_gen = {}
    for g in ("Gen Z (14-29)", "Millennial (30-45)"):
        rows = [m for m in M if prof[m["a"]]["gen"] == g]
        c = collections.Counter(m["brand"] for m in rows)
        mix_by_gen[g] = {"mention_sentences": len(rows), "authors": len({m["a"] for m in rows}),
                         "brand_share": {b: prop(v, len(rows)) for b, v in c.most_common(12)}}
    out["modules"]["profiling"] = {
        "question": "Who is talking: self-reported age, gender, country, and how does the brand mix differ by generation?",
        "definitions": "Gen Z = age 14-29, Millennial = 30-45 (in 2026), Older = 46+; first self-report by an author wins; age from '(24F)', 'I'm 24', '24 y/o', 'born in 1998'",
        "coverage_all_authors": {"base": len(allau), "age": cov(allau, "age"), "gender": cov(allau, "gender"), "country": cov(allau, "country")},
        "coverage_brand_mentioning_authors": {"base": len(ma), "age": cov(ma, "age"), "gender": cov(ma, "gender"), "country": cov(ma, "country")},
        "generation_of_brand_mentioning_authors": {g: prop(v, sum(1 for a in ma if prof[a]["age"] is not None)) for g, v in gens.items()},
        "gender_of_brand_mentioning_authors": {g: prop(v, sum(1 for a in ma if prof[a]["gender"])) for g, v in collections.Counter(prof[a]["gender"] for a in ma if prof[a]["gender"]).items()},
        "country_of_brand_mentioning_authors": {g: prop(v, sum(1 for a in ma if prof[a]["country"])) for g, v in collections.Counter(prof[a]["country"] for a in ma if prof[a]["country"]).items()},
        "median_age_known": float(np.median([prof[a]["age"] for a in ma if prof[a]["age"]])) if any(prof[a]["age"] for a in ma) else None,
        "brand_mix_by_generation": mix_by_gen}

    # --- 4 positioning
    S = [m for m in M if m["single"] and m["attrs"]]
    cells = collections.Counter((m["brand"], a) for m in S for a in m["attrs"])
    rows_b = [b for b in brands_all if sum(cells[(b, a)] for a in ATTRS) >= 30]
    A = list(ATTRS)
    pos = {"question": "How do brands differ on what people talk about (price, quality, fit, ...)?",
           "unit": "single-brand sentences containing an attribute keyword (a sentence can hit several attributes)",
           "brands_in_matrix": rows_b, "attributes": A, "min_attribute_hits_per_brand": 30,
           "core_brands_excluded_base_too_small": {b: sum(cells[(b, a)] for a in ATTRS) for b in CORE if b not in rows_b},
           "counts": {b: {a: cells[(b, a)] for a in A} for b in rows_b},
           "row_share_pct": {}}
    if len(rows_b) >= 3:
        N = np.array([[cells[(b, a)] for a in A] for b in rows_b], float)
        keep = N.sum(0) > 0
        N, A2 = N[:, keep], [a for a, k in zip(A, keep) if k]
        n = N.sum()
        P = N / n
        r, c = P.sum(1), P.sum(0)
        E = np.outer(r, c) * n
        chi = float(((N - E) ** 2 / E).sum())
        df = (N.shape[0] - 1) * (N.shape[1] - 1)
        Sres = (P - np.outer(r, c)) / np.sqrt(np.outer(r, c))
        U, D, Vt = np.linalg.svd(Sres, full_matrices=False)
        inertia = D ** 2
        tot = float(inertia.sum())
        rc, cc = U * D / np.sqrt(r)[:, None], Vt.T * D / np.sqrt(c)[:, None]
        z = (N - E) / np.sqrt(E * np.outer(1 - r, 1 - c))
        cells_n = N.size
        bonf = float(__import__("scipy.stats", fromlist=["norm"]).norm.isf(0.05 / cells_n / 2))
        pos.update({
            "n_sentence_attribute_hits": int(n), "attributes_used": A2,
            "row_share_pct": {b: {a: round(100 * N[i, j] / N[i].sum(), 1) for j, a in enumerate(A2)} for i, b in enumerate(rows_b)},
            "chi_square": {"chi2": round(chi, 2), "df": df, "p": float(chi2.sf(chi, df)), "n": int(n),
                           "cells_expected_lt_5": int((E < 5).sum()), "cells": int(cells_n),
                           "note": "hits are not fully independent (one author can contribute many); treat p as indicative"},
            "correspondence_analysis": {"total_inertia": round(tot, 4), "check_chi2_over_n": round(chi / n, 4),
                                        "axis_inertia": [round(float(x), 4) for x in inertia[:3]],
                                        "axis_inertia_pct": [round(100 * float(x) / tot, 1) for x in inertia[:3]],
                                        "row_coords_dim1_2": {b: [round(float(rc[i, 0]), 3), round(float(rc[i, 1]), 3)] for i, b in enumerate(rows_b)},
                                        "col_coords_dim1_2": {a: [round(float(cc[j, 0]), 3), round(float(cc[j, 1]), 3)] for j, a in enumerate(A2)}},
            "adjusted_std_residuals": {b: {a: round(float(z[i, j]), 2) for j, a in enumerate(A2)} for i, b in enumerate(rows_b)},
            "bonferroni_z": round(bonf, 2),
            "significant_cells": [{"brand": b, "attribute": a, "observed": int(N[i, j]), "expected": round(float(E[i, j]), 1), "z": round(float(z[i, j]), 2),
                                   "direction": "over" if z[i, j] > 0 else "under", "survives_bonferroni": bool(abs(z[i, j]) > bonf)}
                                  for i, b in enumerate(rows_b) for j, a in enumerate(A2) if abs(z[i, j]) > 1.96]})
    out["modules"]["positioning"] = pos

    # --- 5 perception
    sm = [m for m in M if m["single"]]
    per = {"question": "How positive or negative is talk about each brand, and on which attributes?",
           "method": "VADER (Hutto & Gilbert 2014) compound score on each single-brand sentence; thresholds +/-0.05",
           "by_brand": {b: sent_block([m["lab"] for m in sm if m["brand"] == b]) for b in brands_all if any(m["brand"] == b for m in sm)},
           "by_brand_x_attribute": {}}
    for b in brands_all:
        d = {}
        for a in ATTRS:
            labs = [m["lab"] for m in sm if m["brand"] == b and a in m["attrs"]]
            if labs:
                d[a] = sent_block(labs)
        if d:
            per["by_brand_x_attribute"][b] = d
    per["by_brand"] = dict(sorted(per["by_brand"].items(), key=lambda kv: -kv[1]["base"]))
    apps_out = {}
    for b in CORE:
        for cc_ in ("us", "ca"):
            rs = [x for x in app_rows if x["brand"] == b and x["cc"] == cc_]
            if not rs:
                continue
            dist = collections.Counter(x["rating"] for x in rs)
            labs = [sent_label(vader.polarity_scores(x["title"] + ". " + x["text"])["compound"]) for x in rs]
            apps_out[f"{b}|{cc_.upper()}"] = {
                "reviews": len(rs), "mean_rating": round(sum(x["rating"] for x in rs) / len(rs), 2),
                "distribution_pct": {str(s): prop(dist[s], len(rs)) for s in (1, 2, 3, 4, 5)},
                "review_text_sentiment": sent_block(labs), "date_range": [min(x["updated"] for x in rs)[:10], max(x["updated"] for x in rs)[:10]]}
    per["appstore"] = {"store_level_ratings_from_itunes_lookup": {b: {k: v for k, v in (a or {}).items() if k.startswith(("rating_count", "avg_rating"))} for b, a in (man.get("apps") or {}).items()},
                       "store_level_note": "all-time store aggregates as of apps_lookup_utc; not the review sample",
                       "apps_lookup_utc": man.get("apps_lookup_utc"),
                       "review_text_status": "available" if apps_out else "UNAVAILABLE: customer-review RSS returned empty feeds for all apps/storefronts at collection time (retried over ~2 hours)",
                       "note": "app reviews judge the app/delivery as much as clothes; only the most recent reviews (RSS, max 10 pages x 50) are available; non-English text scores neutral", "by_app_storefront": apps_out}

    # VADER validation (hand-labelled sample, blind to VADER)
    pool = sorted({m["s"] for m in sm if len(m["s"].split()) >= 4}, key=lambda s: hashlib.sha1(("val1" + s).encode()).hexdigest())[:50]
    key = lambda s: hashlib.sha1(s.encode()).hexdigest()[:10]
    (SANDBOX / "validation_sample.json").write_text(json.dumps([{"k": key(s), "text": s} for s in pool], indent=1, ensure_ascii=False), "utf8")
    lf = DATA / "validation_labels.json"
    val = {"status": "pending hand labels", "sample_file": "sandbox validation_sample.json (50 sentences, seeded by sha1 order)"}
    if lf.exists():
        lab = json.loads(lf.read_text("utf8"))
        pairs = [(lab[key(s)], sent_label(cache[s])) for s in pool if key(s) in lab]
        if pairs:
            n = len(pairs)
            agree = sum(a == b for a, b in pairs)
            cats = ("pos", "neu", "neg")
            po = agree / n
            pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
            lo_, hi_ = wilson(agree, n)
            val = {"n": n, "agreement": round(po, 3), "agreement_ci95": [round(lo_, 3), round(hi_, 3)],
                   "cohens_kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
                   "confusion_human_rows_vader_cols": {h: {v: sum(1 for a, b in pairs if a == h and b == v) for v in cats} for h in cats},
                   "human_label_counts": dict(collections.Counter(a for a, _ in pairs)),
                   "labeller": "one human-equivalent labeller (the engineer agent), blind to VADER output; single rater, so no inter-rater reliability",
                   "caution": "n=50 gives a wide interval; sentence sentiment toward a brand is not the same as VADER's sentence polarity"}
    per["vader_validation"] = val
    out["modules"]["perception"] = per

    # --- 6 segmentation
    per_a = collections.defaultdict(list)
    for m in M:
        per_a[m["a"]].append(m)
    elig = {a: v for a, v in per_a.items() if len(v) >= 2}
    tot_b = collections.Counter(m["brand"] for m in M)
    vec_brands = [b for b in brands_all if tot_b[b] >= 50]
    seg = {"question": "Are there groups of shoppers with different brand repertoires and concerns?",
           "eligible_authors": len(elig), "rule": "authors with >= 2 brand-mention sentences", "vector_brands": vec_brands + ["other"]}
    if len(elig) >= 60:
        ids = sorted(elig)
        X = np.array([[sum(m["brand"] == b for m in elig[a]) / len(elig[a]) for b in vec_brands] +
                      [sum(m["brand"] not in vec_brands for m in elig[a]) / len(elig[a])] +
                      [sum(at in m["attrs"] for m in elig[a]) / len(elig[a]) for at in ATTRS] for a in ids])
        sil = {}
        fits = {}
        for k in range(2, 7):
            km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
            fits[k] = km
            sil[k] = float(silhouette_score(X, km.labels_))
        kbest = max(sil, key=sil.get)
        lab = fits[kbest].labels_
        allm = [m for a in ids for m in elig[a]]
        base_share = collections.Counter(m["brand"] for m in allm)
        attr_base = {at: sum(at in m["attrs"] for m in allm) / len(allm) for at in ATTRS}
        segs = []
        for j in range(kbest):
            au = [a for a, l in zip(ids, lab) if l == j]
            ms = [m for a in au for m in elig[a]]
            bs = collections.Counter(m["brand"] for m in ms)
            ash = {at: sum(at in m["attrs"] for m in ms) / len(ms) for at in ATTRS}
            lift_b = {b: (bs[b] / len(ms)) / (base_share[b] / len(allm)) for b in bs if bs[b] / len(ms) >= 0.10}
            top_b = max(lift_b, key=lift_b.get) if lift_b else bs.most_common(1)[0][0]
            top_a = max(ATTRS, key=lambda at: ash[at] / attr_base[at] if attr_base[at] else 0)
            known = [prof[a]["gen"] for a in au if prof[a]["gen"]]
            segs.append({"segment": j + 1, "authors": len(au), "share_of_eligible": prop(len(au), len(elig)),
                         "mention_sentences": len(ms),
                         "top_brands_share_of_mentions": {b: round(100 * v / len(ms), 1) for b, v in bs.most_common(4)},
                         "top_attributes_share_of_mentions": {at: round(100 * ash[at], 1) for at in sorted(ash, key=ash.get, reverse=True)[:3]},
                         "sentiment": sent_block([m["lab"] for m in ms if m["single"]]),
                         "generation_known_n": len(known),
                         "generation_mix": {g: prop(v, len(known)) for g, v in collections.Counter(known).items()},
                         "name": f"{top_b}-led, {top_a}-minded (rule: highest brand lift with >=10% share; highest attribute lift)"})
        seg.update({"silhouette_by_k": {str(k): round(v, 3) for k, v in sil.items()}, "k": kbest, "segments": segs,
                    "caveat": "silhouette is often low on sparse share vectors; segments describe talk patterns, not validated shopper types"})
    else:
        seg["status"] = "base too small"
    out["modules"]["segmentation"] = seg

    # --- trend
    months = sorted({r["month"] for r in items})
    tr = {"question": "Does public search interest (Wikipedia pageviews) track social mention volume?",
          "months": months, "caveat": "mention volume is bounded by collection caps per month/subreddit; use share-of-voice, not raw growth. Pageviews are English Wikipedia, all-access, user agent.",
          "wikipedia_monthly_views": wiki["views"], "mention_items_by_month": {}, "mention_share_of_voice_pct": {}, "pearson_r_views_vs_mentions": {}}
    cm = collections.Counter((m["brand"], m["month"]) for m in {(m["brand"], m["kind"], m["item"], m["month"]): m for m in M}.values())
    tm = collections.Counter(m for (_, m) in cm.elements())
    for b in brands_all:
        if any(cm[(b, mo)] for mo in months):
            tr["mention_items_by_month"][b] = {mo: cm[(b, mo)] for mo in months}
            tr["mention_share_of_voice_pct"][b] = {mo: round(100 * cm[(b, mo)] / tm[mo], 1) if tm[mo] else None for mo in months}
    for b, v in wiki["views"].items():
        ys = [v.get(mo.replace("-", "")) for mo in months]
        xs = [cm[(b, mo)] for mo in months]
        if all(y is not None for y in ys) and len(ys) >= 12 and np.std(xs) > 0 and np.std(ys) > 0:
            tr["pearson_r_views_vs_mentions"][b] = {"r": round(float(np.corrcoef(xs, ys)[0, 1]), 2), "n_months": len(ys), "note": "n=12, descriptive only"}
    out["modules"]["trend"] = tr

    # within-brand context from brand subreddits: NOT comparable across brands (fan communities, no Zara/H&M sub)
    bs_rows = [m for m in Mall if m["sub_type"] == "brand" and m["single"]]
    ctx = {"label": "WITHIN-BRAND CONTEXT ONLY: brand-subreddit sentences. Fan communities, not comparable across brands, never used to fill a general-sub cell.",
           "subreddits_scanned": BRAND_SUBS, "no_subreddit_with_data_found_for": ["Zara", "H&M"], "by_brand": {}}
    for b in brands_all:
        rs = [m for m in bs_rows if m["brand"] == b]
        if rs:
            ctx["by_brand"][b] = {"sentences": len(rs), "sentiment": sent_block([m["lab"] for m in rs]),
                                  "attribute_sentences": {a: sum(a in m["attrs"] for m in rs) for a in ATTRS}}
    out["within_brand_context_brand_subreddits"] = ctx
    out["meta"]["comparison_basis"] = "all cross-brand modules use general subreddits only"
    # ---------------------------------------------------------------- supplementary analysis (general subreddits only)
    from scipy.stats import norm
    supp = {"note": "Supplementary analysis added after the audited report; every other top-level key is unchanged. Proxies from public social text, not survey measures.",
            "supplementary_analysis_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "comparison_basis": "general subreddits only"}
    # 1 brand funnel (nested proxy)
    fun = {}
    for b in brands_all:
        rows = [m for m in M if m["brand"] == b]
        if not rows:
            continue
        S = funnel_sets(rows)
        assert S["advocate"] <= S["bought"] <= S["considering"] <= S["aware"] and len(S["aware"]) == out["sample"]["authors_per_brand"][b], b
        aw, prev, ent = len(S["aware"]), None, {}
        for st_ in FUNNEL:
            k = len(S[st_])
            ent[st_] = {"k": k} if prev is None else {"k": k, "share_of_aware": prop(k, aw), "conversion_from_previous_stage": prop(k, prev)}
            prev = k
        fun[b] = ent
    supp["funnel"] = {
        "label": "SOCIAL-LISTENING PROXY, not a survey funnel: stages come from phrases in public posts, and only authors who talked about the brand are in the base",
        "base": "distinct authors mentioning the brand in general subreddits (= sample.authors_per_brand)",
        "stages": {"aware": "mentioned the brand", "considering": "intent phrase in a sentence naming the brand, or any later stage",
                   "bought": "existing ownership/purchase phrase (or advocate)", "advocate": "owner who also used a recommend/repeat phrase about the brand"},
        "intent_regex": INTENT_RX.pattern, "advocate_regex": ADV_RX.pattern, "ownership_regex": OWN_RX.pattern,
        "formulas": "share_of_aware = stage k / aware k; conversion = stage k / previous stage k; Wilson 95% CI; shown only when the base n >= 30; multi-brand sentences credit every brand named",
        "by_brand": fun}
    # 2 two-axis positioning map
    pm = {}
    for b in rows_b:
        tot = sum(cells[(b, a)] for a in ATTRS)
        sb = [m for m in sm if m["brand"] == b]
        blk = sent_block([m["lab"] for m in sb])
        pm[b] = {"attribute_hits": tot, "x_price_value_share": prop(cells[(b, "price/value")], tot),
                 "y_style_trend_share": prop(cells[(b, "style/trend")], tot),
                 "bubble_mention_sentences": sum(1 for m in M if m["brand"] == b),
                 "colour_net_sentiment": blk.get("net_sentiment"), "net_sentiment_block": blk}
    supp["positioning_map"] = {"rule": "brands with >= 30 attribute hits (same as the positioning matrix); x = price/value share of the brand's attribute hits, y = style/trend share, bubble = mention sentences, colour = net sentiment (VADER)",
                               "by_brand": pm}
    # 3 brand image
    coded = [(m, image_of(m["s"])) for m in sm]
    coded = [(m, ims) for m, ims in coded if ims]
    nb = collections.Counter(m["brand"] for m, _ in coded)
    gb = [b for b in brands_all if nb[b] >= 30]
    IM = list(IMAGES)
    cnt = {b: collections.Counter(i for m, ims in coded if m["brand"] == b for i in ims) for b in gb}
    img = {"dictionary": {k: {"regex": p, "valence": v} for k, (p, v) in IMAGES.items()},
           "pole_pairs": IMAGE_POLES,
           "unit": "single-brand sentences with at least one image keyword (a sentence can carry several images); multi-brand sentences excluded",
           "coded_sentences_per_brand": {b: nb[b] for b in brands_all if nb[b]},
           "brands_in_grid": gb, "brands_base_too_small": [b for b in brands_all if 0 < nb[b] < 30]}
    if len(gb) >= 3:
        pooled = {i: sum(cnt[b][i] for b in gb) / sum(nb[b] for b in gb) for i in IM}
        img["association_grid"] = {b: {i: prop(cnt[b][i], nb[b]) for i in IM} for b in gb}
        img["set_average_share_pct"] = {i: round(100 * pooled[i], 1) for i in IM}
        cols = [i for i in IM if sum(cnt[b][i] for b in gb) > 0]
        N = np.array([[cnt[b][i] for i in cols] for b in gb], float)
        n_ = N.sum()
        r_, c_ = N.sum(1) / n_, N.sum(0) / n_
        E = np.outer(r_, c_) * n_
        chi = float(((N - E) ** 2 / E).sum())
        df_ = (N.shape[0] - 1) * (N.shape[1] - 1)
        Z = (N - E) / np.sqrt(E * np.outer(1 - r_, 1 - c_))
        bonf = float(norm.isf(0.05 / N.size / 2))
        img["chi_square_independence"] = {"chi2": round(chi, 2), "df": df_, "p": float(chi2.sf(chi, df_)), "n_image_hits": int(n_),
                                          "cells": int(N.size), "cells_expected_lt_5": int((E < 5).sum()),
                                          "note": "one author can contribute many sentences, so p is indicative"}
        img["bonferroni_z"] = round(bonf, 2)
        img["adjusted_std_residuals"] = {b: {i: round(float(Z[a, j]), 2) for j, i in enumerate(cols)} for a, b in enumerate(gb)}
        sent = {b: {i: sent_block([m["lab"] for m, ims in coded if m["brand"] == b and i in ims]) for i in IM if cnt[b][i]} for b in gb}
        sw = []
        for a, b in enumerate(gb):
            for j, i in enumerate(cols):
                if abs(Z[a, j]) > bonf:
                    over, v = Z[a, j] > 0, IMAGES[i][1]
                    sw.append({"brand": b, "image": i, "observed": int(N[a, j]), "expected": round(float(E[a, j]), 1), "z": round(float(Z[a, j]), 2),
                               "direction": "over" if over else "under", "cell_net_sentiment": sent[b].get(i, {"status": "no sentences"}).get("net_sentiment", "base too small"),
                               "caution": "keyword association is not endorsement: people also discuss a brand's (un)ethical or cheap image critically; read with the cell sentiment",
                               "reading": "distinctive (neutral image)" if v == "0" else "strength" if over == (v == "+") else "weakness"})
        img["strengths_and_weaknesses_bonferroni"] = {"rule": "|adjusted standardised residual| above the Bonferroni z over all cells; over-index on a favourable image or under-index on an unfavourable one = strength, the reverse = weakness; neutral images = distinctive",
                                                      "cells": sw}
        img["net_sentiment_by_cell"] = sent
        quad = {}
        for b in CORE:
            if b not in gb:
                quad[b] = {"status": "base too small", "coded_sentences": nb[b]}
                continue
            cellsq = []
            for i in IM:
                s_ = sent[b].get(i)
                if not s_ or "net_sentiment" not in s_:
                    continue
                idx = (cnt[b][i] / nb[b]) / pooled[i]
                strong, pos_ = idx >= 1.0, s_["net_sentiment"] > 0
                cellsq.append({"image": i, "n": cnt[b][i], "share_pct": round(100 * cnt[b][i] / nb[b], 1), "index_vs_set_average": round(idx, 2),
                               "net_sentiment": s_["net_sentiment"],
                               "quadrant": ("defend" if pos_ else "fix") if strong else ("hidden asset" if pos_ else "low priority")})
            quad[b] = {"coded_sentences": nb[b], "cells_n_ge_30": cellsq, "cells_below_30_not_placed": sum(1 for i in IM if 0 < cnt[b][i] < 30)}
        img["priority_quadrant"] = {"rule": "only brand x image cells with n >= 30; strong = brand's share of the image >= pooled set-average share (index >= 1.0), weak otherwise; positive = net sentiment within the cell > 0. strong+positive = defend, strong+negative = fix, weak+positive = hidden asset, weak+negative = low priority",
                                    "by_brand": quad}
    else:
        img["status"] = "base too small"
    supp["brand_image"] = img
    out["supplementary"] = supp

    mp = DATA / "metrics.json"
    if mp.exists() and "--rebuild" not in sys.argv:
        # the audited metrics must not move: everything except "supplementary" (and the run timestamp) must equal the existing file
        old = json.loads(mp.read_text("utf8"))
        out["meta"]["analysis_utc"] = old["meta"]["analysis_utc"]
        a_ = json.dumps({k: v for k, v in old.items() if k != "supplementary"}, sort_keys=True, ensure_ascii=False)
        b_ = json.dumps({k: v for k, v in out.items() if k != "supplementary"}, sort_keys=True, ensure_ascii=False)
        assert a_ == b_, "existing metrics changed; refusing to write (use --rebuild after a re-crawl)"
        print("assert old == new for all existing keys: OK")
        # write the OLD content (same key order and bytes: set iteration order differs between runs) plus the new key
        out = {**{k: v for k, v in old.items() if k != "supplementary"}, "supplementary": supp}
    mp.write_text(json.dumps(out, indent=1, ensure_ascii=False), "utf8")

    # --- quotes: closest to the cell's median compound; <= 25 words; no personal cues
    def ok(m):
        w = len(m["s"].split())
        return 5 <= w <= 25 and not find_age(m["s"]) and not find_gender(m["s"]) and not find_country(m["s"]) and not re.search(r"@|\d{3}[- .]\d{3}", m["s"])
    quotes = {"rule": "per brand x attribute cell with >= 10 single-brand sentences: the up-to-3 sentences (5-25 words, no age/gender/country self-report, no username/permalink) whose VADER compound is closest to the cell median; ties broken by sha1 of the text; one quote per author",
              "cells": {}}
    for b in brands_all:
        for a in ATTRS:
            cell = [m for m in sm if m["brand"] == b and a in m["attrs"]]
            if len(cell) < 10:
                continue
            med = float(np.median([m["c"] for m in cell]))
            cand = sorted((m for m in cell if ok(m)), key=lambda m: (abs(m["c"] - med), hashlib.sha1(m["s"].encode()).hexdigest()))
            pick, au = [], set()
            for m in cand:
                if m["a"] not in au:
                    au.add(m["a"])
                    pick.append({"text": m["s"], "vader_compound": round(m["c"], 3), "subreddit_type": m["sub_type"], "month": m["month"]})
                if len(pick) == 3:
                    break
            quotes["cells"].setdefault(b, {})[a] = {"cell_n": len(cell), "cell_median_compound": round(med, 3), "quotes": pick}
    (DATA / "quotes.json").write_text(json.dumps(quotes, indent=1, ensure_ascii=False), "utf8")
    print("metrics.json + quotes.json written; items", len(items), "mention sentences", len(M))


# ================================================================ SELF-CHECK
def selfcheck():
    lo, hi = wilson(50, 100)
    assert abs(lo - 0.4038) < 1e-3 and abs(hi - 0.5962) < 1e-3, (lo, hi)
    assert wilson(0, 0) == (0.0, 0.0)
    assert net_sentiment(3, 1, 4) == 0.25 and net_sentiment(0, 0, 0) is None
    assert prop(5, 29)["status"] == "base too small" and prop(15, 30)["pct"] == 50.0
    names = lambda t: {b for _, b in sentence_brands(t)}
    assert names("I got a gap in my teeth.") == set()
    assert names("The gap between sizes at Zara is huge.") == {"Zara"}
    assert names("Bought jeans from Gap yesterday.") == {"Gap"}
    assert names("Gap between the two is huge.") == set()  # ctx word absent
    assert names("I parked in my Garage and read.") == set()
    assert names("Garage has cute tops.") == {"Garage"}
    assert names("mango smoothie after shopping") == set()
    assert names("I love Mango dresses.") == {"Mango"}
    assert names("cos it was cheap, I ordered more") == set()
    assert names("COS makes great coats.") == {"COS"}
    assert names("Simons sells nice coats.") == {"Simons"}
    assert names("my simons order arrived") == set()
    assert names("H&M and Zara jeans fit well") == {"H&M", "Zara"}
    assert names("hm, not sure") == set()
    assert find_age("Hi (24F) here") == 24 and find_age("I'm 31 and tall") == 31 and find_age("I'm 5'4 and 150") is None
    assert find_age("I'm 30 pounds up") is None and find_age("she is 27 y/o") == 27 and find_age("born in 1990") == 36
    assert find_gender("(24F) here") == "female" and find_gender("as a guy I like it") == "male"
    assert find_country("I live in Toronto now") == "Canada" and find_country("ships to Canada") is None
    assert generation(29) == "Gen Z (14-29)" and generation(30) == "Millennial (30-45)" and generation(None) is None
    assert OWN_RX.search("I just bought a coat from Zara") and not OWN_RX.search("Zara is pricey")
    assert "price/value" in attrs_of("It is so expensive") and attrs_of("hello there") == []
    # supplementary: funnel nesting and image dictionary
    rows = [{"a": "A", "s": "I just bought a coat from Zara", "own": True}, {"a": "B", "s": "Thinking of buying Zara jeans", "own": False},
            {"a": "C", "s": "I bought it and highly recommend Zara", "own": True}, {"a": "D", "s": "Zara is fine", "own": False},
            {"a": "E", "s": "Zara is my go-to", "own": False}]
    f = funnel_sets(rows)
    assert [len(f[k]) for k in FUNNEL] == [5, 3, 2, 1], f  # advocate needs ownership: E says go-to but never bought
    assert f["advocate"] <= f["bought"] <= f["considering"] <= f["aware"]
    assert INTENT_RX.search("Should I get the Aritzia puffer?") and INTENT_RX.search("is it worth it") and not INTENT_RX.search("I own it")
    assert ADV_RX.search("will buy again") and ADV_RX.search("obsessed with my coat") and not ADV_RX.search("I would never")
    im = lambda t: set(image_of(t))
    assert im("so unethical and exploitative") == {"unethical/exploitative"} and im("ethical production") == {"ethical/responsible"}
    assert im("itchy and uncomfortable") == {"uncomfortable"} and im("comfy and soft") == {"comfortable"}
    assert im("looks cheap and flimsy") == {"cheap/disposable"} and im("feels dated and boring") == {"dated/frumpy"}
    assert im("quality is hit or miss") == {"inconsistent/hit-or-miss"} and im("always reliable") == {"reliable/consistent"}
    assert im("so luxurious and elevated") == {"premium/aspirational"} and im("a very trendy drop") == {"trendy/fashion-forward"}
    assert "Canadian/local" in im("a Canadian brand") and "fun/young" in im("fun and youthful") and im("the weather today") == set()
    assert all(a in IMAGES and b in IMAGES and IMAGES[a][1] == "+" and IMAGES[b][1] == "-" for a, b in IMAGE_POLES)
    print("selfcheck ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selfcheck"
    selfcheck()
    if cmd == "collect":
        collect(sys.argv[2] if len(sys.argv) > 2 else "all")
    elif cmd == "analyze":
        DATA.mkdir(exist_ok=True)
        analyze()
