# APRS-IS Integration for Home Assistant

Connect Home Assistant to the [APRS-IS](http://www.aprs-is.net/) network (Automatic Packet Reporting System — Internet Service). Monitor positions, weather stations, and messages for your callsigns and any other amateur radio stations you want to track. Optionally connect a local KISS TNC (e.g. [Direwolf](https://github.com/wb2osz/direwolf)) to receive simultaneously from RF and transmit over the air.

## Requirements

- Home Assistant 2026.1 or later
- A valid amateur radio callsign and APRS-IS passcode
- Use passcode `-1` for receive-only mode on APRS-IS (outbound still works via KISS TNC if configured)
- Optional: a local KISS TNC accessible via TCP (e.g. Direwolf with `KISSPORT 8001`)

## Installation

### HACS (Custom Repository)

1. In HACS, go to **Integrations → Custom repositories**
2. Add this repository URL with category **Integration**
3. Search for **APRS-IS** and install
4. Restart Home Assistant

### Manual

Copy the `custom_components/aprs_is` folder into your HA config's `custom_components/` directory and restart.

## Initial Setup

Go to **Settings → Devices & Services → Add Integration** and search for **APRS-IS**.

| Field | Description |
|---|---|
| Callsign | Your login callsign, optionally with SSID (e.g. `KE5YIM` or `KE5YIM-1`) |
| Passcode | Your APRS-IS passcode. Use `-1` for receive-only |

The login callsign is used only to authenticate the connection and receive inbound messages. All stations are configured separately in Options. To change callsign or passcode later, use **Reconfigure** from the integration's `⋮` menu.

## Options

Open the integration and click **Configure** to access the multi-step options menu.

### APRS-IS

| Option | Description |
|---|---|
| Server | APRS-IS server hostname (default: `rotate.aprs.net`). Leave empty to disable APRS-IS and use KISS TNC only |
| Port | TCP port (default: `14580`) |
| Event rate limit | Max HA events fired per second per station. `0` = unlimited (default) |

### KISS TNC

Connect a local KISS TNC over TCP (e.g. Direwolf) to receive APRS packets from RF simultaneously with APRS-IS and to transmit over the air.

| Option | Description |
|---|---|
| Host | Hostname or IP of the KISS TNC (e.g. `localhost`). Leave empty to disable |
| Port | TCP port (Direwolf default: `8001`) |
| RF digipeater path | AX.25 path for outbound RF packets (default: `WIDE1-1,WIDE2-1`) |
| Primary transmit transport | Which transport to use first for outbound packets. The other is used as automatic fallback if the primary is unavailable |

**Transmit routing:** Both APRS-IS and KISS TNC are equals — either can be set as primary with the other as fallback. The integration checks live connection state on every outbound packet, so failover and recovery are seamless and automatic. Message retry loops continue across transport changes without resetting the retry count.

**Receive:** Both connections run concurrently. Packets from RF are filtered locally to your configured stations (mirrors the APRS-IS server-side filter). Duplicate packets arriving on both transports are harmless — entity state updates are idempotent and the message dedup window handles messages.

**ACKs:** Outbound ACKs and incoming ACK receipt use the same transport-agnostic routing. An ACK arriving via either transport cancels the retry loop regardless of which transport sent the original message.

### Station Beacon

Periodically transmit a position report for the login callsign using the Home Assistant home location.

| Option | Description |
|---|---|
| Beacon interval | Transmit every N minutes. `0` = disabled |
| Comment | Free-text comment appended to the position packet. Defaults to "Home Assistant" |
| APRS symbol | Two-character symbol (table + code). Examples: `/-` = house (default), `/>` = car, `/k` = truck |
| Transport | Which transport to use: `auto` (default), `both`, `aprs_is`, or `kiss_tnc` |

### Stations

Add any APRS callsign to track. For each station, choose a position tracking mode:

| Mode | Description |
|---|---|
| None | Packet count and last-seen only |
| Device Tracker | Integrates with HA zones and presence detection |
| Map Pin (Geo Location) | Shows a position pin on the HA map |

Stations whose base callsign matches the login callsign are considered **my stations**. Each station gets:
- Packets Received sensor
- Last Heard timestamp sensor
- Symbol sensor (human-readable APRS symbol name, e.g. "Car", "House", "Digipeater")
- Device tracker or map pin (if enabled)

### Weather Stations

Add any APRS weather station callsign. Each gets a full set of weather sensors (temperature, humidity, pressure, wind, rain, luminosity), a Symbol sensor, and a HA Weather entity.

### Weather Beacon

Automatically transmit an APRS weather report on a schedule using your Home Assistant sensor entities.

| Option | Description |
|---|---|
| Beacon interval | Transmit every N minutes. `0` = disabled |
| From callsign | Callsign to send the beacon as (e.g. `KE5YIM-13`). Leave blank to use the login callsign |
| Comment | Free-text comment appended to the packet. Defaults to "Home Assistant" |
| Latitude / Longitude override | Override the WX station coordinates. Defaults to the HA home location |
| Temperature sensor | Any °C / °F / K sensor — converted automatically |
| Humidity sensor | Relative humidity sensor (%) |
| Pressure sensor | Any hPa / mb / inHg / PSI / kPa sensor — converted automatically |
| Wind direction sensor | Degrees |
| Wind speed / gust sensors | Any mph / km/h / m/s / kn sensor — converted automatically |
| Rain last 1h / 24h / since midnight | mm or inch precipitation sensors |
| Luminosity sensor | Solar irradiance (W/m²) |
| Staleness sentinel entity | Optional. If set, this entity must have updated within the max data age or the beacon is suppressed — useful for an uptime sensor or similar always-updating entity. If not set, the beacon is suppressed if none of the configured sensor entities have updated within the beacon interval (or max data age, whichever is longer) |
| Max data age | How stale the sentinel entity (or any configured sensor entity) can be before the beacon is skipped |
| Transport | Which transport to use: `auto` (default), `both`, `aprs_is`, or `kiss_tnc` |

All sensor fields are optional. Unavailable or non-numeric entities are silently omitted from the packet.

## Actions (Services)

All actions are available under the `aprs_is` domain. The optional `from_call` field overrides which callsign transmits the packet; if omitted, the login callsign is used.

When sending as the login callsign, messages include a message number and are automatically retried (up to 6 times) until an ACK is received. When using a custom `from_call`, no message number is added and no retry occurs since ACKs would be addressed to a callsign we don't receive messages for.

### Transport and NOGATE fields

Every action accepts two optional routing fields:

| Field | Default | Description |
|---|---|---|
| `transport` | `auto` | Which transport to use for this packet |
| `nogate` | `false` | Append `NOGATE` to the AX.25 digipeater path — instructs IGates not to forward the RF packet to the internet. Only applies when transmitting via KISS TNC. |

**Transport values:**

| Value | Available on | Description |
|---|---|---|
| `auto` | All actions | Use the configured primary transport; fall back to the other if unavailable |
| `both` | All except `send_message` | Send simultaneously on APRS-IS and KISS TNC. NOGATE is forced on the RF copy when APRS-IS is connected, preventing IGates from re-injecting the packet back onto the internet feed. If APRS-IS is disconnected, NOGATE is not forced so IGates can pick up the RF copy |
| `aprs_is` | All actions | Always use APRS-IS; raise an error if unavailable or passcode is `-1` |
| `kiss_tnc` | All actions | Always use KISS TNC; raise an error if not configured or not connected |

`both` is intentionally excluded from `send_message` — APRS radios vary in how reliably they deduplicate messages with the same message ID arriving from two paths, and a duplicate delivery cannot be retracted once sent.

### `aprs_is.send_message`

Send a direct APRS message.

```yaml
action: aprs_is.send_message
data:
  to: "W1ABC-9"
  message: "Hello from HA!"
  from_call: "KE5YIM-1"   # optional
  transport: auto          # optional: auto, aprs_is, kiss_tnc
  nogate: false            # optional
```

### `aprs_is.send_bulletin`

Send a numbered or named APRS bulletin.

```yaml
action: aprs_is.send_bulletin
data:
  bulletin_id: "0"          # BLN0–BLN9, or a name up to 5 chars
  message: "Net tonight 7pm on 146.520"
  from_call: "KE5YIM-1"    # optional
  transport: both           # optional: auto, both, aprs_is, kiss_tnc
```

### `aprs_is.send_announcement`

Send an APRS announcement (BLN_A–BLN_Z).

```yaml
action: aprs_is.send_announcement
data:
  announcement_id: "A"
  message: "ARES activation"
  transport: both           # optional
```

### `aprs_is.send_wx_report`

Send an APRS weather report using raw values. All values must be in the specific units listed. Useful when calling from a template automation where you need to compute or transform values first.

```yaml
action: aprs_is.send_wx_report
data:
  temperature_f: "{{ states('sensor.outdoor_temp') | float }}"
  humidity: "{{ states('sensor.outdoor_humidity') | float }}"
  pressure_mb: "{{ states('sensor.pressure') | float }}"
  wind_speed_mph: 12.5
  wind_dir: 270
  wind_gust_mph: 18.0
  latitude: 32.345    # optional; defaults to HA home location
  longitude: -97.456  # optional; defaults to HA home location
  from_call: "KE5YIM-13"
  transport: both     # optional
```

### `aprs_is.send_wx_report_from_entities`

Send an APRS weather report by pointing directly at your Home Assistant sensor entities. Units are read from each sensor's `unit_of_measurement` attribute and converted automatically — use any °C/°F/K temperature sensor, any hPa/mb/inHg/PSI pressure sensor, any mph/km/h/m/s wind sensor, and mm or inch rain sensors.

```yaml
action: aprs_is.send_wx_report_from_entities
data:
  temperature_entity: sensor.outdoor_temperature
  humidity_entity: sensor.outdoor_humidity
  pressure_entity: sensor.outdoor_pressure
  wind_speed_entity: sensor.wind_speed
  wind_dir_entity: sensor.wind_direction
  wind_gust_entity: sensor.wind_gust
  rain_1h_entity: sensor.rain_last_hour
  rain_24h_entity: sensor.rain_last_24h
  rain_midnight_entity: sensor.rain_since_midnight
  luminosity_entity: sensor.solar_radiation
  latitude: 32.345    # optional; defaults to HA home location
  longitude: -97.456  # optional; defaults to HA home location
  from_call: "KE5YIM-13"   # optional
  transport: both           # optional
```

All fields are optional. Any entity that is unavailable or has an unknown state is silently omitted from the packet.

### `aprs_is.send_position`

Send an APRS position report. Useful for publishing your HA location or any fixed/mobile station position to APRS-IS (and from there to RF via an IGate).

```yaml
action: aprs_is.send_position
data:
  latitude: 33.123
  longitude: -97.456
  symbol_table: "/"
  symbol_code: ">"          # > = car
  comment: "Home Assistant"
  speed_mph: 35.0           # optional
  course: 270               # optional, degrees
  altitude_ft: 650          # optional
  from_call: "KE5YIM-9"    # optional
  transport: both           # optional
```

Speed and course populate the APRS course/speed data extension. Speed is encoded as knots in the packet. If only one of speed/course is provided, the other defaults to 0.

### `aprs_is.send_object`

Create or update an APRS object on the map.

```yaml
action: aprs_is.send_object
data:
  object_name: "SHELTER1"
  latitude: 33.123
  longitude: -97.456
  symbol_table: "/"
  symbol_code: "h"
  comment: "Emergency shelter open"
  transport: both   # optional
```

### `aprs_is.delete_object`

Kill an APRS object (sends a killed-object packet).

```yaml
action: aprs_is.delete_object
data:
  object_name: "SHELTER1"
  transport: both   # optional
```

## HA Events

Every received packet fires a Home Assistant event you can use in automations:

| Event | Fired for |
|---|---|
| `aprs_is_packet_received` | Every packet |
| `aprs_is_position_received` | Position packets |
| `aprs_is_weather_received` | Weather packets |
| `aprs_is_message_received` | Direct messages |
| `aprs_is_bulletin_received` | Bulletins and announcements |
| `aprs_is_packet_sent` | Outbound packets |

Event data includes the full parsed packet from aprslib.

## APRS-IS Filter

The integration automatically builds a server-side filter to minimize incoming packet volume:

- `b/` — packets FROM your configured stations and weather stations
- `g/` — messages addressed TO your login callsign
- `r/` — range filter centred on your HA location (if radius > 0)

Extra terms from **Global Settings → Extra filter terms** are appended verbatim.

The KISS TNC has no server-side filter. The integration applies the same logic locally: only packets FROM configured stations or messages addressed TO the login callsign are processed; all others are silently dropped.
