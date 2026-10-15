# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the GDACS feeder."""

import asyncio
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from tak_feeder_gdacs import feeder

ITEM = """<item>
 <title>Green earthquake (Magnitude 6.1M, Depth:10km) in Panama 12/10/2026 23:20 UTC</title>
 <description>On 10/12/2026, an earthquake of magnitude 6.1 occurred.</description>
 <link>https://www.gdacs.org/report.aspx?eventtype=EQ&amp;eventid=1571161</link>
 <pubDate>Mon, 12 Oct 2026 23:34:20 GMT</pubDate>
 <gdacs:iscurrent>{current}</gdacs:iscurrent>
 <guid isPermaLink="false">EQ1571161</guid>
 <geo:Point><geo:lat>{lat}</geo:lat><geo:long>-81.4989</geo:long></geo:Point>
 <gdacs:eventtype>{etype}</gdacs:eventtype>
 <gdacs:alertlevel>{level}</gdacs:alertlevel>
 <gdacs:eventid>1571161</gdacs:eventid>
 <gdacs:severity unit="{unit}" value="{value}">Magnitude 6.1M, Depth:10km</gdacs:severity>
 <gdacs:population unit="(in MMI&gt;=VII)" value="1130">1 thousand (in MMI&gt;=VII)</gdacs:population>
 <gdacs:country>Panama</gdacs:country>
</item>"""


def feed(*items):
    return ('<rss version="2.0" xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#" '
            'xmlns:gdacs="http://www.gdacs.org"><channel>' + "".join(items)
            + "</channel></rss>").encode()


def item(current="true", lat="7.7028", etype="EQ", level="Green", unit="M", value="6.1"):
    return ITEM.format(current=current, lat=lat, etype=etype, level=level, unit=unit, value=value)


class GdacsTest(unittest.TestCase):
    def test_event(self) -> None:
        src = feeder.GdacsSource(feeder.Settings())
        (ev,) = [ET.fromstring(e) for e in src.parse(feed(item()))]
        self.assertEqual(ev.get("uid"), "gdacs-green-eq1571161")
        self.assertEqual(ev.find("detail/contact").get("callsign"), "GDACS EQ Green Panama")
        self.assertEqual(ev.find("detail/color").get("argb"), "-16711936")
        self.assertTrue(ev.find("detail/usericon").get("iconsetpath").endswith("earthquake.png"))
        self.assertEqual(ev.find("point").get("ce"), "1000.0")  # magnitude is not an area
        text = ev.find("detail/remarks").text
        self.assertIn("Severity: Magnitude 6.1M, Depth:10km", text)
        self.assertIn("Population: 1 thousand", text)
        self.assertIn("Published: 2026-10-13 02:34", text)
        self.assertTrue(text.endswith("#GDACS #disaster #earthquake"))

    def test_area_severity_sets_ce(self) -> None:
        src = feeder.GdacsSource(feeder.Settings())
        (ev,) = [ET.fromstring(e) for e in src.parse(feed(item(etype="FL", unit="km2",
                                                                value="314.159")))]
        self.assertAlmostEqual(float(ev.find("point").get("ce")), 10000.0, places=0)

    def test_skips_old_broken_and_filtered(self) -> None:
        src = feeder.GdacsSource(feeder.Settings(alert_levels="Orange,Red"))
        xml = feed(item(current="false"), item(lat="x"), item(level="Green"), item(level="Red"))
        self.assertEqual(len(src.parse(xml)), 1)

    def test_feed_down(self) -> None:
        src = feeder.GdacsSource(feeder.Settings())
        with mock.patch.object(feeder, "fetch", mock.AsyncMock(side_effect=OSError("x"))):
            self.assertEqual(asyncio.run(src.events()), [])

    def test_fetches_every_fetch_interval_and_resends_between(self) -> None:
        src = feeder.GdacsSource(feeder.Settings(fetch_interval=600))
        clock = mock.Mock(return_value=1000.0)
        with mock.patch.object(feeder.time, "monotonic", clock):
            up = mock.AsyncMock(return_value=feed(item()))
            with mock.patch.object(feeder, "fetch", up):
                self.assertEqual(len(asyncio.run(src.events())), 1)
                clock.return_value = 1060.0
                self.assertEqual(len(asyncio.run(src.events())), 1)  # from the cache
                self.assertEqual(up.await_count, 1)
            down = mock.AsyncMock(side_effect=OSError("x"))
            with mock.patch.object(feeder, "fetch", down):
                clock.return_value = 1600.0
                self.assertEqual(len(asyncio.run(src.events())), 1)
                clock.return_value = 1660.0  # retried every round
                self.assertEqual(len(asyncio.run(src.events())), 1)
                self.assertEqual(down.await_count, 2)
                clock.return_value = 2801.0  # last good fetch 3 fetch intervals ago
                self.assertEqual(asyncio.run(src.events()), [])

    def test_legacy_interval(self) -> None:
        with mock.patch.dict("os.environ", {"GDACS_PULL_INTERVAL": "30"}, clear=True):
            self.assertEqual(feeder.Settings.from_env().update_interval, 60.0)  # min 60
        with mock.patch.dict("os.environ", {"GDACS_PULL_INTERVAL": "120"}, clear=True):
            self.assertEqual(feeder.Settings.from_env().update_interval, 120.0)


if __name__ == "__main__":
    unittest.main()
