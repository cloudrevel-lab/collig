#!/usr/bin/env python3
"""Offline tests for the Flight Search skill and its routing.

No network here: airport resolution is local (airportsdata), and the search
pipeline is exercised through its pure helpers and a synthetic itinerary.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

passed = []
failed = []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
        print("PASS: " + name + ((" - " + detail) if detail else ""))
    else:
        failed.append(name)
        print("FAIL: " + name + ((" - " + detail) if detail else ""))


# ---------------------------------------------------------------------------
# Airport resolution
# ---------------------------------------------------------------------------
from skills.flight import FlightSearchSkill, _format_reply, _parse_date, _total_duration
from skills.flight.airports import nearby_airports, resolve_airport

res = resolve_airport("Datong Yungang")
check("resolves Datong Yungang airport", res.found and res.airport.iata == "DAT", repr(res.airport))
check(
    "Datong label carries the city",
    res.found and "Datong" in res.airport.label,
    res.airport.label if res.airport else "",
)

res = resolve_airport("SYD")
check("exact IATA resolves to Sydney", res.found and res.airport.iata == "SYD", repr(res.airport))

res = resolve_airport("sydney")
check("lower-case city resolves", res.found and res.airport.iata == "SYD", repr(res.airport))

res = resolve_airport("Datnog")
check("typo resolves to Datong", res.found and res.airport.iata == "DAT", repr(res.airport))

res = resolve_airport("Beijing")
check("Beijing picks the primary gateway", res.found and res.airport.iata == "PEK", repr(res.airport))
check(
    "Beijing lists Daxing as the alternative",
    any(item.iata == "PKX" for item in res.alternatives),
    repr([item.iata for item in res.alternatives]),
)

# Chinese names: the router now accepts Chinese travel requests, so the
# resolver must understand the place names that arrive with them.
res = resolve_airport("悉尼")
check("Chinese city resolves to Sydney", res.found and res.airport.iata == "SYD", repr(res.airport))

res = resolve_airport("大同云冈机场")
check("Chinese airport name resolves to Datong", res.found and res.airport.iata == "DAT", repr(res.airport))

res = resolve_airport("北京")
check("Chinese capital resolves to PEK", res.found and res.airport.iata == "PEK", repr(res.airport))

res = resolve_airport("北京大兴")
check("Chinese secondary airport resolves to PKX", res.found and res.airport.iata == "PKX", repr(res.airport))

res = resolve_airport("上海浦东机场")
check("Chinese airport suffix is tolerated", res.found and res.airport.iata == "PVG", repr(res.airport))

res = resolve_airport("zzzz nowhere")
check("unknown place is not a match", not res.found)
check("unknown place explains itself", "couldn't match" in res.error(), res.error())

nearby = nearby_airports(resolve_airport("Datong").airport, radius_km=350, limit=4)
check(
    "Datong has nearby airports for the empty-result hint",
    len(nearby) >= 1 and all(0 < distance <= 350 for _, distance in nearby),
    repr([(a.iata, round(d)) for a, d in nearby]),
)

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
check("ISO date", _parse_date("2026-12-19") == date(2026, 12, 19), repr(_parse_date("2026-12-19")))
check("day-month-year", _parse_date("19/12/2026") == date(2026, 12, 19), repr(_parse_date("19/12/2026")))
check("month name", _parse_date("19 Dec 2026") == date(2026, 12, 19), repr(_parse_date("19 Dec 2026")))
check(
    "ordinal month name",
    _parse_date("19th December 2026") == date(2026, 12, 19),
    repr(_parse_date("19th December 2026")),
)
check("nonsense date", _parse_date("next fortnight perhaps") is None)
check("empty date", _parse_date("") is None)

# ---------------------------------------------------------------------------
# Duration + formatting helpers
# ---------------------------------------------------------------------------
legs = [
    {
        "from": "SYD",
        "to": "CAN",
        "dep": datetime(2026, 12, 19, 10, 0),
        "arr": datetime(2026, 12, 19, 18, 0),
        "minutes": 480,
    },
    {
        "from": "CAN",
        "to": "DAT",
        "dep": datetime(2026, 12, 19, 21, 0),
        "arr": datetime(2026, 12, 19, 23, 30),
        "minutes": 150,
    },
]
check("total duration adds the layover", _total_duration(legs) == 480 + 150 + 180, repr(_total_duration(legs)))

# ---------------------------------------------------------------------------
# Tool surface + rendering
# ---------------------------------------------------------------------------
skill = FlightSearchSkill(skill_root=os.path.join(PROJECT, "skills", "flight"))
tools = {item.name: item for item in skill.get_tools()}
check("flight skill exposes two tools", set(tools) == {"search_flights", "find_airport"}, repr(sorted(tools)))
check("find_airport is callable offline", tools["find_airport"]("PEK").startswith("PEK"), tools["find_airport"]("PEK"))

rendered = _format_reply(
    origin=resolve_airport("Sydney").airport,
    destination=resolve_airport("Datong").airport,
    depart=date(2026, 12, 19),
    ret=date(2027, 1, 8),
    adults=2,
    cabin="economy",
    currency="AUD",
    itineraries=[
        {
            "price": 1234,
            "airlines": ["China Southern"],
            "airline_code": "CZ",
            "legs": [legs[0]],
            "stops": 0,
            "duration": 480,
        }
    ],
    total_found=1,
    url="https://example.test/flights",
)
check("render names both airports", "SYD" in rendered and "DAT" in rendered)
check("render states the party size", "2 adults" in rendered)
check("render explains the round-trip outbound", "outbound" in rendered)
check("render links Skyscanner", "skyscanner.com.au/transport/flights/syd/dat/261219/270108" in rendered)

bad = skill._search("Sydney", "Datong", "not-a-date", "", 2)
check("unreadable date returns a sentence, not a traceback", bad.startswith("I couldn't read"), bad)
unknown = tools["find_airport"]("zzzz nowhere")
check("unknown airport returns a sentence", "couldn't match" in unknown, unknown)

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
from core.harness import route_message

route = route_message(
    "search flight ticket for 2 adults from sydney to datong yungang airport, " "from 19December to Jan 8th round trip"
)
check("the Datong request routes to Flight Search", route.names == ["Flight Search"], repr(route.names))
check("routing advertises both flight tools", route.tool_count == 2, repr([t["name"] for t in route.tool_metadata]))

route = route_message("what is the weather in Sydney")
check("weather still routes to Weather only", route.names == ["Weather Reporter"], repr(route.names))

route = route_message("cheapest flights to Tokyo in March")
check("fare question routes to Flight Search", route.names == ["Flight Search"], repr(route.names))

# The Chinese request that exposed the gap: it says "机场", "经济舱" and
# "转机" but never "航班" or "机票", so the English-only trigger list routed
# it to no skill at all and the model had no flight tools.
route = route_message("从悉尼到大同云冈机场，2026年12月19日出发，2027年1月8日回。两个大人，经济舱，不限转机")
check("the Chinese Datong request routes to Flight Search", route.names == ["Flight Search"], repr(route.names))
check(
    "Chinese routing advertises both flight tools",
    route.tool_count == 2,
    repr([t["name"] for t in route.tool_metadata]),
)

route = route_message("大同云冈机场在哪")
check("a Chinese airport lookup routes to Flight Search", route.names == ["Flight Search"], repr(route.names))

route = route_message("帮我查一下从悉尼到大同的机票，两个大人，往返")
check("a Chinese airfare question routes to Flight Search", route.names == ["Flight Search"], repr(route.names))

route = route_message("今天悉尼天气怎么样")
check("Chinese weather routing is unaffected", route.names == ["Weather Reporter"], repr(route.names))

# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
print("%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    for name in failed:
        print("  -", name)
    sys.exit(1)
print("All checks passed.")
