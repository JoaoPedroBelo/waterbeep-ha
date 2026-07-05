# Waterbeep (EPAL) Home Assistant Integration

[![Tests](https://img.shields.io/github/actions/workflow/status/JoaoPedroBelo/waterbeep-ha/tests.yml?style=for-the-badge&label=Tests)](https://github.com/JoaoPedroBelo/waterbeep-ha/actions/workflows/tests.yml)
[![HACS Validation](https://img.shields.io/github/actions/workflow/status/JoaoPedroBelo/waterbeep-ha/validate.yml?style=for-the-badge&label=HACS)](https://github.com/JoaoPedroBelo/waterbeep-ha/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/JoaoPedroBelo/waterbeep-ha?style=for-the-badge)](https://github.com/JoaoPedroBelo/waterbeep-ha/releases)
[![License](https://img.shields.io/github/license/JoaoPedroBelo/waterbeep-ha?style=for-the-badge)](LICENSE)
[![Maintainer](https://img.shields.io/badge/Maintainer-%40JoaoPedroBelo-blue?style=for-the-badge)](https://github.com/JoaoPedroBelo)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JoaoPedroBelo&repository=waterbeep-ha&category=integration)

---

A Home Assistant custom integration for the **Aquamatrix Waterbeep** water-telemetry service, which exposes household water consumption from **EPAL** meters. Since Waterbeep has no public API, this integration signs into your Waterbeep account and reads the same dashboard endpoints the web app uses.

## ✨ Features

- **💧 Consumption Monitoring**: Daily, 7-day, 30-day and monthly water consumption (m³) + per-capita average
- **📊 Water Dashboard Ready**: A `total_increasing` cumulative sensor built for the Home Assistant Water dashboard
- **🕐 Low-Profile Polling**: Queries the service only twice a day (01:00 & 13:00) — no tight loops
- **☁️ Cloud Polling**: Authenticates and pulls dashboard data automatically
- **🇬🇧🇵🇹 Localised**: English and Portuguese translations included

## 🚀 Quick Start

### Installation via HACS

1. Open HACS in your Home Assistant instance
2. Click on "Integrations"
3. Click the three dots in the top right corner and select "Custom repositories"
4. Add this repository URL: `https://github.com/JoaoPedroBelo/waterbeep-ha`
5. Select category "Integration"
6. Click "Add"
7. Find "Waterbeep (EPAL)" in HACS and click "Install"
8. Restart Home Assistant

### Configuration

> ⚠️ **Note:** This integration is in **early alpha**. Login and the last-7-days chart are wired up; more sensors (meter index in m³, 30-day totals, per-person average, billing history, leak alerts) will be added as their dashboard endpoints are captured. See **[docs/API.md](custom_components/waterbeep/docs/API.md)**.

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Waterbeep"
4. Enter your configuration:
   - **NIF**: Your NIF (this is your Waterbeep account User Code)
   - **Password**: Your Waterbeep account password

The integration validates your credentials with a live login before creating the entry, then refreshes automatically **twice a day (01:00 and 13:00 local time)**.

## 📖 Documentation

Comprehensive documentation is available in the [`docs`](custom_components/waterbeep/docs/) folder:

- **[Architecture](custom_components/waterbeep/docs/ARCHITECTURE.md)**: Technical architecture and data flow
- **[API](custom_components/waterbeep/docs/API.md)**: The reverse-engineered Waterbeep requests and outstanding TODOs

## 🎯 Entities

### Sensors (6)
- **Total Consumption** (m³, `total_increasing`) — cumulative accumulator, the entity to add to the **Water dashboard**
- **Daily Consumption** (m³) — most recent complete day (daily series in attributes)
- **7-Day Consumption** (m³) — total over the last 7 days
- **30-Day Consumption** (m³) — total over the last 30 days
- **Last Month Consumption** (m³) — latest billed month (month label in attributes)
- **Average Per-Capita Consumption** (L/person/day)

### Binary Sensors (1)
- Service Available (ON when the last poll succeeded — disabled by default)

> Waterbeep exposes only per-period consumption (no lifetime meter index), so the
> **Total Consumption** sensor synthesises a monotonic cumulative value by adding
> each completed day exactly once, persisted across restarts. This is what makes it
> valid for the Home Assistant Water dashboard.

## 🏗️ Example Automations

### High Daily Consumption Alert
```yaml
automation:
  - alias: "Notify on high water consumption"
    trigger:
      - platform: numeric_state
        entity_id: sensor.waterbeep_daily_consumption
        above: 500
    action:
      - service: notify.mobile_app
        data:
          title: "High water usage 💧"
          message: >
            Yesterday's consumption was
            {{ states('sensor.waterbeep_daily_consumption') }} L.
```

### Daily Water Report
```yaml
automation:
  - alias: "Daily water report"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: notify.mobile_app
        data:
          title: "Water report"
          message: >
            Yesterday: {{ states('sensor.waterbeep_daily_consumption') }} L ·
            Last 7 days: {{ states('sensor.waterbeep_7_day_consumption') }} L
```

## 🛠️ Technical Details

- **Service**: Aquamatrix Waterbeep (`aquamatrix.pt/waterbeep`), EPAL meters
- **Auth**: ASP.NET Core session cookie + antiforgery token (`__RequestVerificationToken`)
- **Architecture**: `DataUpdateCoordinator`; all network logic isolated in `api.py`
- **Integration Type**: Service (Cloud Polling)
- **Update Schedule**: Twice daily (01:00 / 13:00) plus once on startup
- **Home Assistant**: Compatible with 2024.1.0+

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. If you can capture additional Waterbeep dashboard endpoints (see [docs/API.md](custom_components/waterbeep/docs/API.md)), that directly unlocks more sensors.

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👤 Author

**João Belo** ([@JoaoPedroBelo](https://github.com/JoaoPedroBelo))

## ⚠️ Disclaimer

This is an independent, open-source integration for the Aquamatrix Waterbeep service. This project is not affiliated with, endorsed by, or sponsored by Aquamatrix, EPAL, or any related companies. Use it in accordance with the Waterbeep service's terms.

## 🔒 Privacy

Your Waterbeep **User Code** and **Password** are stored only in your local Home Assistant config entry and are sent solely to `aquamatrix.pt`. Never commit real credentials or account codes to this repository.

## 🐛 Issues & Support

For issues or questions:
- [GitHub Issues](https://github.com/JoaoPedroBelo/waterbeep-ha/issues)
- Review Home Assistant logs for error messages

## ⭐ Show Your Support

If you find this integration useful, please consider giving it a star on GitHub!
