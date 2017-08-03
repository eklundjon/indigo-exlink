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

### Monitored States

The plugin is able to query several settings from a supported TV

* Power (boolean)
* Active Input (TV / HDMI1 / SmartHub / etc)
* Current Volume (integer)
* Current Channel (integer)
* Current Mute State (boolean)
* Picture Mode (Dynamic / Standard / etc)
* Sound Mode (Music / Movie / etc)
* Picture Size (Zoom / Wide Fit / etc)

### Actions Supported

Not all TVs support all actions -- for example, if your TV does not support 3D, don't expect the 3D commands to work.
The sound commands only work when audio is routed to the TV's internal speakers.  Some settings might have a different name
on your TV (for example, the Surround and Dialog settings may or may not be SRS co-branded), and different models have
different names for the various sound and picture modes, or different numbers of supported modes.  If you select a mode
that's not supported by your TV, expect to see the "Not Available" error briefly appear on the display.

* Set Input
* Set Volume
* Set Channel
* Set Picture Mode
* Set Picture Size
* Set Sound Mode
* Send Picture Command
  * Set Black Tone
  * Set Dynamic Contrast
  * Set RGB-Only Mode
  * Set Color Space
  * Set Edge Enhancement
  * Set xvYCC
  * Set Motion Lighting
  * Set LED Motion Plus
  * Set Color Tone
  * Set Digital Noise Filter
  * Set MPEG Noise Filter
  * Set HDMI Black Level
  * Set Film Mode
  * Set Auto-Motion Plus
  * Set Backlight Level
  * Set Contrast Level
  * Set Brightness
  * Set Sharpness
  * Set Color
  * Set Tint
  * Set Shadow Detail
  * Set Gamma
  * Set White Balance (RGB offsets and gains)
  * Reset Picture
  * Reset White Balance
* Send Sound Command
  * Set SRS Surround
  * Set SRS Dialog
  * Set MTS
  * Set Auto-Volume
  * Select Speakers
  * Set Balance
  * Set Graphic EQ 100Hz/300Hz/1Khz/3Khz/10Khz
  * Reset Sound
  * Reset Graphic EQ
* Send 3D command
  * Set 3D Mode
  * Set 3D->2D
  * Set Auto-View
  * Set Viewpoint
  * Set Depth
  * 3D Picture Correction
* Set TV Mode Antenna/Cable
* Set Language
* Send button press
  * Menu
  * Up
  * Down
  * Left
  * Right
  * Enter
  * Exit
  * Mute
  * Vol+
  * Vol-
  * Ch+
  * Ch-
  * PrevCh
  * FavCh
  * ChAdd
  * Caption
  * Sleep
  * Guide
  * Info
  * Return
  * Tools
  * Red
  * Green
  * Yellow
  * Blue
  * Play
  * Pause
  * Stop
  * Rewind
  * FFwd
  * Skip Fwd
  * Skip Back
  * Source
  * Picture Mode
  * Sound Mode
  * Channel List
  * Digits 0 - 9
  
### License

[![License: MPL 2.0](https://img.shields.io/badge/License-MPL%202.0-brightgreen.svg)](https://opensource.org/licenses/MPL-2.0)

### Troubleshooting

If your TV does not support a command, you should see the error "Not Available" displayed briefly.
