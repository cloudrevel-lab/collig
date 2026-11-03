---
name: Flight Search
description: Search live flight prices and itineraries for one-way or round-trip routes, with airline, times, stops and duration (Google Flights, no API key)
version: 1.0.0
author: Collig Team
license: MIT

tools:
  - name: search_flights
    description: Search live flight prices and itineraries between two airports
  - name: find_airport
    description: Look up the IATA code and name of an airport or city

config:
  required: []
  optional:
    - "FLIGHT_DEFAULT_CURRENCY (default AUD)"

triggers:
  - flight
  - flights
  - airfare
  - air fare
  - air ticket
  - air tickets
  - plane ticket
  - plane tickets
  - flight search
  - cheapest flight
  - round trip
  - round-trip
  - one way
  - one-way
  - fly to
  - flying to
  - skyscanner
  - google flights
  # Chinese: a request like "从悉尼到大同云冈机场…经济舱，不限转机" says
  # neither "flight" nor "航班", so the router needs the travel vocabulary.
  - 航班
  - 机票
  - 飞机票
  - 飞机
  - 机场
  - 航空
  - 转机
  - 中转
  - 直飞
  - 经济舱
  - 商务舱
  - 头等舱
  - 往返
  - 单程
  - 飞往
  - 航线
---

# Flight Search Skill

Live fare search that behaves like the Skyscanner / Google Flights result list:
resolve the airports, ask for the route, and return ranked itineraries with
price, airline, stops, times and duration for the whole party.

No API key and no account. The skill reads the same search page a browser
would, so a quote is a real live fare rather than an invented number.

## Usage

Use this skill when the user asks to:

- find or compare flights between two places ("flights from Sydney to Datong")
- price a trip for a number of passengers ("2 adults, 19 Dec to 8 Jan")
- check a specific route, date, cabin or stop count
- find the airport behind a city name ("which airport is Datong?")

## Tools

### search_flights(...)

Search one-way or round-trip itineraries.

| Argument | Meaning |
| --- | --- |
| `origin` | City or IATA code, e.g. `Sydney`, `SYD` |
| `destination` | City or IATA code, e.g. `Datong`, `DAT` |
| `depart_date` | `2026-12-19`, `19 Dec 2026`, `19/12/2026` |
| `return_date` | Return date for a round trip; empty for one-way |
| `adults` | 1-9 |
| `cabin` | `economy`, `premium-economy`, `business`, `first` |
| `max_stops` | `-1` any, `0` nonstop, `1` at most one stop |
| `currency` | `AUD`, `USD`, `CNY`, ... (default from config, else AUD) |
| `sort` | `price` or `duration` |
| `limit` | 1-20 itineraries |

Returns a ranked list plus a Google Flights link and a Skyscanner link.

### find_airport(query)

Resolve a city or airport name to an IATA code, and list other airports in the
same city. Use it before a search when the place is ambiguous (Beijing has PEK
and PKX; London has five).

## Behaviour worth knowing

- **Round trips**: Google prices the whole trip but renders the *outbound*
  options first. The listed itinerary is the outbound leg and the price already
  includes the cheapest return, so the reply says so and links out to pick the
  return. Do not present the outbound leg as the complete itinerary.
- **Empty results are normal for small airports.** Datong (DAT) has very little
  through-fare inventory, so the skill reports that honestly and lists nearby
  airports (Taiyuan, Hohhot) instead of inventing a connection.
- **Round trip with no through-fare**: the skill then prices the outbound as a
  one-way, because Google often carries one-way inventory without a return
  combination. The reply labels it as one-way and says the return needs its own
  search — it never passes a one-way total off as a round-trip price.
- **Prices are per booking for the party**, in the requested currency, and
  change constantly. Baggage and seat fees are not included.
- **Airport resolution is offline** (`airportsdata`, ~7.9k IATA airports), so it
  is fast, deterministic and testable without network access. Chinese city and
  airport names resolve too (`悉尼`, `大同云冈机场`, `北京大兴`), including names
  with a trailing `机场`/`国际机场`.

## Failure handling

Every failure returns a sentence, never an exception: an unreadable date, an
unknown city, a network error, a Google page without data, or a route with no
fares. A failed tool call aborts the whole ADK invocation, so the skill keeps
the error inside the tool result.

## Notes

- Uses Google Flights' public search page. It is not an official API and has no
  SLA; if it changes shape the skill degrades to "no fares found" plus links
  rather than wrong prices.
- For an official, licensed feed, swap in Amadeus Self-Service, Duffel or Kiwi
  behind the same `search_flights` signature (see AGENT.md, "Public APIs for new
  skills"). Those need a key and a contract; this one works out of the box.
