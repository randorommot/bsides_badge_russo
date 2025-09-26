# lib/screensaver_bounce_nb.py
# One-frame-per-call "bouncing sprite" for SSD1306 128x64 (MONO)
# API:
#   state = init_state(width, height, seed=None)
#   state = draw_step(oled, state, bottom_guard=8)

import time
import framebuf

def _rng32(x):
    x &= 0xFFFFFFFF
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= (x >> 17) & 0xFFFFFFFF
    x ^= (x << 5) & 0xFFFFFFFF
    return x & 0xFFFFFFFF

# 16x16 simple snake-ish glyph (MONO_HLSB)
_SPRITE_16 = bytearray([
    0b00000000,0b00000000,
    0b00011111,0b11100000,
    0b00111111,0b11110000,
    0b01111000,0b00111000,
    0b01110011,0b11011000,
    0b11100111,0b11101100,
    0b11100110,0b00101100,
    0b11100110,0b00101100,
    0b11100111,0b11101100,
    0b01110011,0b11011000,
    0b01111000,0b00111000,
    0b00111111,0b11110000,
    0b00011111,0b11100000,
    0b00000110,0b00100000,
    0b00000111,0b11100000,
    0b00000000,0b00000000,
])

def init_state(width=128, height=64, seed=None, stars_count=18):
    if seed is None:
        try:
            seed = time.ticks_ms()
        except:
            seed = 0xACE1
    s = seed & 0xFFFFFFFF

    # sprite framebuffer
    fb = framebuf.FrameBuffer(bytearray(_SPRITE_16), 16, 16, framebuf.MONO_HLSB)

    # initial pos/vel
    x, y = 8, 8
    vx, vy = 1, 1

    # star field (avoid bottom 8px by default)
    stars = []
    for _ in range(stars_count):
        s = _rng32(s)
        sx = s % width
        s = _rng32(s)
        sy = (s % (height - 8))
        stars.append((sx, sy))

    return (x, y, vx, vy, stars, s, fb)

def draw_step(oled, state, bottom_guard=8):
    width, height = oled.width, oled.height
    x, y, vx, vy, stars, s, fb = state
    max_y = height - bottom_guard - fb.height

    # update physics
    x += vx
    y += vy
    if x <= 0 or x + fb.width >= width:
        vx = -vx
        x += vx
    if y <= 0 or y >= max_y:
        vy = -vy
        y += vy

    # draw
    oled.fill(0)

    # twinkle
    # toggle half of stars each call
    s = _rng32(s)
    phase = (s >> 3) & 1
    for i, (sx, sy) in enumerate(stars):
        if ((i ^ phase) & 1) == 0:
            oled.pixel(sx, sy, 1)

    # sprite
    oled.blit(fb, x, y)

    oled.show()
    return (x, y, vx, vy, stars, s, fb)
