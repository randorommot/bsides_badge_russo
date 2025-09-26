# lib/screensaver_matrix.py
# Matrix rain screensaver for 128x64 SSD1306 (MONO) on MicroPython.
# API: run_screensaver(display, username="PLAYER", exit_pins=[...], fps=30)
import time, framebuf

# Tiny PRNG (no imports, fast, deterministic enough)
class _RNG:
    def __init__(self, s=0xC0FFEE):
        if s == 0:
            s = 1
        self.s = s & 0xFFFFFFFF
    def rand(self):
        # xorshift32
        x = self.s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17) & 0xFFFFFFFF
        x ^= (x << 5) & 0xFFFFFFFF
        self.s = x & 0xFFFFFFFF
        return self.s
    def rint(self, n):
        return self.rand() % n

def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)

def run_screensaver(disp, username="PLAYER", exit_pins=None, fps=30):
    """
    disp: SSD1306-like object with fill, text, pixel, line, show
    username: optional string at bottom row
    exit_pins: list/iterable of machine.Pin; any edge exits
    fps: 10..60 recommended
    """
    W, H = 128, 64
    rng = _RNG(time.ticks_ms() ^ 0x5EED)

    # Layout: use columns every 4 px for legibility
    COL_W = 4
    COLS = W // COL_W

    # Each column has: head_y, length, speed, gap
    # y is in pixels. We render "bits" with 1px spacing.
    heads = []
    for c in range(COLS):
        length = 6 + rng.rint(18)         # 6..23 pixels long
        speed  = 1 + (rng.rint(3))        # 1..3 px per frame
        gap    = 6 + rng.rint(18)         # vertical spacing before next head
        start  = -rng.rint(H)             # stagger starts above screen
        heads.append([start, length, speed, gap])

    # Username
    uname = (username or "").strip()
    tw = len(uname) * 8
    tx = max(0, (W - tw) // 2)
    bottom_y = H - 8

    last = time.ticks_ms()
    frametime = 1000 // _clamp(fps, 10, 60)

    # A little blink timer for the username “cursor” feel
    blink_ms = 700
    blink_t0 = last

    while True:
        # Exit on any pin change (simple debounce)
        if exit_pins:
            for p in exit_pins:
                try:
                    v1 = p.value()
                    time.sleep_ms(3)
                    if v1 != p.value():
                        return
                except:
                    pass

        now = time.ticks_ms()
        if time.ticks_diff(now, last) < frametime:
            time.sleep_ms(1)
            continue
        last = now

        # Draw frame
        disp.fill(0)

        # Draw matrix columns
        for i in range(COLS):
            head_y, length, speed, gap = heads[i]
            x = i * COL_W

            # Draw the trail: brighter head + trailing bits (mono fake brightness)
            # Head (solid line segment for a few pixels)
            hy0 = head_y
            hy1 = head_y + 2  # 3px head
            # Clip and draw head
            if hy1 >= 0 and hy0 < bottom_y - 1:  # keep above username row
                y0 = max(0, hy0)
                y1 = min(bottom_y - 2, hy1)
                disp.line(x+1, y0, x+1, y1, 1)
                disp.pixel(x+2, y1, 1)

            # Trail of random bits beneath head
            # We fill downwards for 'length' pixels with sparse random pixels
            max_trail_end = min(bottom_y - 2, head_y + length)
            y = head_y + 3
            while y <= max_trail_end:
                # Random 2px-wide “glyph” bits
                r = rng.rand()
                if (r & 0x3) != 0:  # ~75% density
                    disp.pixel(x+1, y, 1)
                if (r & 0x8) != 0:
                    disp.pixel(x+2, y, 1)
                # occasional vertical link to mimic katakana streaks
                if (r & 0x40) != 0 and y+1 <= max_trail_end:
                    disp.pixel(x+1 + ((r>>7)&1), y+1, 1)
                y += 1

            # Move the head downward
            head_y += speed

            # When head passes screen+gap, reset with new stats to keep variety
            if head_y - length > bottom_y - 2 + gap:
                head_y = -rng.rint(H // 2) - 8
                length = 6 + rng.rint(18)
                speed  = 1 + (rng.rint(3))
                gap    = 6 + rng.rint(18)
            heads[i][0] = head_y
            heads[i][1] = length
            heads[i][2] = speed
            heads[i][3] = gap

        # Username at bottom with subtle blink cursor
        if uname:
            disp.text(uname, tx, bottom_y, 1)
            if time.ticks_diff(now, blink_t0) // blink_ms % 2 == 0:
                # Draw a 3px cursor after the name
                cx = tx + tw + 1
                if cx < W - 1:
                    disp.line(cx, bottom_y, cx, bottom_y+6, 1)

        disp.show()
