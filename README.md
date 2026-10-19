# tak-feeder-gdacs

> [!WARNING]
> **Work in progress. Not recommended for use.** This fork is being improved
> and has not been tested against a live TAK server yet. Things may change or
> break without notice.

Sends the current alerts of GDACS (Global Disaster Alert and Coordination
System) to a TAK server as CoT: earthquakes, tropical cyclones, floods,
volcanoes, wildfires and droughts.

Fork of [sgofferj/tak-feeder-gdacs](https://github.com/sgofferj/tak-feeder-gdacs)
by Stefan Gofferje. The Node.js feeder is rewritten in Python on the logic of
his [trakbridge-plugin-gdacs](https://github.com/sgofferj/trakbridge-plugin-gdacs).

## What it sends

| Field | Value |
|---|---|
| UID | `gdacs-<alert level>-<guid>` (unchanged from upstream) |
| Callsign | `GDACS <type> <level> <country>`, e.g. `GDACS EQ Orange Panama` |
| Type | `a-o-G` with an icon per event type, coloured green / orange / red by alert level |
| Remarks | title, type, alert level, country, severity, affected population, description, link, published time, source, `#GDACS #disaster #<type>` |

Only current events are sent. Events with missing coordinates are skipped.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `COT_URL` | `udp://239.2.3.1:6969` | TAK server. Old name `REMOTE_SERVER_URL` works |
| `PYTAK_TLS_CLIENT_CERT` / `PYTAK_TLS_CLIENT_KEY` | | Client certificate and unencrypted key (PEM). Old names `REMOTE_SSL_USER_CERTIFICATE` / `REMOTE_SSL_USER_KEY` work |
| `PYTAK_TLS_DONT_VERIFY` | `0` | `1` = do not verify the server certificate |
| `SEND_STATIC_INTERVAL` | `60` | Seconds between send rounds, min 30 (old names `UPDATE_INTERVAL`, `GDACS_PULL_INTERVAL`); each round re-sends the current events |
| `FETCH_INTERVAL` | `600` | Seconds between feed reads, min 600. A failed read is retried the next round; the last good feed is sent for at most 3 fetch intervals |
| `STALE_SECONDS` | `180` | Marker lifetime; always at least 3 send intervals |
| `GDACS_ALERT_LEVELS` | (all) | e.g. `Orange,Red` |
| `TIMEZONE` | `Europe/Helsinki` | Time zone of the published time |
| `HEALTH_MAX_ERRORS` | `3` | Failed feed reads in a row before the container is unhealthy |
| `DEBUG` | `0` | Debug logging |

`UUID` and `LOGCOT` of the old feeder are no longer used.

## Running

Image for amd64 and arm64: `ghcr.io/street3r/tak-feeder-gdacs:latest`.

```yaml
services:
  feeder-gdacs:
    image: ghcr.io/street3r/tak-feeder-gdacs:latest
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./certs:/data:ro
```

The container runs as uid 10001; the key must be readable by it.

## Data

GDACS, a cooperation of the European Commission Joint Research Centre and UN
OCHA, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The source
line is in every marker's remarks.

## Credits and changes

Original work © Stefan Gofferje:
[tak-feeder-gdacs](https://github.com/sgofferj/tak-feeder-gdacs) and
[trakbridge-plugin-gdacs](https://github.com/sgofferj/trakbridge-plugin-gdacs),
used with his permission.

Changes in this fork (Street3r):

- 2026-10-13
  - Rewritten in Python (pytak) on the logic of the TrakBridge plugin.
  - **Fixed:** the heartbeat marker at 0,0 is gone.
  - **Fixed:** the uncertainty radius was computed from the severity value
    even when it is a magnitude or wind speed; now only from areas (km²).
  - **Fixed:** a connection error no longer exits the feeder; pytak
    reconnects to TAK and feed errors are retried.
  - Items with missing data are skipped instead of breaking the feed.
  - Callsign `GDACS <type> <level> <country>` instead of the UID; richer
    remarks; optional alert level filter.
  - Standard variable names with the old ones as aliases; health check;
    unprivileged container; tests and CI.
- 2026-10-15
  - Every event of a send round reaches TAK. pytak's send queue holds 100
    events and dropped the oldest when full, so rounds of more than 100
    lost the rest.
  - Reading and sending are separate: the feed is read every
    `FETCH_INTERVAL` (600 s) and the current events are re-sent every
    `UPDATE_INTERVAL` (60 s), so the feed is read less often while a client
    that connects still sees the events within a minute.
- 2026-10-19
  - Send intervals shared by all feeders: `SEND_STATIC_INTERVAL` (60 s, min 30,
    old name `UPDATE_INTERVAL`) and `STALE_SECONDS` (default 180 s, always
    at least 3 send intervals).
  - `FETCH_INTERVAL` minimum raised from 60 s to 600 s.

## License

GNU General Public License v3.0 or later, see [LICENSE](LICENSE).
