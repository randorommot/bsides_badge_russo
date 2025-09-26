# lib/screensaver_bounce.py
# Simple animated screensaver for 128x64 SSD1306 (MONO) displays on MicroPython.
import framebuf, time

# 24x24 snake icon (1-bit). You can redraw later; keep size small for speed.
# Each byte is MONO_HLSB-packed. This is a simple stylized snake head.
_SNAKE_24x24 = bytearray([
    0b00000000,0b00000000,0b00000000,
    0b00011111,0b11110000,0b00000000,
    0b00111111,0b11111000,0b00000000,
    0b01111100,0b00111100,0b00000000,
    0b01111000,0b00011100,0b00000000,
    0b11110011,0b11001110,0b00000000,
    0b11100111,0b11100110,0b00000000,
    0b11100110,0b00100110,0b00000000,
    0b11100110,0b00100110,0b00000000,
    0b11100111,0b11100110,0b00000000,
    0b11110011,0b11001110,0b00000000,
    0b01111000,0b00011100,0b00000000,
    0b01111100,0b00111100,0b00000000,
    0b00111111,0b11111000,0b00000000,
    0b00011111,0b11110000,0b00000000,
    0b00000110,0b00100000,0b00000000,
    0b00000110,0b00100000,0b00000000,
    0b00000111,0b11100000,0b00000000,
    0b00000110,0b00100000,0b00000000,
    0b00000110,0b00100000,0b00000000,
    0b00000111,0b11100000,0b00000000,
    0b00000000,0b00000000,0b00000000,
    0b00000000,0b00000000,0b00000000,
    0b00000000,0b00000000,0b00000000,
])

class _Sprite24:
    def __init__(self, data):
        # Create a 24x24 framebuffer for the sprite using MONO_HLSB
        self.fb = framebuf.FrameBuffer(bytearray(data), 24, 24, framebuf.MONO_HLSB)
        self.w = 24
        self.h = 24

def _twinkle_points(seed=0xACE1, count=18, w=128, h=56):
    # Deterministic pseudo-random star positions (avoid last 8 px where text sits)
    pts = []
    x = seed
    for _ in range(count):
        # simple LFSR-ish
        x ^= (x << 7) & 0xFFFF
        x ^= (x >> 9)
        x ^= (x << 8) & 0xFFFF
        px = (x & 0x7F) % w
        py = ((x >> 7) & 0x3F) % h
        pts.append((px, py))
    return pts

def _draw_twinkles(disp, pts, t):
    # Alternate stars on/off with a slow wave
    phase = (t // 250) & 1  # toggle every ~250ms
    for i, (x, y) in enumerate(pts):
        on = ((i + phase) & 1) == 0
        if on:
            disp.pixel(x, y, 1)

def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)

def run_screensaver(disp, username="PLAYER", exit_pins=None, fps=30):
    """
    disp: SSD1306-like object with fill, text, blit, pixel, rect, show
    username: string to render at the bottom
    exit_pins: iterable of machine.Pin configured as inputs; any press exits
    fps: target frames per second
    """
    sprite = _Sprite24(_SNAKE_24x24)
    stars = _twinkle_points()

    # Starting position and velocity for bounce
    x, y = 8, 8
    vx, vy = 1, 1  # pixels per frame (keep small for crisp mono motion)
    W, H = 128, 64
    bottom_text_y = H - 8  # last text row
    last = time.ticks_ms()
    frametime = 1000 // _clamp(fps, 8, 60)

    # Precompute text width (6 px per char in framebuf.font)
    uname = (username or "").strip()
    tw = len(uname) * 8  # use 8 for a bit of spacing/center bias
    tx = max(0, (W - tw) // 2)

    while True:
        # Exit condition on any pin press (active low or high: we detect any state change)
        if exit_pins:
            for p in exit_pins:
                try:
                    if p.value() == 0 or p.value() == 1:  # read once; if wired active-low, a press reads 0
                        # simple debounce: check twice 5ms apart
                        v1 = p.value()
                        time.sleep_ms(5)
                        v2 = p.value()
                        if v1 != v2:  # edge
                            return
                except:
                    pass

        now = time.ticks_ms()
        if time.ticks_diff(now, last) < frametime:
            # small sleep to stabilize FPS and save power
            time.sleep_ms(1)
            continue
        last = now

        # Update physics
        x += vx
        y += vy
        if x <= 0 or x + sprite.w >= W:
            vx = -vx
            x += vx
        # Keep the sprite above username text area
        max_y = bottom_text_y - sprite.h - 2
        if y <= 0 or y >= max_y:
            vy = -vy
            y += vy

        # Draw frame
        disp.fill(0)
        _draw_twinkles(disp, stars, now)
        # Draw sprite
        disp.blit(sprite.fb, x, y)
        # Draw simple "shadow" username for pop (mono fake outline)
        if uname:
            disp.text(uname, tx+1, bottom_text_y+1, 0)  # shadow (erase)
            disp.text(uname, tx,   bottom_text_y,   1)  # text
        disp.show()
