"""Offline unit tests for WebLookup (Open-Meteo weather, Google News RSS, Wikipedia) and toolkit wiring."""

from datetime import date, datetime, timezone
import http.client
import json
import logging
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from buddyai.briefing import BriefingService
from buddyai.document_reader import DocumentReader
from buddyai.exceptions import DataSourceError, InvalidInputError
from buddyai.models import Reminder, Task
from buddyai.sources import JsonStore
from buddyai.toolkit import BuddyToolkit
from buddyai.web_lookup import WebLookup
from buddyai.workspace import Workspace

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(2026, 11, 27, 1, 30, tzinfo=MANILA)

_SAMPLE_GEO = json.dumps(
    {
        "results": [
            {
                "name": "Manila",
                "admin1": "Metro Manila",
                "country": "Philippines",
                "latitude": 14.6042,
                "longitude": 120.9822,
            }
        ]
    }
)

_SAMPLE_WEATHER = json.dumps(
    {
        "timezone": "Asia/Manila",
        "current": {
            "time": "2026-11-27T01:15",
            "temperature_2m": 28.0,
            "apparent_temperature": 31.7,
            "relative_humidity_2m": 69,
            "weather_code": 2,
            "wind_speed_10m": 7.5,
        },
        "hourly": {
            "time": [
                "2026-11-27T01:00",
                "2026-11-27T15:00",
                "2026-11-28T12:00",
            ],
            "temperature_2m": [27.5, 32.5, 31.0],
            "apparent_temperature": [31.0, 36.2, 34.0],
            "relative_humidity_2m": [72, 58, 62],
            "weather_code": [2, 80, 1],
            "wind_speed_10m": [7.0, 12.5, 9.0],
            "precipitation_probability": [10, 65, 20],
        },
        "daily": {
            "time": ["2026-11-27", "2026-11-28"],
            "temperature_2m_max": [34.4, 33.8],
            "temperature_2m_min": [25.1, 24.9],
            "precipitation_probability_max": [40, 20],
        },
    }
)

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Manila forecast stays warm - Daily News</title>
    <link>https://example.com/news1</link>
    <pubDate>Fri, 27 Nov 2026 00:00:00 GMT</pubDate>
    <description>&lt;b&gt;Warm weather&lt;/b&gt; expected across Metro Manila.</description>
    <source>Daily News</source>
  </item>
</channel></rss>"""

_SAMPLE_PH_HEADLINES_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Metro Manila transport upgrade begins - Inquirer</title>
    <link>https://example.com/ph1</link>
    <pubDate>Fri, 27 Nov 2026 00:00:00 GMT</pubDate>
    <description>New commuter lines open.</description>
    <source>Inquirer</source>
  </item>
  <item>
    <title>BSP holds policy rates steady</title>
    <link>https://example.com/ph2</link>
    <pubDate>Fri, 27 Nov 2026 01:00:00 GMT</pubDate>
    <description>Central bank cites stable inflation.</description>
    <source>Philstar</source>
  </item>
  <item>
    <title>[WATCH] PAGASA monitors tropical trough - ABS-CBN News</title>
    <link>https://example.com/ph3</link>
    <pubDate>Fri, 27 Nov 2026 01:30:00 GMT</pubDate>
    <description>Scattered rain expected in Visayas.</description>
    <source>ABS-CBN News</source>
  </item>
  <item>
    <title>DOE expands solar grid capacity - GMA News</title>
    <link>https://example.com/ph4</link>
    <pubDate>Fri, 27 Nov 2026 01:45:00 GMT</pubDate>
    <description>New Luzon solar plants go online.</description>
    <source>GMA News</source>
  </item>
  <item>
    <title>Gilas Pilipinas finalizes roster - Rappler</title>
    <link>https://example.com/ph5</link>
    <pubDate>Fri, 27 Nov 2026 02:00:00 GMT</pubDate>
    <description>Team prepares for upcoming qualifiers.</description>
    <source>Rappler</source>
  </item>
  <item>
    <title>Sixth headline should be excluded - Manila Bulletin</title>
    <link>https://example.com/ph6</link>
    <pubDate>Fri, 27 Nov 2026 02:15:00 GMT</pubDate>
    <description>Extra item.</description>
    <source>Manila Bulletin</source>
  </item>
</channel></rss>"""

