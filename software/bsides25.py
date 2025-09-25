import sys
import os
import ubinascii
import urandom
import network
import socket
import ssl
import json
import uasyncio as asyncio
import time, micropython
from machine import Pin, I2C
import ssd1306, neopixel
import bsides_logo

# Writer
from writer.writer import Writer
import writer.freesans20 as freesans20
import writer.font10 as font10
import writer.font6 as font6

# -----------------------
# Settings
# -----------------------
I2C_SCL = 1
I2C_SDA = 0
OLED_WIDTH = 128
OLED_HEIGHT = 64

NEOPIXEL_PIN = 3
NEOPIXEL_COUNT = 16
NEOPIXEL_FPS = 50

# Buttons
BTN_NEXT_PIN = 5      # Next / Increase
BTN_PREV_PIN = 8      # Previous / Decrease
BTN_SELECT_PIN = 4    # Enter
BTN_BACK_PIN = 9      # Back
DEBOUNCE_MS = 50

# Auto-repeat
REPEAT_DELAY = 500     # ms before auto-repeat starts
REPEAT_INTERVAL = 10  # ms between repeats

INACTIVITY_TIMEOUT = 5000  # ms
LOGO_PERIOD = 3000  # ms

SSID = "bsides-badge"
PASSWORD = "bsidestallinn"
URL = "https://badge.bsides.ee"
URL_QR = "badge.bsides.ee"

# -----------------------
# Globals
# -----------------------
button_event = None
last_button = None
last_activity = 0

BTN_NEXT = 1
BTN_PREV = 2
BTN_SELECT = 3
BTN_BACK = 4

btn_state = {}       # {btn_id: pressed or not}
repeat_tasks = {}    # {btn_id: task}
_last_event_ms = {}  # debounce tracking

i2c_oled = I2C(0, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA))
oled = ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c_oled)
wri6  = Writer(oled, font6, verbose=False)
wri10 = Writer(oled, font10, verbose=False)
wri20 = Writer(oled, freesans20, verbose=False)

username_wri = wri20
username_lines = None

# -----------------------
# Parameters
# -----------------------

class Parameter:
    def __init__(self, name, value, maxval):
        self.name = name
        self.value = value
        self.maxval = maxval

# -----------------------
# LED effects
# -----------------------

led_startup    = True
led_effects    = []
led_effect     = Parameter("Light_effect", 0, 3)
led_brightness = Parameter("Brightness", 10, 100)
led_hue        = Parameter("Hue", 180, 360)
led_sat        = Parameter("Saturation", 100, 100)
led_speed      = Parameter("Speed", 30, 100)

# -----------------------
# JSON parameter storage
# -----------------------

params = {
    "Brightness": led_brightness,
    "Hue": led_hue,
    "Saturation": led_sat,
    "Speed": led_speed,
    "Light_effect" : led_effect
}

# --- Snake high score param (persistent in params.json) ---
snake_high_score = Parameter("SnakeHighScore", 0, 9999)
params["SnakeHighScore"] = snake_high_score

FILENAME = "params.json"

def save_params():
    data = {name: param.value for name, param in params.items()}
    with open(FILENAME, "w") as f:
        json.dump(data, f)

def load_params():
    try:
        with open(FILENAME, "r") as f:
            data = json.load(f)
            for name, val in data.items():
                if name in params:
                    params[name].value = val
    except OSError:
        # file not found, keep defaults
        pass

# -----------------------
# Username and ID
# -----------------------
def load_username():
    try:
        with open("yourname.txt") as f:
            return f.read().strip() or None
    except OSError:
        return None

USERNAME = load_username()

ID_FILENAME = "id.txt"

def is_valid_hex_id(s):
    """Check if s is a 12-character hex string (6 bytes)."""
    if len(s) != 12:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False

def load_or_create_device_id():
    device_id = None
    need_create = True

    # try to read existing ID
    try:
        with open(ID_FILENAME, "r") as f:
            hex_str = f.read().strip().upper()
            if is_valid_hex_id(hex_str):
                device_id = hex_str
                need_create = False
    except OSError:
        pass  # file does not exist

    if need_create:
        # generate new 6-byte ID
        random_bytes = bytes([urandom.getrandbits(8) for _ in range(6)])
        hex_str = ubinascii.hexlify(random_bytes).decode().upper()
        device_id = hex_str

        # store to file
        try:
            with open(ID_FILENAME, "w") as f:
                f.write(device_id)
        except OSError:
            pass  # handle write error

    return device_id

