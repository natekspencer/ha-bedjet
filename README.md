<!-- BEGIN AUTO-GENERATED HEADER -->

[![Release](https://img.shields.io/github/v/release/natekspencer/ha-bedjet?style=for-the-badge)](https://github.com/natekspencer/ha-bedjet/releases)
[![Buy Me A Coffee/Beer](https://img.shields.io/badge/Buy_Me_A_☕/🍺-F16061?style=for-the-badge&logo=ko-fi&logoColor=white&labelColor=grey)](https://ko-fi.com/natekspencer)
[![HACS Badge](https://img.shields.io/badge/HACS-default-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

![Downloads](https://img.shields.io/github/downloads/natekspencer/ha-bedjet/total?style=flat-square)
![Latest Downloads](https://img.shields.io/github/downloads/natekspencer/ha-bedjet/latest/total?style=flat-square)

<!-- END AUTO-GENERATED HEADER -->

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://brands.home-assistant.io/bedjet/dark_logo.png">
  <img alt="bedjet logo" src="https://brands.home-assistant.io/bedjet/logo.png">
</picture>

# BedJet for Home Assistant

This project provides various entities to allow control of a [BedJet 3](https://bedjet.com) device.

> ⚠️ **Important**
>
> BedJet devices only allow **one active Bluetooth connection at a time**. If the BedJet mobile app is open (or running in the background) and connected to the device, Home Assistant will not be able to connect to it. The BedJet remote is not affected by this limitation, as it uses RF rather than Bluetooth.
>
> Before proceeding, **make sure the BedJet app is fully closed**. If you need to use the app (for example, to adjust biorhythm programs), temporarily disable the Home Assistant integration.

## Installation (HACS) - Recommended

1. Ensure HACS is installed: https://hacs.xyz/docs/use/download/download/
2. In Home Assistant, go to: HACS → Integrations
3. Search for BedJet
4. Click Download
5. Restart Home Assistant

## Installation (Manual)

1. Download this repository as a ZIP (green button, top right) and unzip the archive
2. Copy `/custom_components/bedjet` to your `<config_dir>/custom_components/` directory
   - You will need to create the `custom_components` folder if it does not exist
   - On Hassio the final location will be `/config/custom_components/bedjet`
   - On Hassbian the final location will be `/home/homeassistant/.homeassistant/custom_components/bedjet`

## Screenshot

![screenshot](images/BedJet3-HA.png)

<!-- BEGIN AUTO-GENERATED FOOTER -->

## ❤️ Support

If you like this integration or found it useful, consider supporting its development:

- 💜 [Sponsor me on GitHub](https://github.com/sponsors/natekspencer)
- ☕ [Buy me a coffee / beer](https://ko-fi.com/natekspencer)
- ⭐ [Star this project](https://github.com/natekspencer/ha-bedjet)

## 📈 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=natekspencer/ha-bedjet)](https://www.star-history.com/#natekspencer/ha-bedjet)

<!-- END AUTO-GENERATED FOOTER -->
