"""Flight Search Skill — live itineraries without an API key.

The skill asks Google Flights for a route (the same query a browser builds) and
parses the server-rendered payload into a ranked list of itineraries.  There is
no booking, no account and no API key; prices are live quotes, not cached
inventory.

Why this shape:

* ``fast_flights`` owns the protobuf encoding of the ``?tfs=`` search token.
  That is the one genuinely hard part of talking to Google Flights, so it is
  not reimplemented here.
* The HTTP fetch is a plain ``requests`` call with a browser user agent.  The
  library's own fetcher pins an impersonation profile that newer ``primp``
  builds accept and older ones reject; a plain request works for the same
  HTML and cannot fight with the ``ddgs`` dependency over the ``primp``
  version.
* The parser is ours, and tolerant: Google occasionally returns a row with no
  price (sold out, or "price unavailable"), and the library's parser raises
  ``IndexError`` on those, which would make an otherwise good set of results
  look like a failure.

Round trips: Google prices the whole trip but renders the *outbound* options
first, so the itinerary shown is the outbound leg and the price already
includes the cheapest return.  The reply says so, and links out for the return
choice.  Pretending otherwise would be the same lie as inventing a fare.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from skills.base import Skill
from skills.tooling import tool

from .airports import Airport, nearby_airports, resolve_airport

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept-Language": "en-AU,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TIMEOUT = 40
_CACHE_TTL = 300  # seconds; repeated follow-ups on the same route are common

_CABINS = {
    "economy": "economy",
    "premium-economy": "premium-economy",
    "premium economy": "premium-economy",
    "premium": "premium-economy",
    "business": "business",
    "first": "first",
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%d %B",
    "%d %b",
    "%B %d %Y",
    "%b %d %Y",
    "%B %d",
    "%b %d",
)

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_CACHE: Dict[str, Tuple[float, str]] = {}


class FlightSearchSkill(Skill):
    """Search live flight prices and itineraries (Google Flights, no key)."""

    def __init__(self, skill_root=None):
        super().__init__(skill_root)

    @property
    def name(self) -> str:
        return "Flight Search"

    @property
    def description(self) -> str:
        return (
            "Search live flight prices and itineraries for one-way or round-trip "
            "routes, with airline, stops, times and duration (Google Flights, no API key)"
        )

    @property
    def triggers(self) -> List[str]:
        return [
            "flight",
            "flights",
            "airfare",
            "air fare",
            "air ticket",
            "air tickets",
            "plane ticket",
            "plane tickets",
            "flight search",
            "cheapest flight",
            "round trip",
            "round-trip",
            "one way",
            "one-way",
            "fly to",
            "flying to",
            "skyscanner",
            "google flights",
        ]

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def get_tools(self) -> List[Any]:
        @tool
        def search_flights(
            origin: str,
            destination: str,
            depart_date: str,
            return_date: str = "",
            adults: int = 1,
            cabin: str = "economy",
            max_stops: int = -1,
            currency: str = "",
            sort: str = "price",
            limit: int = 8,
        ) -> str:
            """
            Search live flight prices and itineraries between two airports.

            Use this for any request about flights, airfares, plane tickets,
            flying somewhere, or comparing routes and dates. Accepts city names
            or IATA codes. Returns real quotes with airline, times, stops and
            duration, cheapest first.

            Args:
                origin: Departure city or IATA code, e.g. "Sydney" or "SYD".
                destination: Arrival city or IATA code, e.g. "Datong" or "DAT".
                depart_date: Departure date, e.g. "2026-12-19" or "19 Dec 2026".
                return_date: Return date for a round trip; leave empty for one-way.
                adults: Number of adult passengers (1-9).
                cabin: "economy", "premium-economy", "business" or "first".
                max_stops: Maximum stops per direction; -1 means any (0 = nonstop).
                currency: Three-letter currency for the quote, e.g. "AUD", "USD".
                sort: "price" or "duration".
                limit: How many itineraries to list (1-20).

            Returns:
                A formatted list of itineraries plus booking links, or a clear
                message explaining why no fares were found.
            """
            try:
                return self._search(
                    origin=origin,
                    destination=destination,
                    depart_date=depart_date,
                    return_date=return_date,
                    adults=adults,
                    cabin=cabin,
                    max_stops=max_stops,
                    currency=currency,
                    sort=sort,
                    limit=limit,
                )
            except Exception as exc:  # never abort the ADK invocation
                return "Flight search failed: %s" % exc

        @tool
        def find_airport(query: str) -> str:
            """
            Look up the IATA code and name of an airport or city.

            Use this when you need to confirm which airport a city name refers
            to, or when a flight search reported an ambiguous or unknown place.

            Args:
                query: City, airport name or code, e.g. "Datong Yungang",
                    "PEK", "悉尼", "大同云冈机场".

            Returns:
                The matched airport with its code and location, plus any other
                airports serving the same city.
            """
            resolution = resolve_airport(query)
            if not resolution.found:
                return resolution.error()
            lines = [resolution.airport.label]
            if resolution.alternatives:
                lines.append("Also: " + "; ".join(a.label for a in resolution.alternatives))
            return "\n".join(lines)

        return [search_flights, find_airport]

    # ------------------------------------------------------------------
    # Search pipeline
    # ------------------------------------------------------------------

    def _search(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str = "",
        adults: int = 1,
        cabin: str = "economy",
        max_stops: int = -1,
        currency: str = "AUD",
        sort: str = "price",
        limit: int = 8,
    ) -> str:
        from_res = resolve_airport(origin)
        to_res = resolve_airport(destination)
        if not from_res.found:
            return from_res.error()
        if not to_res.found:
            return to_res.error()
        if from_res.airport.iata == to_res.airport.iata:
            return "Origin and destination are the same airport (%s)." % from_res.airport.iata

        depart = _parse_date(depart_date)
        if depart is None:
            return (
                "I couldn't read the departure date %r. Use ISO (2026-12-19) "
                "or a form like 19 Dec 2026." % depart_date
            )
        if depart < date.today():
            return "%s is in the past (today is %s)." % (depart.isoformat(), date.today().isoformat())

        ret: Optional[date] = None
        if (return_date or "").strip():
            ret = _parse_date(return_date)
            if ret is None:
                return (
                    "I couldn't read the return date %r. Use ISO (2027-01-08) or a form like 8 Jan 2027." % return_date
                )
            if ret < depart:
                return "The return date (%s) is before the departure date (%s)." % (ret.isoformat(), depart.isoformat())

        cabin_key = _CABINS.get((cabin or "economy").strip().lower(), "economy")
        try:
            adults_n = max(1, min(9, int(adults)))
        except (TypeError, ValueError):
            adults_n = 1
        try:
            limit_n = max(1, min(20, int(limit)))
        except (TypeError, ValueError):
            limit_n = 8
        try:
            stops_cap = int(max_stops)
        except (TypeError, ValueError):
            stops_cap = -1
        default_currency = str(self.config.get("FLIGHT_DEFAULT_CURRENCY") or "AUD")
        currency_code = (currency or default_currency).strip().upper()[:3] or "AUD"

        itineraries, url, error = _query(
            from_res.airport.iata,
            to_res.airport.iata,
            depart,
            ret,
            adults_n,
            cabin_key,
            stops_cap,
            currency_code,
        )
        if error:
            return "%s\n\nYou can still check the route directly: %s" % (error, url)

        if not itineraries:
            if ret is not None:
                fallback = _one_way_fallback(
                    from_res.airport,
                    to_res.airport,
                    depart,
                    ret,
                    adults_n,
                    cabin_key,
                    stops_cap,
                    currency_code,
                    url,
                )
                if fallback:
                    return fallback
            return _empty_reply(from_res.airport, to_res.airport, depart, ret, adults_n, cabin_key, currency_code, url)

        if stops_cap >= 0:
            itineraries = [item for item in itineraries if item["stops"] <= stops_cap]
            if not itineraries:
                return (
                    "No itinerary with at most %d stop(s) was in Google Flights' first page for "
                    "%s → %s on %s. Try allowing one more stop."
                    % (stops_cap, from_res.airport.iata, to_res.airport.iata, depart.isoformat())
                )

        key = "duration" if str(sort).lower().startswith("dur") else "price"
        itineraries.sort(key=lambda item: (item[key], item["price"]))

        return _format_reply(
            origin=from_res.airport,
            destination=to_res.airport,
            depart=depart,
            ret=ret,
            adults=adults_n,
            cabin=cabin_key,
            currency=currency_code,
            itineraries=itineraries[:limit_n],
            total_found=len(itineraries),
            url=url,
        )


# ----------------------------------------------------------------------
# Query + one-way fallback
# ----------------------------------------------------------------------


def _query(
    from_iata: str,
    to_iata: str,
    depart: date,
    ret: Optional[date],
    adults: int,
    cabin: str,
    stops_cap: int,
    currency: str,
) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """Build the Google Flights query, fetch it and parse the itineraries."""
    from fast_flights import FlightQuery, Passengers, create_query

    legs = [FlightQuery(date=depart.isoformat(), from_airport=from_iata, to_airport=to_iata)]
    if ret is not None:
        legs.append(FlightQuery(date=ret.isoformat(), from_airport=to_iata, to_airport=from_iata))
    query = create_query(
        flights=legs,
        seat=cabin,
        trip="round-trip" if ret is not None else "one-way",
        passengers=Passengers(adults=adults),
        currency=currency,
        max_stops=stops_cap if stops_cap >= 0 else None,
        hide_separate_and_self_transfer=True,
    )
    url = query.url()
    html, error = _fetch(url)
    if error:
        return [], url, error
    itineraries, parse_error = _parse_html(html)
    if parse_error:
        return [], url, parse_error
    return itineraries, url, None


def _one_way_fallback(
    origin: Airport,
    destination: Airport,
    depart: date,
    ret: date,
    adults: int,
    cabin: str,
    stops_cap: int,
    currency: str,
    round_trip_url: str,
) -> Optional[str]:
    """When a round trip has no through-fares, price the outbound separately.

    Google often carries one-way inventory for a route but no round-trip
    combination (small Chinese airports are the common case), and "no fares"
    for the trip is unhelpful when the outbound is bookable.  Only the outbound
    is probed here: one extra request, and the reply says the return still
    needs its own search.
    """
    items, url, error = _query(origin.iata, destination.iata, depart, None, adults, cabin, stops_cap, currency)
    if error or not items:
        return None

    items.sort(key=lambda item: item["price"])
    lines = [
        "No round-trip fares for %s → %s on %s → %s, but the outbound leg is sold separately:"
        % (
            origin.iata,
            destination.iata,
            depart.strftime("%d %b %Y"),
            ret.strftime("%d %b %Y"),
        ),
        "",
    ]
    for item in items[:3]:
        first = item["legs"][0]
        last = item["legs"][-1]
        lines.append(
            "  %s total · %s · %s · %s — %s %s → %s %s"
            % (
                _money(item["price"], currency),
                _airlines(item["airlines"]),
                _stops(item["stops"]),
                _duration(item["duration"]),
                first["dep"].strftime("%d %b %H:%M"),
                first["from"],
                last["arr"].strftime("%d %b %H:%M"),
                last["to"],
            )
        )
    lines.extend(
        [
            "",
            "That is a one-way fare for the outbound only. Price the return (%s → %s, %s) "
            "separately, and leave a good buffer: separate tickets are not protected if the "
            "first leg runs late." % (destination.iata, origin.iata, ret.strftime("%d %b %Y")),
            "Outbound search: " + url,
            "Round-trip search: " + round_trip_url,
            "Skyscanner: " + _skyscanner_url(origin.iata, destination.iata, depart, ret, adults, cabin, currency),
        ]
    )
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Dates
# ----------------------------------------------------------------------


def _parse_date(value: str) -> Optional[date]:
    """Parse the date forms a model or a person is likely to hand us."""
    text = (value or "").strip()
    if not text:
        return None
    text = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()

    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%Y" in fmt:
            return parsed.date()
        # No year supplied: use the current year, rolling to next year when the
        # date is already behind us (a December request in January means next).
        candidate = parsed.date().replace(year=date.today().year)
        if candidate < date.today() - timedelta(days=1):
            candidate = candidate.replace(year=date.today().year + 1)
        return candidate

    # "19 December 2026" with an ordinal/comma variant already handled above.
    match = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})\s*(\d{4})?$", text)
    if match:
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2)[:3].lower())
        year = int(match.group(3)) if match.group(3) else None
        if month and 1 <= day <= 31:
            try:
                if year:
                    return date(year, month, day)
                candidate = date(date.today().year, month, day)
                if candidate < date.today() - timedelta(days=1):
                    candidate = candidate.replace(year=date.today().year + 1)
                return candidate
            except ValueError:
                return None
    return None


# ----------------------------------------------------------------------
# Fetch + parse
# ----------------------------------------------------------------------


def _fetch(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Fetch the Google Flights page, with a tiny in-process cache."""
    now = time.monotonic()
    cached = _CACHE.get(url)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1], None

    last_error = ""
    for attempt in range(2):
        try:
            response = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            last_error = str(exc)
            time.sleep(0.5 * (attempt + 1))
            continue
        if response.status_code != 200:
            last_error = "Google Flights returned HTTP %s." % response.status_code
            continue
        html = response.text
        if "ds:1" not in html:
            last_error = "Google Flights returned a page without flight data."
            continue
        _cache_put(url, html)
        return html, None

    return None, "I couldn't reach Google Flights (%s)." % (last_error or "unknown error")


