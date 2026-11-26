"""Stdlib-only live weather and web lookup service for BuddyAI."""

from datetime import date, datetime
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from buddyai.exceptions import DataSourceError, InvalidInputError

_WMO_WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


# Encapsulation & Dependency Injection: wraps free public HTTP lookup APIs behind an injectable fetcher.
class WebLookup:
    """Provides live weather (Open-Meteo) and web search (Wikipedia + Google News RSS)."""

    USER_AGENT = "BuddyAI/1.0 (IT121AL Executive Assistant)"
    TIMEOUT_SECONDS = 8

    def __init__(self, fetcher=None):
        self._fetcher = fetcher
        self._geo_cache = {}

    def _fetch_text(self, url):
        """Fetch UTF-8 text from url using the injected fetcher or urllib."""
        if self._fetcher is not None:
            return self._fetcher(url)
        request = urllib.request.Request(
            url, headers={"User-Agent": self.USER_AGENT}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.TIMEOUT_SECONDS
            ) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DataSourceError(
                f"Could not reach web service ({exc}). Check your internet connection."
            ) from exc

    @staticmethod
    def _clean_html(text):
        plain = re.sub(r"<[^>]+>", "", text or "")
        return " ".join(html.unescape(plain).split())

    @staticmethod
    def _to_weather_timezone(target, tz_name):
        """Convert an aware datetime to the location's timezone when available."""
        if not isinstance(target, datetime) or target.tzinfo is None or not tz_name:
            return target
        try:
            return target.astimezone(ZoneInfo(tz_name))
        except ZoneInfoNotFoundError:
            return target

    @staticmethod
    def _indexed_value(mapping, key, index):
        values = mapping.get(key) or []
        if 0 <= index < len(values):
            return values[index]
        return None

    @staticmethod
    def _is_close_to_current(target_dt, current_time_text):
        """Return True if target_dt is within 45 minutes of Open-Meteo's current time."""
        if not current_time_text:
            return False
        try:
            current_dt = datetime.fromisoformat(current_time_text)
        except ValueError:
            return False
        naive_target = target_dt.replace(tzinfo=None)
        naive_current = current_dt.replace(tzinfo=None)
        return abs((naive_target - naive_current).total_seconds()) <= 45 * 60

    @staticmethod
    def _format_weather_summary(
        display_location,
        condition,
        temp_c,
        feels_c,
        humidity,
        wind_kmh,
        high_c,
        low_c,
        rain_chance,
        time_label="",
        hour_rain=None,
        day_label="Today's",
    ):
        heading = f"{display_location} ({time_label})" if time_label else display_location
        if temp_c is not None:
            parts = [f"{condition}, {temp_c}°C"]
            if feels_c is not None:
                parts[0] += f" (feels like {feels_c}°C)"
            if humidity is not None:
                parts.append(f"humidity {humidity}%")
            if wind_kmh is not None:
                parts.append(f"wind {wind_kmh} km/h")
            if hour_rain is not None:
                parts.append(f"rain chance {hour_rain}%")
            summary = f"{heading}: {', '.join(parts)}"
        else:
            summary = f"{heading}: Forecast"

        outlook = []
        if high_c is not None and low_c is not None:
            outlook.append(f"{day_label} high {high_c}°C, low {low_c}°C")
        if rain_chance is not None:
            prefix = "rain chance" if outlook else f"{day_label} rain chance"
            outlook.append(f"{prefix} {rain_chance}%")
        if outlook:
            if temp_c is not None:
                summary += f". {', '.join(outlook)}"
            else:
                summary += f" — {', '.join(outlook)}"
        return summary + "."

    def _resolve_location(self, place):
        """Resolve a place name to (latitude, longitude, display_location) with caching."""
        cache_key = place.lower()
        cached = self._geo_cache.get(cache_key)
        if cached is not None:
            return cached

        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": place, "count": 1, "language": "en"})
        )
        try:
            geo_data = json.loads(self._fetch_text(geo_url))
        except ValueError as exc:
            raise DataSourceError("Weather geocoding returned invalid JSON.") from exc

        results = geo_data.get("results") or []
        if not results:
            raise InvalidInputError(f"Could not find a location named '{place}'.")

        match = results[0]
        lat = match["latitude"]
        lon = match["longitude"]
        resolved_name = match.get("name", place)
        country = match.get("country", "")
        admin1 = match.get("admin1", "")
        display_parts = [p for p in (resolved_name, admin1, country) if p]
        display_location = ", ".join(dict.fromkeys(display_parts))
        resolved = (lat, lon, display_location)
        self._geo_cache[cache_key] = resolved
        return resolved

    def get_weather(self, location, at_time=None):
        """Return live weather or forecast for `location` (optionally at `at_time`) via Open-Meteo."""
        place = (location or "").strip()
        if not place:
            raise InvalidInputError("Location cannot be empty.")

        lat, lon, display_location = self._resolve_location(place)

        weather_url = (
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "current": (
                        "temperature_2m,apparent_temperature,"
                        "relative_humidity_2m,weather_code,wind_speed_10m"
                    ),
                    "hourly": (
                        "temperature_2m,apparent_temperature,"
                        "relative_humidity_2m,weather_code,"
                        "wind_speed_10m,precipitation_probability"
                    ),
                    "daily": (
                        "temperature_2m_max,temperature_2m_min,"
                        "precipitation_probability_max"
                    ),
                    "timezone": "auto",
                    "forecast_days": 7,
                }
            )
        )
        try:
            weather_data = json.loads(self._fetch_text(weather_url))
        except ValueError as exc:
            raise DataSourceError("Weather forecast returned invalid JSON.") from exc

        weather_tz = weather_data.get("timezone", "")
        current = weather_data.get("current") or {}
        hourly = weather_data.get("hourly") or {}
        daily = weather_data.get("daily") or {}

        daily_times = daily.get("time") or []
        hourly_times = hourly.get("time") or []

        target_dt = self._to_weather_timezone(at_time, weather_tz)
        target_label = ""
        hour_idx = None
        day_idx = 0
        use_current = True

        if isinstance(target_dt, datetime):
            target_day_str = target_dt.strftime("%Y-%m-%d")
            target_hour_str = target_dt.strftime("%Y-%m-%dT%H:00")
            target_label = target_dt.strftime("%Y-%m-%d %H:%M")
            if daily_times:
                day_idx = daily_times.index(target_day_str) if target_day_str in daily_times else None
            if not self._is_close_to_current(target_dt, current.get("time", "")):
                if target_hour_str in hourly_times:
                    hour_idx = hourly_times.index(target_hour_str)
                    use_current = False
                elif day_idx is not None and daily_times:
                    use_current = False
                elif daily_times or hourly_times:
                    raise DataSourceError(
                        f"Weather forecast for {target_label} is outside the 7-day forecast range."
                    )
        elif isinstance(target_dt, date):
            target_day_str = target_dt.strftime("%Y-%m-%d")
            target_label = target_day_str
            if daily_times:
                day_idx = daily_times.index(target_day_str) if target_day_str in daily_times else None
            midday_hour = f"{target_day_str}T12:00"
            if midday_hour in hourly_times:
                hour_idx = hourly_times.index(midday_hour)
                use_current = False
            elif day_idx is not None and daily_times:
                use_current = False
            elif daily_times or hourly_times:
                raise DataSourceError(
                    f"Weather forecast for {target_label} is outside the 7-day forecast range."
                )

        if use_current:
            code = current.get("weather_code")
            condition = _WMO_WEATHER_CODES.get(code, f"Weather code {code}")
            temp_c = current.get("temperature_2m")
            feels_c = current.get("apparent_temperature")
            humidity = current.get("relative_humidity_2m")
            wind_kmh = current.get("wind_speed_10m")
            observed_at = current.get("time", "")
            hour_rain = None
        elif hour_idx is not None:
            code = self._indexed_value(hourly, "weather_code", hour_idx)
            condition = _WMO_WEATHER_CODES.get(code, f"Weather code {code}")
            temp_c = self._indexed_value(hourly, "temperature_2m", hour_idx)
            feels_c = self._indexed_value(hourly, "apparent_temperature", hour_idx)
            humidity = self._indexed_value(hourly, "relative_humidity_2m", hour_idx)
            wind_kmh = self._indexed_value(hourly, "wind_speed_10m", hour_idx)
            observed_at = hourly_times[hour_idx]
            hour_rain = self._indexed_value(hourly, "precipitation_probability", hour_idx)
        else:
            condition = "Daily forecast"
            temp_c = None
            feels_c = None
            humidity = None
            wind_kmh = None
            observed_at = target_label
            hour_rain = None

        today_high = self._indexed_value(daily, "temperature_2m_max", day_idx) if day_idx is not None else None
        today_low = self._indexed_value(daily, "temperature_2m_min", day_idx) if day_idx is not None else None
        rain_chance = (
            self._indexed_value(daily, "precipitation_probability_max", day_idx)
            if day_idx is not None
            else None
        )
        day_label = "Day" if target_label else "Today's"

        summary = self._format_weather_summary(
            display_location=display_location,
            condition=condition,
            temp_c=temp_c,
            feels_c=feels_c,
            humidity=humidity,
            wind_kmh=wind_kmh,
            high_c=today_high,
            low_c=today_low,
            rain_chance=rain_chance,
            time_label=target_label,
            hour_rain=hour_rain,
            day_label=day_label,
        )

        return {
            "location": display_location,
            "timezone": weather_tz,
            "observed_at": observed_at,
            "target_time": target_label,
            "condition": condition,
            "temperature_c": temp_c,
            "feels_like_c": feels_c,
            "humidity_percent": humidity,
            "wind_kmh": wind_kmh,
            "today_high_c": today_high,
            "today_low_c": today_low,
            "rain_chance_percent": rain_chance,
            "summary": summary,
        }

    def _parse_rss_items(self, raw_xml, limit):
        """Parse up to `limit` non-empty RSS items from Google News XML."""
        root = ET.fromstring(raw_xml)
        results = []
        for item in root.findall(".//item"):
            if len(results) >= limit:
                break
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source_el = item.find("source")
            source = (source_el.text or "").strip() if source_el is not None else "Google News"
            snippet = self._clean_html(item.findtext("description") or "")
            results.append(
                {
                    "title": title,
                    "snippet": snippet or title,
                    "source": source,
                    "published": pub_date,
                    "url": link,
                }
            )
        return results

    def _search_news(self, query, limit):
        url = (
            "https://news.google.com/rss/search?"
            + urllib.parse.urlencode(
                {"q": query, "hl": "en-PH", "gl": "PH", "ceid": "PH:en"}
            )
        )
        return self._parse_rss_items(self._fetch_text(url), limit)

    def get_headlines(self, limit=5, country="PH"):
        """Fetch the top `limit` news headlines for `country` (default Philippines) via Google News RSS."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise InvalidInputError("Headline limit must be a positive integer.")
        code = (country or "").strip().upper()
        if not code:
            raise InvalidInputError("Country code cannot be empty.")

        url = (
            "https://news.google.com/rss?"
            + urllib.parse.urlencode(
                {"hl": f"en-{code}", "gl": code, "ceid": f"{code}:en"}
            )
        )
        try:
            items = self._parse_rss_items(self._fetch_text(url), limit)
        except ET.ParseError as exc:
            raise DataSourceError("Headlines feed returned invalid XML.") from exc

        return {
            "country": code,
            "headlines": items,
            "summary": f"Found {len(items)} top headline(s) for {code}.",
        }

    def _search_wikipedia(self, query, limit):
        url = (
            "https://en.wikipedia.org/w/api.php?"
            + urllib.parse.urlencode(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": limit,
                    "format": "json",
                }
            )
        )
        data = json.loads(self._fetch_text(url))
        items = data.get("query", {}).get("search") or []
        results = []
        for entry in items[:limit]:
            title = (entry.get("title") or "").strip()
            snippet = self._clean_html(entry.get("snippet") or "")
            slug = urllib.parse.quote(title.replace(" ", "_"))
            results.append(
                {
                    "title": title,
                    "snippet": snippet,
                    "source": "Wikipedia",
                    "published": entry.get("timestamp", ""),
                    "url": f"https://en.wikipedia.org/wiki/{slug}" if title else "",
                }
            )
        return results

    def search_web(self, query, max_results=5):
        """Search live news (Google News RSS) and factual summaries (Wikipedia)."""
        cleaned = (query or "").strip()
        if not cleaned:
            raise InvalidInputError("Search query cannot be empty.")

        news_limit = max(1, (max_results + 1) // 2)
        wiki_limit = max(1, max_results - news_limit)

        results = []
        errors = []

        try:
            results.extend(self._search_news(cleaned, news_limit))
        except (DataSourceError, ET.ParseError, ValueError) as exc:
            errors.append(str(exc))

        try:
            results.extend(self._search_wikipedia(cleaned, wiki_limit))
        except (DataSourceError, ValueError) as exc:
            errors.append(str(exc))

        if not results and errors:
            raise DataSourceError(errors[0])

        return {
            "query": cleaned,
            "results": results[:max_results],
            "summary": f"Found {len(results[:max_results])} web result(s) for '{cleaned}'.",
        }
