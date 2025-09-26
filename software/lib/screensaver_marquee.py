# lib/screensaver_marquee.py
# Marquee screensaver for 128x64 SSD1306 (MONO) on MicroPython.
# API: run_screensaver(display, username="PLAYER", exit_pins=[...], fps=30)
import time

def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)

# Tiny integer sine LUT (0..63 -> -5..+5) to add a subtle wave without math.sin
_SIN = [
     0,  1,  1,  2,  2,  3,  3,  4,
     4,  4,  5,  5,  5,  5,  5,  5,
     5,  5,  5,  5,  5,  4,  4,  4,
     3,  3,  2,  2,  1,  1,  0, -1,
    -1, -2, -2, -3, -3, -4, -4, -4,
    -5, -5, -5, -5, -5, -5, -5, -5,
    -5, -5, -5, -4, -4, -4, -3, -3,
    -2, -2, -1, -1,  0,  1,  1,  2
]

def _wave(i, phase=0):
    return _SIN[(i + phase) & 63]

def _draw_outlined_text(disp, text, x, y):
    """Fake outline: draw shadow (0) around then foreground (1).
       For SSD1306's built-in 8x8 font, this gives a crisp look."""
    # Erase halo to boost contrast
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                disp.text(text, x + dx, y + dy, 0)
    # Foreground
    disp.text(text, x, y, 1)

def run_screensaver(disp, username="PLAYER", exit_pins=None, fps=30,
                    message=None, loop=True):
    """
    disp: SSD1306-like object with fill, text, line, show
    username: used if message is None
    exit_pins: iterable of machine.Pin; any edge exits
    fps: target 10..60
    message: optional text to scroll; defaults to username
    loop: if False, one pass then exit
    """
    W, H = 128, 64
    fps = _clamp(fps, 10, 60)
    frametime = 1000 // fps

    msg = (message if (message is not None and len(message)) else username or "HELLO").strip()
    # Add spacing so the gap between repeats looks nice
    gap = "    "
    scroll_text = msg + gap

    # Compute pixel width (8 px per char for framebuf font). Slightly looser spacing feels better.
    char_w = 8
    text_px = len(scroll_text) * char_w

    # Start off-screen to the right
    x = W
    # Vertical placement & wave
    baseline = (H // 2) - 4  # center-ish (font is 8px tall)
    phase = 0

    last = time.ticks_ms()
    speed_px = 1  # pixels per frame
    wave_stride = 2  # every N pixels, advance the wave phase for motion

    # Optional top/bottom dividers for style
    draw_bars = True
    bar_margin = 10

    while True:
        # Exit on any debounced pin change
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

        disp.fill(0)

        # Decorative bars
        if draw_bars:
            disp.line(0, bar_margin, W-1, bar_margin, 1)
            disp.line(0, H - bar_margin - 1, W-1, H - bar_margin - 1, 1)

        # We render the text twice to cover wrap-around
        for k in (0, 1):
            tx = x + k * text_px
            # Only draw if at least partially visible
            if tx < W and tx + text_px > 0:
                # Wave: split text into chunks to vary Y slightly across width
                # Draw every 8px (per-char) with slight vertical offset
                for i, ch in enumerate(scroll_text):
                    cx = tx + i * char_w
                    if cx <= -char_w or cx >= W:
                        continue
                    wy = _wave(i, phase)
                    _draw_outlined_text(disp, ch, cx, baseline + wy)

        # Update scroll
        x -= speed_px
        if x <= -text_px:
            if not loop:
                disp.show()
                return
            x += text_px

        # Nudge wave forward
        if (x & (wave_stride - 1)) == 0:
            phase = (phase + 1) & 63

        disp.show()
