# lib/screensaver_marquee_nb.py
# One-frame-per-call marquee with subtle wave.
# API:
#   state = init_state(width, height, message="HELLO", speed_px=1)
#   state = draw_step(oled, state)
import time

# tiny integer sine LUT (0..63 -> -3..+3)
_SIN = [0,0,1,1,1,2,2,2,3,3,3,3,3,3,3,3,
        3,3,3,3,3,3,3,3,2,2,2,1,1,1,0,0,
        0,0,-1,-1,-1,-2,-2,-2,-3,-3,-3,-3,-3,-3,-3,-3,
        -3,-3,-3,-3,-3,-3,-3,-3,-2,-2,-2,-1,-1,-1,0,0]

def init_state(width=128, height=64, message="HELLO", speed_px=1, gap_chars=4):
    msg = (message or "HELLO").strip()
    gap = " " * gap_chars
    scroll_text = msg + gap
    char_w = 8  # framebuf's default font width assumption
    text_px = len(scroll_text) * char_w

    # start off-screen to the right
    x = width
    baseline = (height // 2) - 4  # center-ish
    phase = 0
    draw_bars = True
    bar_margin = 10

    return (scroll_text, char_w, text_px, x, baseline, phase, speed_px, draw_bars, bar_margin, width, height)

def draw_step(oled, state):
    (scroll_text, char_w, text_px, x, baseline, phase,
     speed_px, draw_bars, bar_margin, W, H) = state

    # draw
    oled.fill(0)

    if draw_bars:
        oled.line(0, bar_margin, W-1, bar_margin, 1)
        oled.line(0, H - bar_margin - 1, W-1, H - bar_margin - 1, 1)

    # render twice for wrap-around
    for k in (0, 1):
        tx = x + k * text_px
        if tx < W and tx + text_px > 0:
            for i, ch in enumerate(scroll_text):
                cx = tx + i * char_w
                if -char_w <= cx < W:
                    wy = _SIN[(i + phase) & 63]
                    # fake outline: draw 0 around then 1 in center
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            if dx or dy:
                                oled.text(ch, cx + dx, baseline + wy + dy, 0)
                    oled.text(ch, cx, baseline + wy, 1)

    # advance
    x -= speed_px
    if x <= -text_px:
        x += text_px
    phase = (phase + 1) & 63

    oled.show()
    return (scroll_text, char_w, text_px, x, baseline, phase, speed_px, draw_bars, bar_margin, W, H)
