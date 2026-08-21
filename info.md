# Waterbeep (EPAL) Integration

Monitor your household water consumption from the Aquamatrix **Waterbeep**
telemetry service (EPAL meters) in Home Assistant.

## Features

- **Consumption sensors** — daily, 7-day, 30-day and monthly water use (m³), plus a per-capita average
- **Energy/Water dashboard ready** — each completed day is imported as the `waterbeep:consumption` external statistic
- **Cloud polling** — signs into your Waterbeep account and reads the dashboard twice a day (01:00 & 13:00)
- **Unattended 2FA** *(optional)* — reads the one-time code from a Resend inbound mailbox
- English 🇬🇧 and Portuguese 🇵🇹 translations

## Quick Start

1. Install via HACS
2. Add the integration via **Settings → Devices & Services → Add Integration**
3. Enter your Waterbeep **User Code** and **Password**

## Status

Beta. Additional data (billing, leak alerts) will be added as the corresponding
dashboard endpoints are mapped.

## Author

**João Belo** — independent, open-source project. Not affiliated with
Aquamatrix or EPAL.