device_id = load_or_create_device_id()
print("Device ID: {}".format(device_id))
# -----------------------
# Hardware init
# -----------------------

def init_neopixels():
    np = neopixel.NeoPixel(Pin(NEOPIXEL_PIN, Pin.OUT), NEOPIXEL_COUNT)
    np.fill((0,0,0))
    np.write()
    return np

# -----------------------
# Button IRQ handling
# -----------------------
def _push_button(btn_id):
    global last_button, last_activity
    last_button = btn_id
    last_activity = time.ticks_ms()
    if button_event:
        button_event.set()

def _schedule_push(btn):
    btn_id, pin_state = btn
    now = time.ticks_ms()
    if time.ticks_diff(now, _last_event_ms.get(btn_id, 0)) < DEBOUNCE_MS:
        return
    _last_event_ms[btn_id] = now

    if pin_state == 0:  # pressed
        btn_state[btn_id] = 1
        _push_button(btn_id)
        # start repeat task for Next/Prev
        if btn_id in (BTN_NEXT, BTN_PREV):
            repeat_tasks[btn_id] = asyncio.create_task(_repeat_task(btn_id))
    else:  # released
        btn_state[btn_id] = 0
        t = repeat_tasks.pop(btn_id, None)
        if t:
            t.cancel()

def make_irq(btn_id):
    def handler(pin):
        micropython.schedule(_schedule_push, (btn_id, pin.value()))
    return handler

def setup_buttons():
    cfg = [(BTN_NEXT_PIN, BTN_NEXT),
           (BTN_PREV_PIN, BTN_PREV),
           (BTN_SELECT_PIN, BTN_SELECT),
           (BTN_BACK_PIN, BTN_BACK)]
    for pin_num, btn_id in cfg:
        p = Pin(pin_num, Pin.IN)  # external pull-ups
        p.irq(trigger=Pin.IRQ_FALLING|Pin.IRQ_RISING, handler=make_irq(btn_id))

async def _repeat_task(btn_id):
    try:
        await asyncio.sleep_ms(REPEAT_DELAY)
        while btn_state[btn_id]:
            _push_button(btn_id)
            await asyncio.sleep_ms(REPEAT_INTERVAL)
    except asyncio.CancelledError:
        return

# -----------------------
# Screen base class
# -----------------------
class Screen:
    def __init__(self, oled):
        self.oled = oled

    def render(self):
        pass

    async def handle_button(self, btn):
        pass

# -----------------------
# Lights screens
# -----------------------
class ParamScreen(Screen):
    def __init__(self, oled, writer, param, returnscreen, barfill=False, wraparound=False):
        super().__init__(oled)
        self.writer = writer
        self.param = param
        self.returnscreen = returnscreen
        self.barfill = barfill
        self.wraparound = wraparound

    def render(self):
        self.oled.fill(0)

        val = self.param.value
        bar_x = 0
        bar_y = 30
        bar_w = self.oled.width
        bar_h = 10
        self.oled.rect(bar_x, bar_y, bar_w, bar_h, 1)

        # Knob/fill position
        pos = bar_x + (val * (bar_w - 1)) // self.param.maxval
        if not self.barfill:
            self.oled.vline(pos, bar_y, bar_h, 1)
        else:
            self.oled.fill_rect(bar_x, bar_y, pos, bar_h, 1)

        # Numeric display
        self.writer.set_textpos(self.oled, 50, 0)
        self.writer.printstring("{}: {:3d}".format(self.param.name, val))
        self.oled.show()

    async def handle_button(self, btn):
        if btn == BTN_NEXT and (self.wraparound or self.param.value < self.param.maxval):
            self.param.value = (self.param.value + 1) % (self.param.maxval + 1)
        elif btn == BTN_PREV and (self.wraparound or self.param.value > 0):
            self.param.value = (self.param.value - 1) % (self.param.maxval + 1)
        elif btn in (BTN_SELECT, BTN_BACK):
            return self.returnscreen(self.oled)
        return self

class BrightnessScreen(ParamScreen):
    def __init__(self, oled):
        super().__init__(oled, wri10, led_brightness, LightsScreen, barfill=True, wraparound=False)

class SpeedScreen(ParamScreen):
    def __init__(self, oled):
        super().__init__(oled, wri10, led_speed, LightsScreen, barfill=True, wraparound=False)

class SaturationScreen(ParamScreen):
    def __init__(self, oled):
        super().__init__(oled, wri10, led_sat, LightsScreen, barfill=False, wraparound=False)

class HueScreen(ParamScreen):
    def __init__(self, oled):
        super().__init__(oled, wri10, led_hue, LightsScreen, barfill=False, wraparound=True)

