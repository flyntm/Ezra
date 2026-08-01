import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from config import (
    DEFAULT_WEATHER_LOCATION,
    DEFAULT_WEATHER_LATITUDE,
    DEFAULT_WEATHER_LONGITUDE,
    ENABLE_LIVE_INFO,
    LIVE_INFO_TIMEOUT_SECONDS,
    NEWS_HEADLINE_COUNT,
    NEWS_RSS_FEEDS,
    WEATHER_INCLUDE_COUNTRY,
    WEATHER_MAX_OBSERVATION_AGE_MINUTES,
    WEATHER_NWS_USER_AGENT,
    WEATHER_STATION_SEARCH_LIMIT,
)


def _normalize_location(raw_location):
    if not raw_location:
        return DEFAULT_WEATHER_LOCATION
    return raw_location.strip()


def _extract_weather_location(command):
    # Examples: "weather in dallas", "what's the weather in new york"
    match = re.search(r"\bweather\s+in\s+([a-zA-Z,.\s]+)", command)
    if match:
        location = match.group(1).strip(" .,?")
        return re.sub(
            r"\s+(?:today|tonight|tomorrow|currently|right now|please)$",
            "",
            location,
        ).strip()

    match = re.search(r"\bin\s+([a-zA-Z,.\s]+)\s+weather\b", command)
    if match:
        return match.group(1).strip()

    return DEFAULT_WEATHER_LOCATION


def _is_weather_query(command):
    return any(
        phrase in command
        for phrase in (
            "weather",
            "temperature",
            "forecast",
            "rain",
            "snow",
        )
    )


def _is_news_query(command):
    return any(
        phrase in command
        for phrase in (
            "news",
            "headlines",
            "current events",
            "latest events",
            "whats happening",
            "what's happening",
        )
    )


def _geocode_weather_location(requested_location):
    """Return latitude, longitude, label for a U.S. place name."""

    if requested_location.casefold() == DEFAULT_WEATHER_LOCATION.casefold():
        return (
            float(DEFAULT_WEATHER_LATITUDE),
            float(DEFAULT_WEATHER_LONGITUDE),
            DEFAULT_WEATHER_LOCATION,
        )

    response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={
            "name": requested_location,
            "count": 1,
            "language": "en",
            "format": "json",
            "countryCode": "US",
        },
        timeout=LIVE_INFO_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        raise ValueError(f"Weather location not found: {requested_location}")

    result = results[0]
    label_parts = [result.get("name", ""), result.get("admin1", "")]
    if WEATHER_INCLUDE_COUNTRY:
        label_parts.append(result.get("country", ""))
    label = ", ".join(part for part in label_parts if part)

    return float(result["latitude"]), float(result["longitude"]), label


def _nws_get(url):
    response = requests.get(
        url,
        headers={
            "Accept": "application/geo+json",
            "User-Agent": WEATHER_NWS_USER_AGENT,
        },
        timeout=LIVE_INFO_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _parse_nws_timestamp(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _fahrenheit(celsius):
    if celsius is None:
        return None
    return round((float(celsius) * 9.0 / 5.0) + 32.0)


def _latest_fresh_observation(station_urls):
    now = datetime.now(timezone.utc)

    for station_url in station_urls[:WEATHER_STATION_SEARCH_LIMIT]:
        try:
            payload = _nws_get(f"{station_url}/observations/latest")
            observation = payload.get("properties") or {}
            observed_at = _parse_nws_timestamp(observation.get("timestamp"))
            temperature = (observation.get("temperature") or {}).get("value")

            if observed_at is None or temperature is None:
                continue

            age_minutes = (now - observed_at.astimezone(timezone.utc)).total_seconds() / 60
            if age_minutes < -10 or age_minutes > WEATHER_MAX_OBSERVATION_AGE_MINUTES:
                continue

            return observation, observed_at
        except Exception:
            continue

    raise RuntimeError("No fresh NWS station observation was available")


def get_weather_summary(command):
    requested_location = _normalize_location(_extract_weather_location(command))

    try:
        latitude, longitude, location_text = _geocode_weather_location(
            requested_location
        )
        point = (_nws_get(f"https://api.weather.gov/points/{latitude},{longitude}")
                 .get("properties") or {})
        stations_payload = _nws_get(point["observationStations"])
        station_urls = [
            feature.get("id")
            for feature in stations_payload.get("features") or []
            if feature.get("id")
        ]
        current, observed_at = _latest_fresh_observation(station_urls)
    except Exception:
        return "I couldn't fetch live weather right now."

    description = current.get("textDescription") or "unknown conditions"
    temp_f = _fahrenheit((current.get("temperature") or {}).get("value"))
    feels_c = (current.get("heatIndex") or {}).get("value")
    if feels_c is None:
        feels_c = (current.get("windChill") or {}).get("value")
    feels_f = _fahrenheit(feels_c)
    humidity = (current.get("relativeHumidity") or {}).get("value")

    try:
        local_time = observed_at.astimezone(ZoneInfo(point["timeZone"]))
    except Exception:
        local_time = observed_at

    observed_text = local_time.strftime("%-I:%M %p")
    details = f"{description}, {temp_f} degrees Fahrenheit"
    if feels_f is not None:
        details += f", feels like {feels_f}"
    if humidity is not None:
        details += f", humidity {round(float(humidity))} percent"

    return (
        f"Current weather in {location_text}, observed at {observed_text}: "
        f"{details}."
    )


def _normalize_headline(title):
    """Normalize headline text for simple cross-source dedupe."""

    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _get_feed_headlines(feed_url):
    try:
        response = requests.get(feed_url, timeout=LIVE_INFO_TIMEOUT_SECONDS)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception:
        return None, []

    channel = root.find("channel")
    if channel is None:
        return None, []

    source = channel.findtext("title", default="the news").strip() or "the news"
    items = channel.findall("item")

    headlines = []
    for item in items:
        title = item.findtext("title", default="").strip()
        if title:
            headlines.append(title)

    return source, headlines


def get_news_summary():
    seen_headlines = set()
    source_summaries = []

    with ThreadPoolExecutor(max_workers=len(NEWS_RSS_FEEDS)) as executor:
        feed_results = list(executor.map(_get_feed_headlines, NEWS_RSS_FEEDS))

    for source, headlines in feed_results:
        unique_headlines = []

        for title in headlines:
            normalized_title = _normalize_headline(title)
            if not normalized_title or normalized_title in seen_headlines:
                continue

            seen_headlines.add(normalized_title)
            unique_headlines.append(title)

            if len(unique_headlines) >= NEWS_HEADLINE_COUNT:
                break

        if not unique_headlines:
            continue

        joined = "; ".join(unique_headlines)
        source_summaries.append(f"From {source}: {joined}")

    if source_summaries:
        return "Top headlines. " + ". ".join(source_summaries) + "."

    return "I couldn't fetch live news right now."


def get_live_info_response(command):
    """Return a live weather/news response string, or None if not a live-info query."""

    if not ENABLE_LIVE_INFO:
        return None

    wants_weather = _is_weather_query(command)
    wants_news = _is_news_query(command)

    if not wants_weather and not wants_news:
        return None

    parts = []

    if wants_weather:
        parts.append(get_weather_summary(command))

    if wants_news:
        parts.append(get_news_summary())

    return " ".join(part for part in parts if part)
