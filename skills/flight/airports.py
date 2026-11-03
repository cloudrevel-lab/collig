"""Offline IATA airport resolution for the Flight Search skill.

Airports come from the ``airportsdata`` package (OurAirports derived), so
resolving "Datong Yungang" or "SYD" never needs a network call.  The matcher is
deliberately small and predictable:

* an exact IATA/ICAO code always wins;
* then exact / prefix / substring matches on the city and the airport name;
* then token containment ("datong yungang" vs city "Datong");
* then a fuzzy ratio, which absorbs typos like "Sidney" or "Datnog";
* multi-airport cities fall back to a curated primary hub (Beijing -> PEK).

Every function here is pure and offline, which is what the tests exercise.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - exercised by the dependency being present
    import airportsdata
except Exception:  # pragma: no cover
    airportsdata = None

# Words that carry no signal when someone says "Datong Yungang Airport".
_GENERIC = {
    "airport",
    "airfield",
    "international",
    "intl",
    "terminal",
    "domestic",
    "regional",
    "airbase",
    "the",
    "at",
    "in",
}

# One primary gateway per multi-airport city, so "Beijing" does not randomly
# resolve to PKX or "Shanghai" to SHA.
_PRIMARY = {
    "beijing": "PEK",
    "shanghai": "PVG",
    "tokyo": "NRT",
    "osaka": "KIX",
    "seoul": "ICN",
    "london": "LHR",
    "paris": "CDG",
    "new york": "JFK",
    "washington": "IAD",
    "chicago": "ORD",
    "los angeles": "LAX",
    "san francisco": "SFO",
    "miami": "MIA",
    "houston": "IAH",
    "dallas": "DFW",
    "rome": "FCO",
    "milan": "MXP",
    "moscow": "SVO",
    "istanbul": "IST",
    "bangkok": "BKK",
    "jakarta": "CGK",
    "kuala lumpur": "KUL",
    "singapore": "SIN",
    "taipei": "TPE",
    "hong kong": "HKG",
    "sao paulo": "GRU",
    "rio de janeiro": "GIG",
    "buenos aires": "EZE",
    "mexico city": "MEX",
    "toronto": "YYZ",
    "montreal": "YUL",
    "vancouver": "YVR",
    "sydney": "SYD",
    "melbourne": "MEL",
    "brisbane": "BNE",
    "perth": "PER",
    "adelaide": "ADL",
    "datong": "DAT",
}


@dataclass(frozen=True)
class Airport:
    """A single airport record, reduced to the fields the skill uses."""

    iata: str
    icao: str
    name: str
    city: str
    region: str
    country: str
    lat: float
    lon: float

    @property
    def label(self) -> str:
        tail = ", ".join(part for part in (self.city, self.region, self.country) if part)
        head = "%s — %s" % (self.iata, self.name or self.city)
        return head + (", " + tail if tail else "")

    @property
    def short(self) -> str:
        return "%s %s" % (self.iata, self.city or self.name)


@lru_cache(maxsize=20000)
def _normalise(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^\w]+", " ", text)
    words = [word.replace("_", "") for word in text.split()]
    return " ".join(word for word in words if word and word not in _GENERIC).strip()


# Historical / colloquial names and common misspellings people actually type.
_ALIASES = {
    "peking": "pek",
    "canton": "can",
    "bombay": "bom",
    "madras": "maa",
    "calcutta": "ccu",
    "bangalore": "blr",
    "saigon": "sgn",
    "constantinople": "ist",
    "sidney": "syd",
    "melborn": "mel",
    "brisborn": "bne",
    "beijing city": "pek",
    "shanghai city": "pvg",
    "new york city": "jfk",
    "nyc": "jfk",
    "washington dc": "iad",
    "hongkong": "hkg",
    "guangzou": "can",
}

# Chinese city and airport names.  The router already accepts Chinese travel
# requests ("从悉尼到大同云冈机场…"), so the resolver must not answer "I
# couldn't match '悉尼'" once the tool is called.  Prefer the longest matching
# prefix so "上海浦东机场" resolves to PVG while bare "上海" stays PVG and
# "北京大兴" resolves to PKX rather than the Capital gateway.
_CJK_ALIASES = {
    # Mainland China
    "北京": "pek",
    "北京首都": "pek",
    "首都机场": "pek",
    "北京大兴": "pkx",
    "大兴机场": "pkx",
    "上海": "pvg",
    "上海浦东": "pvg",
    "浦东机场": "pvg",
    "上海虹桥": "sha",
    "虹桥机场": "sha",
    "广州": "can",
    "广州白云": "can",
    "白云机场": "can",
    "深圳": "szx",
    "深圳宝安": "szx",
    "宝安机场": "szx",
    "成都": "ctu",
    "成都双流": "ctu",
    "双流机场": "ctu",
    "成都天府": "tfu",
    "天府机场": "tfu",
    "重庆": "ckg",
    "西安": "xiy",
    "咸阳机场": "xiy",
    "杭州": "hgh",
    "南京": "nkg",
    "武汉": "wuh",
    "长沙": "csx",
    "昆明": "kmg",
    "厦门": "xmn",
    "天津": "tsn",
    "青岛": "tao",
    "大连": "dlc",
    "沈阳": "she",
    "哈尔滨": "hrb",
    "郑州": "cgo",
    "济南": "tna",
    "太原": "tyn",
    "大同": "dat",
    "大同云冈": "dat",
    "云冈机场": "dat",
    "呼和浩特": "het",
    "乌鲁木齐": "urc",
    "拉萨": "lxa",
    "三亚": "syx",
    "海口": "hak",
    # Greater China and Asia
    "香港": "hkg",
    "澳门": "mfm",
    "台北": "tpe",
    "高雄": "kah",
    "东京": "nrt",
    "成田机场": "nrt",
    "羽田机场": "hnd",
    "大阪": "kix",
    "关西机场": "kix",
    "名古屋": "ngo",
    "首尔": "icn",
    "仁川机场": "icn",
    "釜山": "pus",
    "新加坡": "sin",
    "曼谷": "bkk",
    "吉隆坡": "kul",
    "雅加达": "cgk",
    "马尼拉": "mnl",
    "河内": "han",
    "胡志明市": "sgn",
    # Oceania, Europe, the Americas and the Middle East
    "悉尼": "syd",
    "墨尔本": "mel",
    "布里斯班": "bne",
    "珀斯": "per",
    "阿德莱德": "adl",
    "奥克兰": "akl",
    "伦敦": "lhr",
    "希思罗机场": "lhr",
    "巴黎": "cdg",
    "法兰克福": "fra",
    "慕尼黑": "muc",
    "阿姆斯特丹": "ams",
    "罗马": "fco",
    "米兰": "mxp",
    "马德里": "mad",
    "巴塞罗那": "bcn",
    "莫斯科": "svo",
    "伊斯坦布尔": "ist",
    "迪拜": "dxb",
    "多哈": "doh",
    "纽约": "jfk",
    "洛杉矶": "lax",
    "旧金山": "sfo",
    "西雅图": "sea",
    "芝加哥": "ord",
    "波士顿": "bos",
    "华盛顿": "iad",
    "多伦多": "yyz",
    "温哥华": "yvr",
    "墨西哥城": "mex",
    "圣保罗": "gru",
    "里约热内卢": "gig",
    "布宜诺斯艾利斯": "eze",
    "约翰内斯堡": "jnb",
    "开罗": "cai",
    "内罗毕": "nbo",
}

_CJK_ALIAS_KEYS = tuple(sorted(_CJK_ALIASES, key=len, reverse=True))


def _cjk_alias(normalised: str) -> Optional[str]:
    """The IATA code for the longest Chinese alias prefixing `normalised`."""
    for key in _CJK_ALIAS_KEYS:
        if normalised.startswith(key):
            return _CJK_ALIASES[key]
    return None


# Airports that still appear in the upstream dataset but no longer take traffic.
_CLOSED = {"NAY", "TXL", "THF", "SXF"}

# Name markers for fields that share a city name but are not airline gateways
# ("Sydney Bankstown Airport", "RAF Northolt").  Used only to trim the "also"
# list, never to reject a direct code lookup.
_GENERAL_AVIATION = (
    "air base",
    "raf ",
    "seaplane",
    "heliport",
    "airfield",
    "flying",
    "gliding",
    "aerodrome",
    "bankstown",
)


@lru_cache(maxsize=1)
def load_airports() -> Dict[str, Airport]:
    """Load the IATA airport table once (about 7.9k airports)."""
    if airportsdata is None:  # pragma: no cover
        return {}
    raw = airportsdata.load("IATA")
    out: Dict[str, Airport] = {}
    for code, item in raw.items():
        out[code] = Airport(
            iata=code,
            icao=str(item.get("icao") or ""),
            name=str(item.get("name") or ""),
            city=str(item.get("city") or ""),
            region=str(item.get("subd") or ""),
            country=str(item.get("country") or ""),
            lat=float(item.get("lat") or 0.0),
            lon=float(item.get("lon") or 0.0),
        )
    return out


def _score(airport: Airport, query: str, tokens: Sequence[str]) -> int:
    iata = airport.iata.lower()
    icao = airport.icao.lower()
    city = _normalise(airport.city)
    name = _normalise(airport.name)

    if query == iata:
        return 10_000
    if icao and query == icao:
        return 9_000

    score = 0
    if city and query == city:
        score = max(score, 600)
    if name and query == name:
        score = max(score, 560)
    # Prefix matches need a real prefix: a one-letter city fragment (from a
    # non-ASCII name) otherwise "matches" every query that starts with it.
    if city and len(query) >= 3 and city.startswith(query):
        score = max(score, 430)
    if name and len(query) >= 3 and name.startswith(query):
        score = max(score, 390)
    if city and len(city) >= 4 and query.startswith(city):
        score = max(score, 430)
    if name and len(name) >= 4 and query.startswith(name):
        score = max(score, 390)
    if city and len(query) >= 4 and query in city:
        score = max(score, 330)
    if name and len(query) >= 4 and query in name:
        score = max(score, 290)

    token_set = set(tokens)
    city_tokens = set(city.split())
    name_tokens = set(name.split())
    if city_tokens and city_tokens <= token_set:
        score = max(score, 410)
    if name_tokens and name_tokens <= token_set:
        score = max(score, 360)

    # Fuzzy fallback for typos ("Sidney", "Datnog", "Guangzou").
    ratio = max(
        SequenceMatcher(None, query, city).ratio() if city else 0.0,
        SequenceMatcher(None, query, name).ratio() if name else 0.0,
    )
    if ratio >= 0.72:
        score = max(score, int(ratio * 320))

    if score <= 0:
        return 0

    # Prefer the curated primary gateway for multi-airport cities, then the
    # airport that advertises itself as international, then shorter names.
    if _PRIMARY.get(city) == airport.iata:
        score += 60
    if "international" in name:
        score += 20
    return score


@dataclass
class Resolution:
    """Result of resolving free text to an airport."""

    airport: Optional[Airport]
    alternatives: List[Airport]
    query: str

    @property
    def found(self) -> bool:
        return self.airport is not None

    def error(self) -> str:
        return (
            "I couldn't match %r to an airport. Try a city name or a three-letter IATA code (for example SYD or DAT)."
            % (self.query,)
        )


def resolve_airport(query: str, limit: int = 1) -> Resolution:
    """Resolve free text such as 'Sydney', 'SYD' or 'Datong Yungang' to an airport."""
    text = (query or "").strip()
    airports = load_airports()
    if not text or not airports:
        return Resolution(None, [], text)

    normalised = _normalise(text)
    tokens = normalised.split()
    if not tokens and len(text.strip()) == 3:
        normalised = text.strip().lower()
        tokens = [normalised]
    normalised = _ALIASES.get(normalised, normalised)
    cjk = _cjk_alias(normalised)
    if cjk:
        normalised = cjk
        tokens = [cjk]

    scored: List[Tuple[int, Airport]] = []
    for airport in airports.values():
        if airport.iata in _CLOSED:
            continue
        value = _score(airport, normalised, tokens)
        if value:
            scored.append((value, airport))
    if not scored:
        return Resolution(None, [], text)

    scored.sort(key=lambda item: (-item[0], len(item[1].name), item[1].iata))
    top_score, top = scored[0]

    alternatives: List[Airport] = []
    top_city = _normalise(top.city)
    for score, airport in scored[1:]:
        if len(alternatives) >= max(0, limit + 2):
            break
        same_city = _normalise(airport.city) == top_city and airport.country == top.country
        name = airport.name.lower()
        if not same_city or not name.startswith(top_city):
            continue
        if any(marker in name for marker in _GENERAL_AVIATION):
            continue
        alternatives.append(airport)

    return Resolution(top, alternatives, text)


def haversine_km(a: Airport, b: Airport) -> float:
    """Great-circle distance between two airports, in kilometres."""
    radius = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, h)))


def nearby_airports(airport: Airport, radius_km: float = 300.0, limit: int = 4) -> List[Tuple[Airport, float]]:
    """Airports within ``radius_km``, nearest first.

    Used when a search comes back empty: Datong has almost no through-fare
    inventory, so pointing at Taiyuan or Hohhot is more useful than "no
    results".
    """
    rows: List[Tuple[Airport, float]] = []
    for other in load_airports().values():
        if other.iata == airport.iata:
            continue
        distance = haversine_km(airport, other)
        if 0 < distance <= radius_km:
            rows.append((other, distance))
    rows.sort(key=lambda item: item[1])
    return rows[:limit]
