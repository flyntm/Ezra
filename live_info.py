import re
import xml.etree.ElementTree as ET

import requests

from config import (
    DEFAULT_WEATHER_LOCATION,
    ENABLE_LIVE_INFO,
    LIVE_INFO_TIMEOUT_SECONDS,
    NEWS_HEADLINE_COUNT,
    NEWS_RSS_FEEDS,
    WEATHER_INCLUDE_COUNTRY,
)


def _normalize_location(raw_location):
    if not raw_location:
        return DEFAULT_WEATHER_LOCATION
    return raw_location.strip().replace(" ", "+")


def _extract_weather_location(command):
    # Examples: "weather in dallas", "what's the weather in new york"
    match = re.search(r"\bweather\s+in\s+([a-zA-Z\s]+)", command)
    if match:
        return match.group(1).strip()

    match = re.search(r"\bin\s+([a-zA-Z\s]+)\s+weather\b", command)
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


def _resolve_location_text(payload, requested_location):
    """Return a human-friendly location string from wttr payload."""

    nearest = (payload.get("nearest_area") or [{}])[0]

    city = (nearest.get("areaName") or [{}])[0].get("value", "").strip()
    region = (nearest.get("region") or [{}])[0].get("value", "").strip()
    country = (nearest.get("country") or [{}])[0].get("value", "").strip()

    parts = [city, region]
    if WEATHER_INCLUDE_COUNTRY:
        parts.append(country)

    parts = [part for part in parts if part]
    if parts:
        return ", ".join(parts)

    if requested_location == "auto":
        return "your location"

    return requested_location.replace("+", " ")


def get_weather_summary(command):
    requested_location = _normalize_location(_extract_weather_location(command))
    url = f"https://wttr.in/{requested_location}?format=j1"

    try:
        response = requests.get(url, timeout=LIVE_INFO_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return "I couldn't fetch live weather right now."

    current = (payload.get("current_condition") or [{}])[0]
    description = (current.get("weatherDesc") or [{}])[0].get("value", "unknown")
    temp_f = current.get("temp_F", "?")
    feels_f = current.get("FeelsLikeF", "?")
    humidity = current.get("humidity", "?")
    location_text = _resolve_location_text(payload, requested_location)

    return (
        f"Current weather in {location_text}: {description}, {temp_f} degrees Fahrenheit, "
        f"feels like {feels_f}, humidity {humidity} percent."
    )


def get_news_summary():
    for feed_url in NEWS_RSS_FEEDS:
        try:
            response = requests.get(feed_url, timeout=LIVE_INFO_TIMEOUT_SECONDS)
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except Exception:
            continue

        channel = root.find("channel")
        if channel is None:
            continue

        source = channel.findtext("title", default="the news")
        items = channel.findall("item")

        headlines = []
        for item in items[:NEWS_HEADLINE_COUNT]:
            title = item.findtext("title", default="").strip()
            if title:
                headlines.append(title)

        if headlines:
            joined = "; ".join(headlines)
            return f"Top headlines from {source}: {joined}."

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