class ListScreen(Screen):
    def __init__(self, oled, title, items):
        super().__init__(oled)
        self.title = title
        self.items = items  # list of strings or tuples
        self.headerwriter = wri10
        self.listwriter = wri6
        self.index = 0
        self.offset = 0  # first visible item

        # metrics
        self.line_height = self.listwriter.font.height()
        self.rows = (self.oled.height - 20) // self.line_height  # room below header

    async def handle_button(self, btn):
        if btn == BTN_NEXT:
            self.index = (self.index + 1) % len(self.items)
        elif btn == BTN_PREV:
            self.index = (self.index - 1) % len(self.items)
        elif btn == BTN_BACK:
            return self.on_back()
        elif btn == BTN_SELECT:
            return self.on_select(self.index)

        # adjust scroll offset
        if self.index < self.offset:
            self.offset = self.index
        elif self.index >= self.offset + self.rows:
            self.offset = self.index - self.rows + 1

        return self

    def render(self):
        self.oled.fill(0)
        self.headerwriter.set_textpos(self.oled, 0, 0)
        self.headerwriter.printstring(self.title)

        visible = range(self.offset, min(len(self.items), self.offset + self.rows))
        for row, i in enumerate(visible):
            y = 20 + row * self.line_height
            prefix = ">" if i == self.index else " "
            self.listwriter.set_textpos(self.oled, y, 0)
            self.listwriter.printstring("{}{}".format(prefix, self.items[i][0]))

        self.oled.show()

    # --- to be customized in child classes ---
    def on_select(self, index):
        pass

    def on_back(self):
        pass

class EffectScreen(ListScreen):
    def __init__(self, oled):
        super().__init__(oled, "LED effects", led_effects)

    def on_select(self, index):
        global led_effect
        led_effect.value = index
        return self

    def on_back(self):
        return LightsScreen(self.oled)

lights_screens = [("Effects", EffectScreen),
                  ("Brightness", BrightnessScreen),
                  ("Hue", HueScreen),
                  ("Saturation", SaturationScreen),
                  ("Speed", SpeedScreen)]

class LightsScreen(ListScreen):
    def __init__(self, oled):
        super().__init__(oled, "Lights", lights_screens)

    def on_select(self, index):
        cls = lights_screens[index][1]
        return cls(self.oled)

    def on_back(self):
        save_params()
        return MenuScreen(self.oled)

# -----------------------
# Badge screens
# -----------------------
class FetchNameScreen(Screen):
    def __init__(self, oled):
        super().__init__(oled)
        self.oled = oled
        self.index = 0  # only one item
        self.message = ""  # status message to display
        self.wlan = None

    async def handle_button(self, btn):
        global username_lines, USERNAME
        if btn == BTN_SELECT:
            self.message = "Connecting WiFi..."
            self.render()
            try:
                await self._connect_wifi()
            except Exception as e:
                self.message = f"WiFi error: {e}"
                self.render()
                return self

            self.message = "Fetching name..."
            self.render()
            try:
                name = await self._fetch_name()
                self.message = f"Name: {name}"
                self.render()
                # Reset name lines and store to yourname.txt
                USERNAME = name
                username_lines = None
                try:
                    with open("yourname.txt", "w") as f:
                        f.write(name)
                except OSError as e:
                    self.message += f" (save error: {e})"
                    self.render()
            except Exception as e:
                self.message = f"Fetch error: {e}"
                self.render()
        elif btn == BTN_BACK:
            await self._disconnect_wifi()
            return BadgeScreen(oled)

        return self

    async def _connect_wifi(self):
        if not self.wlan:
            self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        if not self.wlan.isconnected():
            self.wlan.connect(SSID, PASSWORD)
            for _ in range(20):  # wait up to ~10 seconds
                await asyncio.sleep(0.5)
                if self.wlan.isconnected():
                    return
            raise RuntimeError("Could not connect to WiFi")

    async def _disconnect_wifi(self):
        if not self.wlan:
            return
        try:
            self.wlan.disconnect()
        except OSError:
            pass
        for _ in range(20):  # up to ~10 seconds
            if not self.wlan.isconnected():
                break
            await asyncio.sleep(0.5)
        self.wlan.active(False)

    async def _fetch_name(self):
        # parse URL
        proto, rest = URL.split("://", 1)
        if "/" in rest:
            host, base_path = rest.split("/", 1)
            base_path = "/" + base_path
        else:
            host, base_path = rest, ""

        port = 443 if proto == "https" else 80

        # resolve host
        addr_info = socket.getaddrinfo(host, port)
        addr = addr_info[0][-1]
        s = socket.socket()
        s.connect(addr)

        if proto == "https":
            s = ssl.wrap_socket(s, server_hostname=host)

        path = base_path + "/getname/" + device_id
        req = "GET {} HTTP/1.0\r\nHost: {}\r\n\r\n".format(path, host)
        s.send(req.encode())

        # read response
        resp = b""
        while True:
            data = s.recv(512)
            if not data:
                break
            resp += data
        s.close()

        # extract body
        body = resp.split(b"\r\n\r\n", 1)[-1]
        try:
            data = json.loads(body)
        except ValueError:
            raise RuntimeError("Invalid JSON")

        # Check for error
        if "error" in data:
            raise RuntimeError("{}".format(data.get("error","")))

        # compare IDs case-insensitively
        if data.get("id", "").upper() != device_id.upper() or "name" not in data:
            raise RuntimeError("Unexpected response")

        return data["name"].strip()

    def render(self):
        self.oled.fill(0)

        # header = device_id
        wri6.set_textpos(self.oled, 0, 0)
        wri6.printstring("ID: {}".format(device_id))

        if self.message:
            y = wri6.font.height() + 2
            wri6.set_textpos(self.oled, y, 0)
            wri6.printstring(self.message)
        else:
            # menu item
            y = wri6.font.height() + 2
            wri6.set_textpos(self.oled, y, 0)
            wri6.printstring(URL_QR)

            # menu item
            y += wri6.font.height() + 2
            wri6.set_textpos(self.oled, y, 0)
            wri6.printstring(">Fetch name")

        self.oled.show()