def _cache_put(url: str, html: str) -> None:
    if len(_CACHE) >= 32:
        oldest = min(_CACHE, key=lambda key: _CACHE[key][0])
        _CACHE.pop(oldest, None)
    _CACHE[url] = (time.monotonic(), html)


def _time_pair(value: Any) -> Tuple[int, int]:
    """Google drops trailing zero components; ``[8]`` is 08:00, ``[None, 31]`` is 00:31."""
    padded = [*(value or []), None, None]
    return (padded[0] or 0, padded[1] or 0)


def _parse_html(html: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Extract itineraries from the ``ds:1`` payload embedded in the page."""
    try:
        from selectolax.lexbor import LexborHTMLParser
    except Exception as exc:  # pragma: no cover
        return [], "Flight search needs selectolax (%s)." % exc

    parser = LexborHTMLParser(html)
    node = parser.css_first("script.ds\\:1")
    if node is None:
        return [], "Google Flights returned no result payload."

    try:
        raw = node.text().split("data:", 1)[1].rsplit(",", 1)[0]
        if raw.endswith("errorHasStatus: true"):
            return [], None
        payload = json.loads(raw)
    except Exception:
        return [], "Google Flights returned a result payload I couldn't read."

    if len(payload) < 4 or payload[3] is None:
        return [], None
    rows = payload[3][0]
    if not rows:
        return [], None

    itineraries: List[Dict[str, Any]] = []
    for row in rows:
        try:
            price = row[1][0][1]
        except (IndexError, TypeError):
            # "Price unavailable" rows are not a failure for the whole search.
            continue
        if not isinstance(price, (int, float)) or price <= 0:
            continue

        try:
            flight = row[0]
            airline_names = [str(name) for name in (flight[1] or [])]
            legs = _parse_legs(flight[2] or [])
        except (IndexError, TypeError):
            continue
        if not legs:
            continue

        itineraries.append(
            {
                "price": int(price),
                "airlines": airline_names,
                "airline_code": str(flight[0] or ""),
                "legs": legs,
                "stops": max(0, len(legs) - 1),
                "duration": _total_duration(legs),
            }
        )
    return itineraries, None


def _parse_legs(raw_legs: List[Any]) -> List[Dict[str, Any]]:
    legs: List[Dict[str, Any]] = []
    for item in raw_legs:
        try:
            dep_date = tuple(item[20])
            arr_date = tuple(item[21])
            dep_time = _time_pair(item[8])
            arr_time = _time_pair(item[10])
            legs.append(
                {
                    "from": str(item[3]),
                    "from_name": str(item[4] or ""),
                    "to": str(item[6]),
                    "to_name": str(item[5] or ""),
                    "dep": datetime(dep_date[0], dep_date[1], dep_date[2], dep_time[0], dep_time[1]),
                    "arr": datetime(arr_date[0], arr_date[1], arr_date[2], arr_time[0], arr_time[1]),
                    "minutes": int(item[11] or 0),
                    "plane": str(item[17] or ""),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    return legs


def _total_duration(legs: List[Dict[str, Any]]) -> int:
    """Flight time plus layovers (layovers are same-airport wall-clock gaps)."""
    total = sum(leg["minutes"] for leg in legs)
    for previous, following in zip(legs, legs[1:]):
        gap = int((following["dep"] - previous["arr"]).total_seconds() // 60)
        if 0 < gap < 24 * 60:
            total += gap
    return total


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------


def _money(amount: int, currency: str) -> str:
    return "%s %s" % (currency, format(amount, ","))


def _duration(minutes: int) -> str:
    hours, mins = divmod(max(0, int(minutes)), 60)
    if hours and mins:
        return "%dh %02dm" % (hours, mins)
    if hours:
        return "%dh" % hours
    return "%dm" % mins


def _stops(count: int) -> str:
    if count <= 0:
        return "nonstop"
    return "1 stop" if count == 1 else "%d stops" % count


def _airlines(names: List[str]) -> str:
    unique: List[str] = []
    for name in names:
        if name and name not in unique:
            unique.append(name)
    return " / ".join(unique) if unique else "Unknown airline"


def _format_reply(
    origin: Airport,
    destination: Airport,
    depart: date,
    ret: Optional[date],
    adults: int,
    cabin: str,
    currency: str,
    itineraries: List[Dict[str, Any]],
    total_found: int,
    url: str,
) -> str:
    trip = "round trip" if ret else "one-way"
    dates = depart.strftime("%d %b %Y")
    if ret:
        dates += " → " + ret.strftime("%d %b %Y")

    lines = [
        "%s → %s · %s · %s · %d adult%s · %s · %s"
        % (
            origin.iata,
            destination.iata,
            dates,
            trip,
            adults,
            "" if adults == 1 else "s",
            cabin,
            currency,
        ),
        "Showing %d of %d itineraries from Google Flights (live quotes)." % (len(itineraries), total_found),
        "",
    ]

    for index, item in enumerate(itineraries, 1):
        lines.append(
            "%d. %s total · %s · %s · %s"
            % (
                index,
                _money(item["price"], currency),
                _airlines(item["airlines"]),
                _stops(item["stops"]),
                _duration(item["duration"]),
            )
        )
        for leg in item["legs"]:
            lines.append(
                "   %s %s → %s %s (%s)"
                % (
                    leg["dep"].strftime("%d %b %H:%M"),
                    leg["from"],
                    leg["arr"].strftime("%d %b %H:%M"),
                    leg["to"],
                    _duration(leg["minutes"]),
                )
            )

    cheapest = min(itineraries, key=lambda item: item["price"])
    fast = min(itineraries, key=lambda item: item["duration"])
    lines.extend(
        [
            "",
            "Cheapest: %s (%s, %s). Fastest: %s (%s)."
            % (
                _money(cheapest["price"], currency),
                _airlines(cheapest["airlines"]),
                _stops(cheapest["stops"]),
                _duration(fast["duration"]),
                _money(fast["price"], currency),
            ),
        ]
    )
    if ret:
        lines.append(
            "Round-trip price includes the cheapest return; the itinerary above is the outbound, "
            "so pick the return leg in the booking link."
        )
    lines.extend(
        [
            "Prices are per booking for %d adult%s and change constantly; baggage and seat fees are extra."
            % (adults, "" if adults == 1 else "s"),
            "Google Flights: " + url,
            "Skyscanner: " + _skyscanner_url(origin.iata, destination.iata, depart, ret, adults, cabin, currency),
        ]
    )
    return "\n".join(lines)


def _empty_reply(
    origin: Airport,
    destination: Airport,
    depart: date,
    ret: Optional[date],
    adults: int,
    cabin: str,
    currency: str,
    url: str,
) -> str:
    lines = [
        "No fares found for %s → %s on %s%s (%d adult%s, %s)."
        % (
            origin.iata,
            destination.iata,
            depart.strftime("%d %b %Y"),
            (" → " + ret.strftime("%d %b %Y")) if ret else "",
            adults,
            "" if adults == 1 else "s",
            cabin,
        ),
        "Google Flights returned an empty result set for this route and date.",
    ]

    nearby = nearby_airports(destination, radius_km=350, limit=3)
    if nearby:
        lines.append(
            "Nearest airports: "
            + "; ".join("%s %s (%.0f km)" % (airport.iata, airport.city, distance) for airport, distance in nearby)
        )
        lines.append(
            "Try the search to one of those and book the last leg separately, "
            "or check whether the route needs a different date."
        )

    lines.extend(
        [
            "Check availability: " + url,
            "Skyscanner: " + _skyscanner_url(origin.iata, destination.iata, depart, ret, adults, cabin, currency),
        ]
    )
    return "\n".join(lines)


_SKYSCANNER_DOMAINS = {
    "AUD": "www.skyscanner.com.au",
    "NZD": "www.skyscanner.co.nz",
    "GBP": "www.skyscanner.net",
    "USD": "www.skyscanner.com",
    "SGD": "www.skyscanner.com.sg",
    "HKD": "www.skyscanner.com.hk",
    "CNY": "www.skyscanner.com.cn",
}


def _skyscanner_url(
    origin: str, destination: str, depart: date, ret: Optional[date], adults: int, cabin: str, currency: str = "AUD"
) -> str:
    """A Skyscanner deep link, for a second opinion when a fare looks odd."""
    domain = _SKYSCANNER_DOMAINS.get((currency or "AUD").upper(), "www.skyscanner.net")
    path = "/transport/flights/%s/%s/%s/" % (origin.lower(), destination.lower(), depart.strftime("%y%m%d"))
    if ret:
        path += ret.strftime("%y%m%d") + "/"
    cabin_class = {
        "economy": "economy",
        "premium-economy": "premiumeconomy",
        "business": "business",
        "first": "first",
    }.get(cabin, "economy")
    return "https://%s%s?adults=%d&cabinclass=%s" % (domain, path, adults, cabin_class)
