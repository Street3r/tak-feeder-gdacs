# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright Stefan Gofferje (tak-feeder-gdacs, trakbridge-plugin-gdacs)
# Copyright (C) 2026 Street3r (Python port and changes, see README)
"""GDACS disaster alerts (RSS) -> CoT."""

from __future__ import annotations

import logging
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from zoneinfo import ZoneInfo

from . import __version__
from .common import Health, cot_event, env, env_float, fetch, remarks_text

LOG = logging.getLogger("tak_feeder_gdacs")

RSS_URL = "https://www.gdacs.org/xml/rss.xml"
NS = {"gdacs": "http://www.gdacs.org", "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#"}
SHAPES = "ad78aafb-83a6-4c07-b2b9-a897a8b6a38f/Shapes/"
EVENTS = {  # type -> (name, icon), as in upstream
    "WF": ("Wildfire", "firedept.png"),
    "DR": ("Drought", "sunny.png"),
    "EQ": ("Earthquake", "earthquake.png"),
    "TC": ("Tropical cyclone", "thunderstorm.png"),
    "FL": ("Flood", "water.png"),
    "VO": ("Volcano", "volcano.png"),
}
COLORS = {"Green": "-16711936", "Orange": "-35072", "Red": "-65535"}


@dataclass
class Settings:
    """Feeder settings from the environment (see .env.example)."""

    update_interval: float = 60.0
    fetch_interval: float = 600.0
    url: str = RSS_URL
    alert_levels: str = ""
    timezone: str = "Europe/Helsinki"
    source_line: str = "Source: GDACS (European Commission JRC, UN OCHA), CC BY 4.0"

    @classmethod
    def from_env(cls) -> "Settings":
        """Read settings (old name GDACS_PULL_INTERVAL still accepted)."""
        d = cls()
        return cls(
            update_interval=max(60.0, env_float("UPDATE_INTERVAL", d.update_interval,
                                                "GDACS_PULL_INTERVAL")),
            fetch_interval=max(60.0, env_float("FETCH_INTERVAL", d.fetch_interval)),
            url=env("GDACS_URL", d.url),
            alert_levels=env("GDACS_ALERT_LEVELS", ""),
            timezone=env("TIMEZONE", d.timezone),
            source_line=env("SOURCE_LINE", d.source_line),
        )


def _text(item: ET.Element, path: str) -> str:
    el = item.find(path, NS)
    return (el.text or "").strip() if el is not None else ""


def _date(value: str) -> Optional[datetime]:
    try:
        return parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError):
        return None


class GdacsSource:
    """Fetches the GDACS RSS feed every FETCH_INTERVAL and sends the current
    events every round with a fresh time, so a client that connects sees them
    within one round. A failed fetch is retried the next round; the last good
    feed is sent for at most CACHE_ROUNDS fetch intervals."""

    CACHE_ROUNDS = 3

    def __init__(self, settings: Settings, health: Optional[Health] = None) -> None:
        self.s = settings
        self.health = health
        self.tz = ZoneInfo(settings.timezone)
        self.levels = {lvl.strip().lower() for lvl in settings.alert_levels.split(",")
                       if lvl.strip()}
        self.headers = {"User-Agent": f"tak-feeder-gdacs/{__version__}"}
        self.feed = b""
        self.feed_at: Optional[float] = None  # monotonic time of the last good fetch

    def item_event(self, item: ET.Element) -> Optional[bytes]:
        """CoT for one current event, or None if it is skipped or broken."""
        if _text(item, "gdacs:iscurrent").lower() != "true":
            return None
        try:
            lat = float(_text(item, "geo:Point/geo:lat"))
            lon = float(_text(item, "geo:Point/geo:long"))
        except ValueError:
            return None
        level = _text(item, "gdacs:alertlevel")
        if self.levels and level.lower() not in self.levels:
            return None
        etype = _text(item, "gdacs:eventtype")
        name, icon = EVENTS.get(etype, (etype or "Event", "caution.png"))
        guid = _text(item, "guid") or f"{etype}{_text(item, 'gdacs:eventid')}"
        country = _text(item, "gdacs:country")

        # Severity is km² only for some events (magnitude for earthquakes etc.),
        # so it is used as the uncertainty radius only when it is an area.
        ce = 1000.0
        sev = item.find("gdacs:severity", NS)
        if sev is not None and sev.get("unit", "").lower() in ("km2", "km²", "sqkm"):
            try:
                ce = max(1000.0, math.sqrt(float(sev.get("value", "0")) / math.pi) * 1000)
            except ValueError:
                pass
        population = item.find("gdacs:population", NS)
        published = _date(_text(item, "pubDate"))
        lines = [
            _text(item, "title"),
            f"Type: {name} ({etype})",
            f"Alert level: {level}" if level else None,
            f"Country: {country}" if country else None,
            f"Severity: {sev.text.strip()}" if sev is not None and sev.text else None,
            (f"Population: {population.text.strip()}"
             if population is not None and population.text else None),
            _text(item, "description"),
            _text(item, "link"),
            (f"Published: {published.astimezone(self.tz).strftime('%Y-%m-%d %H:%M')}"
             if published else None),
        ]
        callsign = " ".join(p for p in ("GDACS", etype, level, country) if p)
        return cot_event(
            uid=f"gdacs-{level}-{guid}".lower(),  # as in upstream
            cot_type="a-o-G",
            lat=lat, lon=lon,
            callsign=callsign,
            remarks=remarks_text(lines, self.s.source_line,
                                 ("GDACS", "disaster", name.lower().replace(" ", ""))),
            stale=self.s.update_interval * 3,
            how="m-r",
            ce=ce,
            icon=SHAPES + icon,
            color=COLORS.get(level, "-1"),
        )

    def parse(self, xml: bytes) -> list[bytes]:
        """Events of the current alerts in the feed."""
        channel = ET.fromstring(xml).find("channel")
        events = []
        for item in channel.findall("item") if channel is not None else []:
            try:
                event = self.item_event(item)
            except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
                LOG.debug("GDACS: skipped item: %s", exc)
                continue
            if event:
                events.append(event)
        return events

    async def _fetch(self, mono: float) -> None:
        try:
            body = await fetch(self.s.url, self.headers, timeout=60)
            ET.fromstring(body)
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-exception-caught
            LOG.warning("GDACS feed failed: %s", exc)
            if self.health is not None:
                self.health.error()
            return
        self.feed, self.feed_at = body, mono
        if self.health is not None:
            self.health.ok()

    async def events(self) -> list[bytes]:
        """Source protocol: fetch when due, then convert the latest feed."""
        mono = time.monotonic()
        fetched = self.feed_at is None or mono - self.feed_at >= self.s.fetch_interval
        if fetched:
            await self._fetch(mono)
        if self.feed_at is None or mono - self.feed_at > self.CACHE_ROUNDS * self.s.fetch_interval:
            return []
        events = self.parse(self.feed)
        if fetched:
            LOG.info("GDACS: %d current events", len(events))
        return events

    async def start(self) -> None:
        """Nothing runs in the background."""