class CodeRepoScreen(Screen):
    async def handle_button(self, btn):
        if btn in (BTN_SELECT, BTN_BACK):
            return BadgeScreen(oled)
        return self

    def render(self):
        self.oled.fill(0)

        wri10.set_textpos(self.oled, 0, 0)
        wri10.printstring("Badge code git")

        y = wri10.font.height() + 4
        wri6.set_textpos(self.oled, y, 0)
        wri6.printstring("github.com/ks000/ bsides_badge")

        self.oled.show()

badge_screens = [("Fetch Name", FetchNameScreen),
                 ("Code git", CodeRepoScreen)]

class BadgeScreen(ListScreen):
    def __init__(self, oled):
        super().__init__(oled, "Badge setup", badge_screens)

    def on_select(self, index):
        cls = badge_screens[index][1]
        return cls(self.oled)

    def on_back(self):
        save_params()
        return MenuScreen(self.oled)

# -----------------------
# Sponsors screens
# -----------------------

class SponsorsScreen(Screen):
    def __init__(self, oled):
        super().__init__(oled)

        # Import logos dynamically
        LOGO_FOLDER = "logos"
        if LOGO_FOLDER not in sys.path:
            sys.path.append(LOGO_FOLDER)
        logo_files = sorted([f for f in os.listdir(LOGO_FOLDER) if f.endswith(".py")])

        self.logos = []
        self.current_logo = 0
        for f in logo_files:
            module_name = f[:-3]  # strip '.py'
            mod = __import__(module_name)
            if hasattr(mod, "fb"):
                self.logos.append(mod.fb)
            else:
                print(f"Warning: {module_name} has no attribute 'fb'")

        if not self.logos:
            raise RuntimeError("No valid logos found!")

    def render(self):
        self.oled.fill(0)
        self.oled.blit(self.logos[self.current_logo], 0, 0)
        self.oled.show()

    async def handle_button(self, btn):
        if btn == BTN_NEXT:
            self.current_logo = (self.current_logo + 1) % len(self.logos)
        elif btn == BTN_PREV:
            self.current_logo = (self.current_logo - 1) % len(self.logos)
        if btn == BTN_BACK:
            return MenuScreen(self.oled)
        return self

# -----------------------
# Text screens
# -----------------------