_SAMPLE_WIKI = json.dumps(
    {
        "query": {
            "search": [
                {
                    "title": "Manila",
                    "snippet": "Manila is the <span class='searchmatch'>capital</span> of the Philippines.",
                    "timestamp": "2026-11-20T00:00:00Z",
                }
            ]
        }
    }
)


def _fake_fetcher(url):
    if "geocoding-api.open-meteo.com" in url:
        return _SAMPLE_GEO
    if "api.open-meteo.com" in url:
        return _SAMPLE_WEATHER
    if "news.google.com/rss/search" in url:
        return _SAMPLE_RSS
    if "news.google.com/rss?" in url:
        return _SAMPLE_PH_HEADLINES_RSS
    if "en.wikipedia.org" in url:
        return _SAMPLE_WIKI
    raise DataSourceError(f"Unexpected URL: {url}")


class TestWebLookup(unittest.TestCase):
    """Checks offline weather and web search parsing and error handling."""

    def test_get_weather_parses_geocoding_and_forecast_cleanly(self):
        lookup = WebLookup(fetcher=_fake_fetcher)
        weather = lookup.get_weather("Manila")
        self.assertEqual(weather["location"], "Manila, Metro Manila, Philippines")
        self.assertEqual(weather["condition"], "Partly cloudy")
        self.assertEqual(weather["temperature_c"], 28.0)
        self.assertEqual(weather["today_high_c"], 34.4)
        self.assertIn("28.0°C", weather["summary"])

    def test_get_weather_rejects_empty_location_and_unknown_place(self):
        lookup = WebLookup(fetcher=lambda url: json.dumps({"results": []}))
        with self.assertRaises(InvalidInputError):
            lookup.get_weather("   ")
        with self.assertRaises(InvalidInputError):
            lookup.get_weather("Atlantis999")

    def test_search_web_combines_news_and_wikipedia_and_strips_html(self):
        lookup = WebLookup(fetcher=_fake_fetcher)
        payload = lookup.search_web("Manila")
        self.assertEqual(payload["query"], "Manila")
        sources = {r["source"] for r in payload["results"]}
        self.assertIn("Daily News", sources)
        self.assertIn("Wikipedia", sources)
        for item in payload["results"]:
            self.assertNotIn("<span", item["snippet"])
            self.assertNotIn("<b>", item["snippet"])

    def test_search_web_falls_back_when_one_provider_fails(self):
        def _wiki_only(url):
            if "news.google.com" in url:
                raise DataSourceError("news offline")
            return _SAMPLE_WIKI

        lookup = WebLookup(fetcher=_wiki_only)
        payload = lookup.search_web("Manila")
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["source"], "Wikipedia")

    def test_search_web_raises_data_source_error_when_all_providers_fail(self):
        def _offline(url):
            raise DataSourceError("no internet")

        lookup = WebLookup(fetcher=_offline)
        with self.assertRaises(DataSourceError):
            lookup.search_web("Manila")

    def test_toolkit_exposes_safe_get_weather_and_search_web_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(sources=[JsonStore(tmpdir)])
            tk = BuddyToolkit(
                ws,
                BriefingService(ws),
                DocumentReader(model="gemini-3.5-flash-lite", clock=lambda: NOW),
                clock=lambda: NOW,
                web_lookup=WebLookup(fetcher=_fake_fetcher),
            )
            w = tk.get_weather("Manila")
            self.assertEqual(w["status"], "success")
            self.assertEqual(w["weather"]["condition"], "Partly cloudy")

            s = tk.search_web("Manila")
            self.assertEqual(s["status"], "success")
            self.assertGreaterEqual(len(s["results"]), 2)

            bad = tk.get_weather("")
            self.assertEqual(bad["status"], "error")
            self.assertEqual(bad["error_type"], "InvalidInputError")

    def test_get_weather_at_particular_time_uses_hourly_forecast(self):
        lookup = WebLookup(fetcher=_fake_fetcher)
        afternoon = datetime(2026, 11, 27, 15, 0, tzinfo=MANILA)
        weather = lookup.get_weather("Manila", at_time=afternoon)
        self.assertEqual(weather["target_time"], "2026-11-27 15:00")
        self.assertEqual(weather["condition"], "Slight rain showers")
        self.assertEqual(weather["temperature_c"], 32.5)
        self.assertIn("2026-11-27 15:00", weather["summary"])
        self.assertIn("rain chance 65%", weather["summary"])

    def test_get_weather_for_future_date_uses_midday_forecast(self):
        lookup = WebLookup(fetcher=_fake_fetcher)
        weather = lookup.get_weather("Manila", at_time=date(2026, 11, 28))
        self.assertEqual(weather["target_time"], "2026-11-28")
        self.assertEqual(weather["condition"], "Mainly clear")
        self.assertEqual(weather["today_high_c"], 33.8)
        self.assertIn("2026-11-28", weather["summary"])

    def test_get_headlines_returns_top_five_philippines_headlines(self):
        lookup = WebLookup(fetcher=_fake_fetcher)
        payload = lookup.get_headlines(country="PH")
        self.assertEqual(payload["country"], "PH")
        self.assertEqual(len(payload["headlines"]), 5)
        self.assertIn("Metro Manila transport upgrade begins", payload["headlines"][0]["title"])
        self.assertIn("Gilas Pilipinas finalizes roster", payload["headlines"][4]["title"])

    def test_briefing_includes_schedule_weather_at_time_and_top_five_clickable_ph_headlines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(sources=[JsonStore(tmpdir)])
            ws.tasks.add_task(Task("Submit capstone deck", NOW, due_date=NOW), NOW)
            lookup = WebLookup(fetcher=_fake_fetcher)
            briefing_svc = BriefingService(ws, web_lookup=lookup)
            tk = BuddyToolkit(
                ws,
                briefing_svc,
                DocumentReader(model="gemini-3.5-flash-lite", clock=lambda: NOW),
                clock=lambda: NOW,
                web_lookup=lookup,
            )

            res = tk.get_daily_briefing(at_time="15:00")
            self.assertEqual(res["status"], "success")
            text = res["briefing_text"]
            self.assertIn("Daily Briefing for Friday, November 27, 2026 at 3:00 PM", text)
            self.assertIn("Submit capstone deck", text)
            self.assertIn("2026-11-27 15:00", text)
            self.assertIn("32.5°C", text)
            self.assertIn("### Top 5 Headlines (Philippines)", text)
            self.assertIn(
                "[Metro Manila transport upgrade begins - Inquirer](https://example.com/ph1)",
                text,
            )
            self.assertIn(
                "[BSP holds policy rates steady (Philstar)](https://example.com/ph2)",
                text,
            )
            self.assertIn(
                r"[\[WATCH\] PAGASA monitors tropical trough - ABS-CBN News](https://example.com/ph3)",
                text,
            )
            self.assertIn(
                "[DOE expands solar grid capacity - GMA News](https://example.com/ph4)",
                text,
            )
            self.assertIn(
                "[Gilas Pilipinas finalizes roster - Rappler](https://example.com/ph5)",
                text,
            )
            self.assertNotIn("Sixth headline", text)
            self.assertEqual(len(res["headlines"]), 5)

    def test_briefing_keeps_schedule_when_weather_and_headlines_are_offline(self):
        def _offline(url):
            raise DataSourceError("No internet connection.")

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(sources=[JsonStore(tmpdir)])
            ws.tasks.add_task(Task("Submit capstone deck", NOW, due_date=NOW), NOW)
            briefing = BriefingService(ws, web_lookup=WebLookup(fetcher=_offline)).build_briefing(NOW)
            text = briefing.to_text()
            self.assertIn("Submit capstone deck", text)
            self.assertIn("### Weather\nUnavailable", text)
            self.assertIn("### Top 5 Headlines (Philippines)\nUnavailable", text)

    def test_get_weather_rejects_out_of_range_date_and_datetime(self):
        lookup = WebLookup(fetcher=_fake_fetcher)
        with self.assertRaises(DataSourceError):
            lookup.get_weather("Manila", at_time=date(2026, 12, 10))
        with self.assertRaises(DataSourceError):
            lookup.get_weather("Manila", at_time=datetime(2026, 12, 10, 15, 0, tzinfo=MANILA))
        with self.assertRaises(DataSourceError):
            lookup.get_weather("Manila", at_time=date(2026, 11, 20))

    def test_get_weather_converts_utc_at_time_to_location_timezone(self):
        lookup = WebLookup(fetcher=_fake_fetcher)
        # 07:00 UTC == 15:00 Asia/Manila
        utc_afternoon = datetime(2026, 11, 27, 7, 0, tzinfo=timezone.utc)
        weather = lookup.get_weather("Manila", at_time=utc_afternoon)
        self.assertEqual(weather["target_time"], "2026-11-27 15:00")
        self.assertEqual(weather["temperature_c"], 32.5)

    def test_get_weather_caches_geocoding_for_repeated_location(self):
        geo_calls = []

        def _counting_fetcher(url):
            if "geocoding-api.open-meteo.com" in url:
                geo_calls.append(url)
            return _fake_fetcher(url)

        lookup = WebLookup(fetcher=_counting_fetcher)
        lookup.get_weather("Manila")
        lookup.get_weather("manila")
        self.assertEqual(len(geo_calls), 1)

    def test_get_headlines_skips_empty_titles_before_applying_limit(self):
        rss_with_blank = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item><title>   </title><source>Empty</source></item>
          <item><title>First real headline - Inquirer</title><source>Inquirer</source></item>
          <item><title></title><source>Blank</source></item>
          <item><title>Second real headline - Rappler</title><source>Rappler</source></item>
          <item><title>Third real headline - Philstar</title><source>Philstar</source></item>
          <item><title>Fourth headline - GMA</title><source>GMA</source></item>
        </channel></rss>"""
        lookup = WebLookup(fetcher=lambda url: rss_with_blank)
        payload = lookup.get_headlines(limit=3, country="PH")
        self.assertEqual(len(payload["headlines"]), 3)
        self.assertEqual(
            [h["title"] for h in payload["headlines"]],
            [
                "First real headline - Inquirer",
                "Second real headline - Rappler",
                "Third real headline - Philstar",
            ],
        )

    def test_get_headlines_validates_inputs_and_handles_invalid_xml(self):
        lookup = WebLookup(fetcher=lambda url: "<not-xml")
        with self.assertRaises(InvalidInputError):
            lookup.get_headlines(limit=0)
        with self.assertRaises(InvalidInputError):
            lookup.get_headlines(limit=True)
        with self.assertRaises(InvalidInputError):
            lookup.get_headlines(limit=3, country="  ")
        with self.assertRaises(DataSourceError):
            lookup.get_headlines(limit=3, country="PH")

    def test_briefing_at_later_time_today_keeps_real_clock_for_reminders_and_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(sources=[JsonStore(tmpdir)])
            ws.tasks.add_reminder(
                Reminder("Lunch check-in", NOW, datetime(2026, 11, 27, 13, 0, tzinfo=MANILA)),
                NOW,
            )
            ws.tasks.add_task(
                Task("Send report", NOW, due_date=datetime(2026, 11, 27, 14, 0, tzinfo=MANILA)),
                NOW,
            )
            lookup = WebLookup(fetcher=_fake_fetcher)
            tk = BuddyToolkit(
                ws,
                BriefingService(ws, web_lookup=lookup),
                DocumentReader(model="gemini-3.5-flash-lite", clock=lambda: NOW),
                clock=lambda: NOW,
                web_lookup=lookup,
            )
            res = tk.get_daily_briefing(at_time="15:00")
            self.assertEqual(res["status"], "success")
            self.assertIn("2026-11-27 15:00", res["briefing_text"])
            self.assertNotIn("[time has passed]", res["briefing_text"])
            self.assertEqual(res["target_time"], "2026-11-27T15:00:00+08:00")

    def test_briefing_partial_live_failure_and_headline_encapsulation(self):
        def _headlines_down(url):
            if "news.google.com" in url:
                raise DataSourceError("RSS down")
            return _fake_fetcher(url)

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Workspace(sources=[JsonStore(tmpdir)])
            briefing = BriefingService(ws, web_lookup=WebLookup(fetcher=_headlines_down)).build_briefing(NOW)
            self.assertIsNotNone(briefing.weather)
            self.assertIsNone(briefing.headlines)
            self.assertIn("RSS down", briefing.headlines_error)
            self.assertIn("28.0°C", briefing.to_text())
            self.assertIn("### Top 5 Headlines (Philippines)\nUnavailable (RSS down)", briefing.to_text())

            ok_briefing = BriefingService(ws, web_lookup=WebLookup(fetcher=_fake_fetcher)).build_briefing(NOW)
            copy = ok_briefing.headlines
            copy[0]["title"] = "Mutated"
            self.assertNotEqual(ok_briefing.headlines[0]["title"], "Mutated")


class TestOddWebReplies(unittest.TestCase):
    """Checks that cut-off or oddly shaped replies become DataSourceError, never a crash."""

    def test_a_reply_cut_off_halfway_becomes_data_source_error(self):
        with mock.patch(
            "urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"")
        ):
            with self.assertRaises(DataSourceError):
                WebLookup()._fetch_text("https://example.invalid/")

    def test_a_null_geocoding_reply_becomes_data_source_error(self):
        lookup = WebLookup(fetcher=lambda url: "null")
        with self.assertRaises(DataSourceError):
            lookup.get_weather("Manila")

    def test_a_place_without_a_latitude_becomes_data_source_error(self):
        lookup = WebLookup(fetcher=lambda url: '{"results": [{"name": "Manila"}]}')
        with self.assertRaises(DataSourceError):
            lookup.get_weather("Manila")

    def test_a_forecast_that_is_a_list_becomes_data_source_error(self):
        def _list_forecast(url):
            return _SAMPLE_GEO if "geocoding" in url else "[]"

        with self.assertRaises(DataSourceError):
            WebLookup(fetcher=_list_forecast).get_weather("Manila")

    def test_a_wikipedia_reply_that_is_a_list_becomes_data_source_error(self):
        lookup = WebLookup(fetcher=lambda url: "[]")
        with self.assertRaises(DataSourceError):
            lookup._search_wikipedia("Manila", 2)


class _BrokenWeb:
    """Stand-in web lookup whose weather and headlines fail with non-BuddyAI errors."""

    def get_weather(self, location, at_time=None):
        raise RuntimeError("unexpected weather failure")

    def get_headlines(self, limit=5, country="PH"):
        raise KeyError("headlines")


class TestBriefingNeverRaises(unittest.TestCase):
    """Checks that /brief still shows the local schedule whatever the web parts do."""

    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(sources=[JsonStore(self._tmp.name)])
        self.ws.tasks.add_task(
            Task("Submit report", NOW, due_date=NOW.replace(hour=23)), NOW
        )

    def tearDown(self):
        self._tmp.cleanup()
        logging.disable(logging.NOTSET)

    def test_an_unexpected_weather_error_shows_weather_as_unavailable(self):
        briefing = BriefingService(self.ws, web_lookup=_BrokenWeb()).build_briefing(NOW)
        self.assertIn(
            "### Weather\nUnavailable (the weather service sent an unexpected reply)",
            briefing.to_text(),
        )

    def test_an_unexpected_headlines_error_keeps_the_local_schedule(self):
        briefing = BriefingService(self.ws, web_lookup=_BrokenWeb()).build_briefing(NOW)
        text = briefing.to_text()
        self.assertIn("Submit report", text)
        self.assertIn("Unavailable (the news feed sent an unexpected reply)", text)


if __name__ == "__main__":
    unittest.main()
