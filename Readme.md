indigo-exlink
=============

This is a plugin for the [Indigo](http://www.indigodomo.com/) smart home server that integrates the Samsung Ex-Link
serial control protocol for televisions.

### Requirements

1. [Indigo 7](http://www.indigodomo.com/) or later
2. Samsung TV with Ex-Link port
3. Suitable RS232 connection to Indigo server

### Installation Instructions

1. Download latest release [here](https://github.com/eklundjon/indigo-exlink/releases).
2. Follow [standard plugin installation process](http://wiki.indigodomo.com/doku.php?id=indigo_7_documentation:getting_started#installing_plugins_configuring_plugin_settings_permanently_removing_plugins)

### Compatible Hardware

This plugin supports any Samsung TV with an Ex-Link port.  Some TVs have obfuscated or disabled ports that can be made to work,
but enabling Ex-Link on your TV is beyond the scope of this README.  Not all plugin functions are supported on all TVs, and
not all TV functions are necessarily available in the plugin.

### Usage

Select the appropriate local or remote serial port for your TV when creating the Indigo device.  Use Indigo's
"Send Status Request" option to query the TV and populate the device's state variables.

[![License: MPL 2.0](https://img.shields.io/badge/License-MPL%202.0-brightgreen.svg)](https://opensource.org/licenses/MPL-2.0)