class TextScreen(Screen):
    def __init__(self, oled, writer, text):
        super().__init__(oled)
        self.wri = writer

        # wrap long text
        self.text = self._wrap_text(text)

        # metrics
        self.line_height = self.wri.font.height()
        self.rows = oled.height // self.line_height
        self.offset = 0

    def _wrap_text(self, text):
        lines = []
        # split paragraphs by explicit newline
        for para in text.split("\n"):
            words = para.split()
            line = ""
            for word in words:
                test_line = (line + " " + word).strip()
                if self.wri.stringlen(test_line) <= self.oled.width:
                    line = test_line
                else:
                    lines.append(line)
                    line = word
            if line:
                lines.append(line)
            if para == "":  # preserve blank lines
                lines.append("")
        return lines

    def render(self):
        self.oled.fill(0)
        y = 0
        for i in range(self.offset, min(len(self.text), self.offset + self.rows)):
            self.wri.set_textpos(self.oled, y, 0)
            self.wri.printstring(self.text[i])
            y += self.line_height
        self.oled.show()

    async def handle_button(self, btn):
        if btn == BTN_NEXT and self.offset + self.rows < len(self.text):
            self.offset += 1
        elif btn == BTN_PREV and self.offset > 0:
            self.offset -= 1
        elif btn == BTN_BACK:
            return MenuScreen(self.oled)
        return self

class AboutScreen(TextScreen):
    def __init__(self, oled):
        text = (
            "BSides is a worldwide infosec event format, organized by the local infosec community in every city it is held. BSides Tallinn is organized by a non-profit core-team, volunteers and sponsors since 2021.\n\n"
            "One core difference of all BSides events is that the talks on the stage are proposed by anyone and selected by a program committee - professionals representing the organizers, private companies, academia, the state, freelancers.\n\n"
            "Talks, presentations, demos, proof-of-concepts across a very broad spectrum of infosec topics. All of the content is proposed by community members."
        )
        super().__init__(oled, wri6, text)


class OurteamScreen(TextScreen):
    def __init__(self, oled):
        text = (
            "Organizers: Hans, Silvia, Matis, Liisa, Johanna, Martti, Rainer, Kadi\n\n"
            "Badge: Konstantin\n\n"
            "Volunteers: Elis, Elle, Kristo, Merli, Hanna, Liam, Sten"
        )
        super().__init__(oled, wri6, text)

