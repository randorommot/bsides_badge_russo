# BSides 25 badge

## Snake Game Fork

This fork adds a fully playable snake game to the BSides badge menu.

PREV - Turn left

NEXT - Turn right

SELECT - Pause/New Game

BACK - Back to the menu

### Installation Guide

```
git clone https://github.com/randorommot/bsides_badge_russo.git

cd /bsides_badge_russo

# Create venv and switch to it
python3 -m venv .venv
source .venv/bin/activate

pip install --user esptool mpremote

```

List the ports with mpremote, while your badge is connected to your computer:
```
mpremote connect list
/dev/cu.Bluetooth-Incoming-Port None 0000:0000 None None
/dev/cu.RandosBeatsStudioBuds None 0000:0000 None None
/dev/cu.debug-console None 0000:0000 None None
/dev/cu.usbmodem1101 ********* Espressif USB JTAG/serial debug unit
/dev/cu.wlan-debug None 0000:0000 None None
```

The Espressif one is correct - add it as shell variable:
```
PORT=/dev/cu.usbmodem1101
```

Copy the files to the badge:
```
mpremote connect $PORT fs cp -r software/* :/
```

Press RESET on your badge and you're done.

## Hardware

ESP32-C3FH4 (4MB flash) with WiFi and Bluetooth

128x64 px OLED display (SSD1306)

16 WS2812B (Neopixel compatible) LEDs

USB-C for flashing/charging

[Schematics](./hardware/BSides_2025_badge_v1.1_schematics.pdf)

## Software

The code in `software` is written in MicroPython and loaded onto the badge via USB-C connector.

Update the code by uploading via `mpremote` or directly via some IDE like [Thonny](https://thonny.org/).

## Device preparation

Install `esptool` and `mpremote`
```
pip install --user esptool mpremote
```

Install [MicroPython](https://micropython.org/download/ESP32_GENERIC_C3).

For BSides 2025: v1.26.1 (2025-09-11)
```
wget https://micropython.org/resources/firmware/ESP32_GENERIC_C3-20250911-v1.26.1.bin
esptool --port <port> erase_flash
esptool --port <port> --baud 921600 write_flash 0 ESP32_GENERIC_C3-20250911-v1.26.1.bin
```

## Copy files to the badge

```
mpremote <port> fs cp -r software/* :/
```

If the code is already running on the badge and `mpremote` does not connect, hold `SELECT` button down while resetting your badge (pressing `RESET` button or toggling ON/OFF switch).
