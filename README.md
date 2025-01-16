[![Release](https://img.shields.io/github/v/release/natekspencer/ha-bedjet?style=for-the-badge)](https://github.com/natekspencer/ha-bedjet/releases)
[![Buy Me A Coffee/Beer](https://img.shields.io/badge/Buy_Me_A_☕/🍺-F16061?style=for-the-badge&logo=ko-fi&logoColor=white&labelColor=grey)](https://ko-fi.com/natekspencer)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

![Downloads](https://img.shields.io/github/downloads/natekspencer/ha-bedjet/total?style=flat-square)
![Latest Downloads](https://img.shields.io/github/downloads/natekspencer/ha-bedjet/latest/total?style=flat-square)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://brands.home-assistant.io/bedjet/dark_logo.png">
  <img alt="bedjet logo" src="https://brands.home-assistant.io/bedjet/logo.png">
</picture>

# BedJet for Home Assistant

This project provides various entities to allow control of a [BedJet](https://bedjet.com) device.

## Installation (HACS) - Recommended

0. Have [HACS](https://custom-components.github.io/hacs/installation/manual/) installed, this will allow you to easily update
1. Add `https://github.com/natekspencer/ha-bedjet` as a [custom repository](https://custom-components.github.io/hacs/usage/settings/#add-custom-repositories) as Type: Integration
2. Click install under "HA-BedJet", restart your instance.

## Installation (Manual)

1. Download this repository as a ZIP (green button, top right) and unzip the archive
2. Copy `/custom_components/bedjet` to your `<config_dir>/custom_components/` directory
   - You will need to create the `custom_components` folder if it does not exist
   - On Hassio the final location will be `/config/custom_components/bedjet`
   - On Hassbian the final location will be `/home/homeassistant/.homeassistant/custom_components/bedjet`

## Screenshot

![screenshot](https://i.imgur.com/Y836CWU.png)