class SnakeScreen(Screen):
    """
    Snake for 128x64 SSD1306.
    - Grid: 4x4 px cells
    - HUD row at top with boundary line; full border around playfield.
    - Controls:
        NEXT  -> turn right
        PREV  -> turn left
        SELECT-> pause/resume (or restart on game over)
        BACK  -> exit to menu

    NOTE: In ui_task(), do not auto-render when current screen is SnakeScreen.
    """
    CELL = 4
    DIRS = [(1,0), (0,1), (-1,0), (0,-1)]  # R, D, L, U

    def __init__(self, oled):
        super().__init__(oled)

        # ----- GEOMETRY -----
        self.HUD_H = wri6.font.height()                 # your build reports 14
        self.GRID_W = OLED_WIDTH // self.CELL           # 32
        self.GRID_H = (OLED_HEIGHT - self.HUD_H) // self.CELL  # e.g. 12
        self.GRID_Y0 = self.HUD_H                       # playfield starts below HUD

        # Playfield pixel bounds
        self.x_left   = 0
        self.x_right  = self.oled.width - 1            # 127
        self.y_top    = self.GRID_Y0
        self.y_bot    = self.GRID_Y0 + self.GRID_H * self.CELL - 1  # e.g. 61

        # ----- GAME STATE -----
        self.running = True
        self.paused = False
        self.tick_ms_base = 180
        self.tick_ms_min  = 70
        self.tick_ms = self.tick_ms_base
        self.score = 0

        try:
            self.high_score = snake_high_score.value
        except NameError:
            self.high_score = 0

        self.dir_idx = 0  # right
        cx = self.GRID_W // 2
        cy = self.GRID_H // 2
        self.snake = [(cx, cy), (cx-1, cy), (cx-2, cy), (cx-3, cy)]
        self.food = self._rand_empty_cell()
        self.game_over = False

        # Start loop last
        self._task = asyncio.create_task(self._loop())
        self.render()

    # ---------- helpers ----------
    def _cell_free(self, x, y):
        return (x, y) not in self.snake

    def _rand_empty_cell(self):
        for _ in range(200):
            x = urandom.getrandbits(5) % self.GRID_W     # 0..31
            y = urandom.getrandbits(5) % self.GRID_H     # 0..GRID_H-1
            if self._cell_free(x, y):
                return (x, y)
        for yy in range(self.GRID_H):
            for xx in range(self.GRID_W):
                if self._cell_free(xx, yy):
                    return (xx, yy)
        return (0, 0)

    def _turn_left(self):
        self.dir_idx = (self.dir_idx - 1) % 4

    def _turn_right(self):
        self.dir_idx = (self.dir_idx + 1) % 4

    def _advance(self):
        dx, dy = self.DIRS[self.dir_idx]
        hx, hy = self.snake[0]
        nx, ny = hx + dx, hy + dy

        # grid-bounds collision
        if nx < 0 or nx >= self.GRID_W or ny < 0 or ny >= self.GRID_H:
            self._end_game()
            return

        # self collision
        if (nx, ny) in self.snake:
            self._end_game()
            return

        # move
        self.snake.insert(0, (nx, ny))

        # eat
        if (nx, ny) == self.food:
            self.score += 1
            self.tick_ms = max(self.tick_ms_min, self.tick_ms_base - self.score * 6)
            self.food = self._rand_empty_cell()
        else:
            self.snake.pop()

    def _end_game(self):
        self.game_over = True
        if self.score > self.high_score:
            self.high_score = self.score
            try:
                snake_high_score.value = self.high_score
                save_params()
            except Exception:
                pass
        # show overlay immediately
        self.render()

    async def _loop(self):
        try:
            while self.running:
                if not self.paused and not self.game_over:
                    self._advance()
                    self.render()
                await asyncio.sleep_ms(self.tick_ms)
        except asyncio.CancelledError:
            return

    # ---------- drawing ----------
    def _draw_hud(self):
        # Clear HUD band
        self.oled.fill_rect(0, 0, self.oled.width, self.HUD_H, 0)

        # Left: score
        wri6.set_textpos(self.oled, 0, 0)
        wri6.printstring("SCORE:{:d}".format(self.score))

        # Right: high score
        hi_txt = "HI:{:d}".format(self.high_score)
        x_hi = self.oled.width - wri6.stringlen(hi_txt)
        wri6.set_textpos(self.oled, 0, x_hi)
        wri6.printstring(hi_txt)

        # Top border (under HUD)
        self.oled.hline(0, self.HUD_H - 1, self.oled.width, 1)

    def render(self):
        self.oled.fill(0)

        # HUD
        self._draw_hud()

        # Food (offset by HUD)
        fx, fy = self.food
        self.oled.fill_rect(fx*self.CELL, self.GRID_Y0 + fy*self.CELL, self.CELL, self.CELL, 1)

        # Snake
        for i, (x, y) in enumerate(self.snake):
            px = x * self.CELL
            py = self.GRID_Y0 + y * self.CELL
            if i == 0:
                self.oled.fill_rect(px, py, self.CELL, self.CELL, 1)
            else:
                self.oled.rect(px, py, self.CELL, self.CELL, 1)

        # Overlays
        if self.paused:
            self._overlay_center("PAUSED")
        elif self.game_over:
            self._overlay_gameover()

        # --- Draw playfield borders LAST so they stay visible ---
        # Left/right verticals span the full playfield height.
        self.oled.vline(self.x_left,  self.y_top, self.y_bot - self.y_top + 1, 1)
        self.oled.vline(self.x_right, self.y_top, self.y_bot - self.y_top + 1, 1)
        # Bottom border
        self.oled.hline(0, self.y_bot, self.oled.width, 1)

        self.oled.show()

    def _overlay_center(self, text):
        """Draw a single-line centered overlay; safely clamps width."""
        pad = 2
        fh = wri6.font.height()
        max_text_w = self.oled.width - 2 * pad

        # Clamp/ellipsize if too wide
        if wri6.stringlen(text) > max_text_w:
            base = text
            while base and wri6.stringlen(base + "...") > max_text_w:
                base = base[:-1]
            text = (base + "...") if base else "..."

        tw = wri6.stringlen(text)
        box_w = min(self.oled.width, tw + 2 * pad)
        box_h = fh + 2 * pad

        x = (self.oled.width - box_w) // 2
        if x < 0: x = 0
        y = self.GRID_Y0 + (self.GRID_H * self.CELL - box_h) // 2
        if y < self.GRID_Y0: y = self.GRID_Y0

        # box
        self.oled.fill_rect(x, y, box_w, box_h, 0)
        self.oled.rect(x, y, box_w, box_h, 1)

        # text
        tw = wri6.stringlen(text)  # recalc in case truncated
        tx = x + (box_w - tw) // 2
        if tx < 0: tx = 0
        wri6.set_textpos(self.oled, y + pad, tx)
        wri6.printstring(text)

    def _overlay_gameover(self):
        """Two-line centered overlay that always fits."""
        lines = ["GAME OVER", "SELECT=Restart"]
        pad = 2
        gap = 1
        fh = wri6.font.height()

        # Ellipsize each line if needed
        trimmed = []
        for s in lines:
            if wri6.stringlen(s) <= self.oled.width - 2 * pad:
                trimmed.append(s)
            else:
                base = s
                while base and wri6.stringlen(base + "...") > self.oled.width - 2 * pad:
                    base = base[:-1]
                trimmed.append((base + "...") if base else "...")
        lines = trimmed

        max_line_w = max(wri6.stringlen(s) for s in lines)
        box_w = min(self.oled.width, max_line_w + 2 * pad)
        box_h = 2 * fh + gap + 2 * pad

        x = (self.oled.width - box_w) // 2
        if x < 0: x = 0
        y = self.GRID_Y0 + (self.GRID_H * self.CELL - box_h) // 2
        if y < self.GRID_Y0: y = self.GRID_Y0

        # box
        self.oled.fill_rect(x, y, box_w, box_h, 0)
        self.oled.rect(x, y, box_w, box_h, 1)

        # lines
        ty = y + pad
        for s in lines:
            tw = wri6.stringlen(s)
            tx = x + (box_w - tw) // 2
            if tx < 0: tx = 0
            wri6.set_textpos(self.oled, ty, tx)
            wri6.printstring(s)
            ty += fh + gap

    # ---------- input ----------
    async def handle_button(self, btn):
        if not self.game_over and not self.paused:
            if btn == BTN_NEXT:
                self._turn_right()
            elif btn == BTN_PREV:
                self._turn_left()

        if btn == BTN_SELECT:
            if self.game_over:
                # cancel old loop before restart
                try:
                    if self._task:
                        self._task.cancel()
                        await asyncio.sleep_ms(0)
                except Exception:
                    pass
                # re-init fresh
                self.__init__(self.oled)
                return self
            else:
                self.paused = not self.paused
                self.render()
                return self

        if btn == BTN_BACK:
            self.running = False
            try:
                if self._task:
                    self._task.cancel()
            except Exception:
                pass
            return MenuScreen(self.oled)

        return self

