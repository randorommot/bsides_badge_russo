# lib/screensaver_matrix_nb.py
# Non-blocking Matrix "rain" for SSD1306 128x64 (1 frame per call)
import time

def _rng32(x):
    x &= 0xFFFFFFFF
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= (x >> 17) & 0xFFFFFFFF
    x ^= (x << 5) & 0xFFFFFFFF
    return x & 0xFFFFFFFF

def init_state(width=128, height=64, seed=None):
    """Return state tuple used by draw_step()."""
    if seed is None:
        try:
            seed = time.ticks_ms()
        except:
            seed = 0xC0FFEE
    COL_W = 4
    COLS = width // COL_W
    cols = []
    s = (seed ^ 0x5EED) & 0xFFFFFFFF
    for _ in range(COLS):
        s = _rng32(s); length = 6 + (s % 18)   # 6..23
        s = _rng32(s); speed  = 1 + (s % 3)    # 1..3 px/frame
        s = _rng32(s); gap    = 6 + (s % 18)   # 6..23
        s = _rng32(s); start  = - (s % height) # start above
        cols.append([start, length, speed, gap])
    return (cols, s)

def draw_step(oled, state, bottom_guard=8):
    """Render one frame and update state. Returns new state."""
    width, height = oled.width, oled.height
    cols, s = state
    COL_W = 4
    bottom_y = height - bottom_guard

    oled.fill(0)

    for i in range(len(cols)):
        head_y, length, speed, gap = cols[i]
        x = i * COL_W

        # head (3px)
        hy0 = head_y
        hy1 = head_y + 2
        if hy1 >= 0 and hy0 < bottom_y - 1:
            y0 = 0 if hy0 < 0 else hy0
            y1 = (bottom_y - 2) if hy1 >= (bottom_y - 1) else hy1
            oled.line(x+1, y0, x+1, y1, 1)
            oled.pixel(x+2, y1, 1)

        # trail
        max_trail_end = bottom_y - 2 if (head_y + length) >= (bottom_y - 1) else (head_y + length)
        y = head_y + 3
        while y <= max_trail_end:
            s = _rng32(s)
            if (s & 0x3) != 0:
                oled.pixel(x+1, y, 1)
            if (s & 0x8) != 0:
                oled.pixel(x+2, y, 1)
            if (s & 0x40) != 0 and y+1 <= max_trail_end:
                oled.pixel(x+1 + ((s>>7)&1), y+1, 1)
            y += 1

        # advance
        head_y += speed
        if head_y - length > bottom_y - 2 + gap:
            s = _rng32(s)
            head_y = - (s % (height // 2)) - 8
            s = _rng32(s); length = 6 + (s % 18)
            s = _rng32(s); speed  = 1 + (s % 3)
            s = _rng32(s); gap    = 6 + (s % 18)

        cols[i][0] = head_y
        cols[i][1] = length
        cols[i][2] = speed
        cols[i][3] = gap

    oled.show()
    return (cols, s)