# -----------------------
# Menu screen
# -----------------------

class MenuScreen(Screen):
    items = [("About", AboutScreen),
             ("Sponsors", SponsorsScreen),
             ("Our team", OurteamScreen),
             ("Lights", LightsScreen),
             ("Badge", BadgeScreen),
             ("Snake", SnakeScreen)]

    def __init__(self, oled):
        super().__init__(oled)
        self.index = 0
        self.render()

    def render(self):
        self.oled.fill(0)
        wri20.set_textpos(self.oled, 17, 20)
        wri20.printstring(MenuScreen.items[self.index][0])
        self.oled.show()

    async def handle_button(self, btn):
        if btn == BTN_NEXT:
            self.index = (self.index+1) % len(MenuScreen.items)
            self.render()
        elif btn == BTN_PREV:
            self.index = (self.index-1) % len(MenuScreen.items)
            self.render()
        elif btn == BTN_SELECT:
            return MenuScreen.items[self.index][1](self.oled)
        return self

# -----------------------
# NeoPixel effects
# -----------------------
def hsv_to_rgb(h, s, v):
    """Convert hue [0–360], saturation [0–1], value [0–1] to RGB tuple."""
    h = h % 360
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return (int((r + m) * 255),
            int((g + m) * 255),
            int((b + m) * 255))

def led_eff_off(np, oldstate):
    np.fill((0,0,0))
    return oldstate

def led_eff_rainbow(np, oldstate):
    """Rainbow running around the circle"""
    pos = oldstate or 0
    for i in range(len(np)):
        pixel_hue = ((i * 360 // len(np)) + pos) % 360
        np[i] = hsv_to_rgb(pixel_hue, led_sat.value/100, led_brightness.value/100)
    return (pos + led_speed.value/10) % 360

def led_eff_breathe(np, oldstate):
    """All LEDs smoothly brighten and dim"""
    br, d = oldstate or (0, 1)
    rgb = hsv_to_rgb(led_hue.value, led_sat.value/100, br*led_brightness.value/100)

    for i in range(len(np)):
        np[i] = rgb
    br += d * led_speed.value / 1000
    if br >= 1.0:
        br = 1.0
        d = -1
    elif br <= 0.0:
        br = 0.0
        d = 1
    return (br, d)

def led_eff_comet(np, oldstate, tail=5):
    """Single bright dot with fading tail"""
    state = oldstate or 0
    head_idx = int(state) % len(np)
    fade_coeff = 0.5 + ((led_speed.maxval - led_speed.value) / led_speed.maxval * 0.4)
    # fade all LEDs slightly
    for i in range(len(np)):
        np[i] = tuple(int(x * fade_coeff) for x in np[i])
    # light the comet head
    np[head_idx] = hsv_to_rgb(led_hue.value, led_sat.value/100, led_brightness.value/100)
    
    return state + led_speed.value / 100


def led_eff_startup(np, oldstate):
    head, phase = oldstate or (0, 0)

    rgb_on = hsv_to_rgb(led_hue.value, led_sat.value/100, led_brightness.value/100)
    rgb_off = (0,0,0)
    for i in range(len(np)):
        rgb = rgb_on if (i <= head) == (phase == 0) else rgb_off
        np[i] = rgb
    
    if head < len(np) - 1:
        return (head + 1, phase)
    elif phase == 0:
        return (0, 1)
    else:
        return None

async def neopixel_task(np):
    global led_effect
    global led_effects
    global led_startup
    t = None
    prev_effect = 0
    led_effects = [("Off", led_eff_off),
                   ("Rainbow", led_eff_rainbow),
                   ("Breathe", led_eff_breathe),
                   ("Comet", led_eff_comet)]
    while True:
        if led_startup == True:
            t = led_eff_startup(np, t)
            if t == None:
                led_startup = False
        else:
            if prev_effect != led_effect.value:
                t = None
                prev_effect = led_effect.value
            if led_effect.value in range(len(led_effects)):
                t = led_effects[led_effect.value][1](np, t)
        np.write()
        await asyncio.sleep_ms(int(1000/NEOPIXEL_FPS))

# -----------------------
# UI manager
# -----------------------
screen = None

async def ui_task(oled):
    global screen

    while True:
        await button_event.wait()
        button_event.clear()
        btn = last_button
        if screen == None:
            screen = MenuScreen(oled)
        screen = await screen.handle_button(btn)

        # Only auto-render non-Snake screens
        if not isinstance(screen, SnakeScreen):
            screen.render()

def show_bsides_logo(oled):
    oled.fill(0)
    oled.blit(bsides_logo.fb, 0, 0)
    oled.show()

def wrap_text(text, writer, max_width, max_height):
    line_height = writer.font.height()
    max_rows = max_height // line_height

    words = text.split()
    lines, line = [], ""

    for word in words:
        # if a word itself is too long, split it at character level
        while writer.stringlen(word) > max_width:
            for i in range(1, len(word) + 1):
                if writer.stringlen(word[:i]) > max_width:
                    lines.append(word[:i-1])
                    word = word[i-1:]
                    break
        test_line = (line + " " + word).strip()
        if writer.stringlen(test_line) <= max_width:
            line = test_line
        else:
            lines.append(line)
            line = word
        if len(lines) >= max_rows:
            break
    if line and len(lines) < max_rows:
        lines.append(line)

    # truncate if too many lines
    if len(lines) > max_rows:
        lines = lines[:max_rows]
        # replace last line with ellipsis if there’s space
        if writer.stringlen(lines[-1] + "...") <= max_width:
            lines[-1] += "..."
        else:
            lines[-1] = lines[-1][:-3] + "..."

    return lines

def show_username(oled, name):
    global username_lines
    oled.fill(0)

    if not username_lines:
        username_lines = wrap_text(name, username_wri, oled.width, oled.height)
    total_height = len(username_lines) * username_wri.font.height()
    y = (oled.height - total_height) // 2

    for line in username_lines:
        x = (oled.width - username_wri.stringlen(line)) // 2
        username_wri.set_textpos(oled, y, x)
        username_wri.printstring(line)
        y += username_wri.font.height()

    oled.show()

async def inactivity_task(oled):
    global screen
    last_toggle = time.ticks_ms()
    showing_logo = True

    while True:
        await asyncio.sleep_ms(500)
        inactive = (screen == None or isinstance(screen, MenuScreen)) and time.ticks_diff(time.ticks_ms(), last_activity) > INACTIVITY_TIMEOUT
        if inactive:
            now = time.ticks_ms()
            if time.ticks_diff(now, last_toggle) >= LOGO_PERIOD:
                showing_logo = not showing_logo
                last_toggle = now

            if showing_logo or not USERNAME:
                show_bsides_logo(oled)
            else:
                show_username(oled, USERNAME)

# -----------------------
# Main
# -----------------------
async def main():
    global button_event, last_activity
    np = init_neopixels()
    button_event = asyncio.Event()
    last_activity = time.ticks_ms()

    setup_buttons()
    load_params()
    show_bsides_logo(oled)
    print("Username: {}".format(USERNAME))

    await asyncio.gather(ui_task(oled), inactivity_task(oled), neopixel_task(np))

try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
