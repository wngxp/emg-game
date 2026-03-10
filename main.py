import random
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass

import pygame

try:
    import serial
except Exception:
    serial = None


# -----------------------------
# Configuration
# -----------------------------
WIDTH, HEIGHT = 900, 600
PANEL_WIDTH = 280
PLAY_WIDTH = WIDTH - PANEL_WIDTH
FPS = 60

GRAVITY = 0.45
FLAP_VELOCITY = -8.5
PIPE_SPEED = 4
PIPE_WIDTH = 90
PIPE_GAP = 190
PIPE_SPAWN_MS = 1500
GROUND_HEIGHT = 70

EMG_PORT = "COM6"
EMG_BAUDRATE = 2000
EMG_TIMEOUT = 0.05

CALIBRATION_SECONDS = 2.0
THRESHOLD_MULTIPLIER = 3.5
MIN_THRESHOLD = 20.0
TRIGGER_DEBOUNCE_SEC = 0.18
SMOOTHING = 0.25
HYSTERESIS_RELEASE_RATIO = 0.6
MIN_HYSTERESIS_GAP = 5.0

GRAPH_MIN = 0.0
GRAPH_MAX = 2500.0
GRAPH_POINTS = 180


@dataclass
class EmgState:
    raw_value: float = 0.0
    baseline: float = 0.0
    threshold: float = 50.0
    release_threshold: float = 40.0
    connected: bool = False
    calibrated: bool = False
    calibrating: bool = False
    calibration_progress: float = 0.0
    trigger: bool = False
    message: str = "Starting EMG reader..."


class EMGReader:
    """
    Reads EMG values from a serial stream.

    Expected input per line:
    - A plain integer/float value (e.g. 123)
    - Or CSV-like line where first parseable number is used.
    """

    def __init__(self, port: str, baudrate: int):
        self.port = port
        self.baudrate = baudrate
        self.state = EmgState()
        self._running = False
        self._thread = None
        self._last_trigger_time = 0.0
        self._smoothed = 0.0
        self._trigger_armed = True

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)

    def _parse_value(self, line: str):
        line = line.strip()
        if not line:
            return None

        # Handle debug-style byte-string repr lines: b'11,14,...\\r\\n'
        if (line.startswith("b'") and line.endswith("'")) or (
            line.startswith('b"') and line.endswith('"')
        ):
            line = line[2:-1].strip()

        # Multi-channel boards: always use channel 1 (first CSV value).
        if "," in line:
            first = line.split(",", 1)[0].strip()
            try:
                return float(first)
            except ValueError:
                pass

        # Try direct parse first
        try:
            return float(line)
        except ValueError:
            pass

        # Fallback: find first numeric token in comma/space separated data
        for token in line.replace(",", " ").split():
            try:
                return float(token)
            except ValueError:
                continue
        return None

    def _run(self):
        if serial is None:
            self.state.message = "pyserial missing. Install requirements."
            return

        ser = None
        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=EMG_TIMEOUT)
            self.state.connected = True
            self.state.message = f"Connected to {self.port} @ {self.baudrate}"
            self.state.calibrating = True
            self.state.calibration_progress = 0.0
            self.state.calibrated = False
            self.state.message = "Calibrating... relax muscle."

            # Calibration phase: gather baseline + noise estimate
            samples = []
            start = time.time()
            while self._running and (time.time() - start) < CALIBRATION_SECONDS:
                elapsed = time.time() - start
                self.state.calibration_progress = min(1.0, elapsed / CALIBRATION_SECONDS)
                raw = ser.readline().decode(errors="ignore")
                value = self._parse_value(raw)
                if value is not None:
                    samples.append(value)

            if not samples:
                self.state.message = "No EMG data received during calibration."
            else:
                baseline = sum(samples) / len(samples)
                variance = sum((x - baseline) ** 2 for x in samples) / max(len(samples), 1)
                std_dev = variance ** 0.5
                threshold = max(MIN_THRESHOLD, baseline + THRESHOLD_MULTIPLIER * std_dev)
                release_from_ratio = baseline + HYSTERESIS_RELEASE_RATIO * max(threshold - baseline, 0.0)
                release_threshold = min(release_from_ratio, threshold - MIN_HYSTERESIS_GAP)
                release_threshold = max(baseline, release_threshold)

                self.state.baseline = baseline
                self.state.threshold = threshold
                self.state.release_threshold = release_threshold
                self.state.calibrated = True
                self.state.message = "Calibrated. Press ENTER to start."

            self.state.calibrating = False
            self.state.calibration_progress = 1.0

            # Streaming phase
            while self._running:
                raw = ser.readline().decode(errors="ignore")
                value = self._parse_value(raw)
                if value is None:
                    continue

                self._smoothed = (1.0 - SMOOTHING) * self._smoothed + SMOOTHING * value
                self.state.raw_value = self._smoothed

                now = time.time()
                is_peak = self.state.raw_value >= self.state.threshold
                if (
                    is_peak
                    and self._trigger_armed
                    and (now - self._last_trigger_time) >= TRIGGER_DEBOUNCE_SEC
                ):
                    self.state.trigger = True
                    self._last_trigger_time = now
                    self._trigger_armed = False
                elif self.state.raw_value <= self.state.release_threshold:
                    self._trigger_armed = True

        except Exception as exc:
            self.state.message = f"EMG connection error: {exc}"
        finally:
            self.state.connected = False
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass

    def consume_trigger(self) -> bool:
        if self.state.trigger:
            self.state.trigger = False
            return True
        return False

    def clear_trigger(self):
        self.state.trigger = False


class Bird:
    def __init__(self):
        self.x = PLAY_WIDTH * 0.25
        self.y = HEIGHT * 0.45
        self.radius = 20
        self.velocity = 0.0

    def flap(self):
        self.velocity = FLAP_VELOCITY

    def update(self):
        self.velocity += GRAVITY
        self.y += self.velocity

    def rect(self):
        return pygame.Rect(
            int(self.x - self.radius),
            int(self.y - self.radius),
            self.radius * 2,
            self.radius * 2,
        )

    def draw(self, screen):
        pygame.draw.circle(screen, (255, 216, 70), (int(self.x), int(self.y)), self.radius)
        pygame.draw.circle(screen, (0, 0, 0), (int(self.x + 7), int(self.y - 6)), 3)


class Pipe:
    def __init__(self):
        self.x = PLAY_WIDTH + PIPE_WIDTH
        gap_y = random.randint(130, HEIGHT - GROUND_HEIGHT - 130)
        self.top_h = gap_y - PIPE_GAP // 2
        self.bottom_y = gap_y + PIPE_GAP // 2
        self.passed = False

    def update(self):
        self.x -= PIPE_SPEED

    def offscreen(self):
        return self.x + PIPE_WIDTH < 0

    def collides(self, bird_rect: pygame.Rect) -> bool:
        top_rect = pygame.Rect(int(self.x), 0, PIPE_WIDTH, int(self.top_h))
        bottom_rect = pygame.Rect(
            int(self.x),
            int(self.bottom_y),
            PIPE_WIDTH,
            HEIGHT - int(self.bottom_y) - GROUND_HEIGHT,
        )
        return bird_rect.colliderect(top_rect) or bird_rect.colliderect(bottom_rect)

    def draw(self, screen):
        green = (38, 171, 73)
        dark = (25, 122, 51)

        top_rect = pygame.Rect(int(self.x), 0, PIPE_WIDTH, int(self.top_h))
        bot_rect = pygame.Rect(
            int(self.x),
            int(self.bottom_y),
            PIPE_WIDTH,
            HEIGHT - int(self.bottom_y) - GROUND_HEIGHT,
        )
        pygame.draw.rect(screen, green, top_rect)
        pygame.draw.rect(screen, green, bot_rect)

        pygame.draw.rect(screen, dark, pygame.Rect(int(self.x - 4), int(self.top_h - 18), PIPE_WIDTH + 8, 18))
        pygame.draw.rect(screen, dark, pygame.Rect(int(self.x - 4), int(self.bottom_y), PIPE_WIDTH + 8, 18))


def draw_background(screen):
    sky = (132, 205, 250)
    ground = (201, 160, 95)
    grass = (90, 196, 75)
    panel_bg = (27, 33, 44)

    screen.fill(panel_bg)
    pygame.draw.rect(screen, sky, (0, 0, PLAY_WIDTH, HEIGHT - GROUND_HEIGHT))
    pygame.draw.rect(screen, grass, (0, HEIGHT - GROUND_HEIGHT - 8, PLAY_WIDTH, 8))
    pygame.draw.rect(screen, ground, (0, HEIGHT - GROUND_HEIGHT, PLAY_WIDTH, GROUND_HEIGHT))
    pygame.draw.line(screen, (50, 60, 80), (PLAY_WIDTH, 0), (PLAY_WIDTH, HEIGHT), 2)


def draw_hud(screen, font, big_font, score, game_over):
    score_txt = big_font.render(str(score), True, (255, 255, 255))
    screen.blit(score_txt, (PLAY_WIDTH // 2 - score_txt.get_width() // 2, 20))

    if game_over:
        overlay = pygame.Surface((PLAY_WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 110))
        screen.blit(overlay, (0, 0))

        title = big_font.render("Game Over", True, (255, 255, 255))
        tip = font.render("Press R to restart", True, (255, 255, 255))
        screen.blit(title, (PLAY_WIDTH // 2 - title.get_width() // 2, HEIGHT // 2 - 35))
        screen.blit(tip, (PLAY_WIDTH // 2 - tip.get_width() // 2, HEIGHT // 2 + 20))


def draw_menu(screen, font, big_font, state: EmgState):
    cx = PLAY_WIDTH // 2

    title = big_font.render("EMG Flappy Bird", True, (255, 255, 255))
    screen.blit(title, (cx - title.get_width() // 2, 110))

    if state.calibrated:
        primary = "Calibration complete"
        secondary = "Press ENTER to start"
    elif state.calibrating:
        primary = "Calibrating... keep muscle relaxed"
        secondary = f"Progress: {int(state.calibration_progress * 100)}%"
    else:
        primary = state.message
        secondary = "Waiting for EMG connection"

    line1 = font.render(primary, True, (255, 255, 255))
    line2 = font.render(secondary, True, (255, 255, 255))
    line3 = font.render("In game: Flex EMG or press SPACE to flap", True, (255, 255, 255))

    screen.blit(line1, (cx - line1.get_width() // 2, 230))
    screen.blit(line2, (cx - line2.get_width() // 2, 265))
    screen.blit(line3, (cx - line3.get_width() // 2, 310))


def _map_signal_to_graph_y(value, graph_y, graph_h):
    clamped = max(GRAPH_MIN, min(GRAPH_MAX, value))
    ratio = (clamped - GRAPH_MIN) / (GRAPH_MAX - GRAPH_MIN)
    return int(graph_y + graph_h - ratio * graph_h)


def draw_signal_panel(screen, font, state: EmgState, history):
    panel_x = PLAY_WIDTH
    panel_w = PANEL_WIDTH

    title = font.render("EMG Monitor (CH1)", True, (232, 238, 248))
    screen.blit(title, (panel_x + 14, 14))

    status = "CONNECTED" if state.connected else "DISCONNECTED"
    status_color = (86, 200, 120) if state.connected else (220, 90, 90)
    status_txt = font.render(status, True, status_color)
    screen.blit(status_txt, (panel_x + 14, 44))

    msg = font.render(state.message[:28], True, (190, 200, 216))
    screen.blit(msg, (panel_x + 14, 74))

    val_txt = font.render(f"raw: {state.raw_value:7.1f}", True, (232, 238, 248))
    thr_txt = font.render(f"thr: {state.threshold:7.1f}", True, (232, 238, 248))
    rel_txt = font.render(f"rel: {state.release_threshold:7.1f}", True, (232, 238, 248))
    screen.blit(val_txt, (panel_x + 14, 112))
    screen.blit(thr_txt, (panel_x + 14, 140))
    screen.blit(rel_txt, (panel_x + 14, 168))

    graph_x = panel_x + 14
    graph_y = 210
    graph_w = panel_w - 28
    graph_h = 350

    pygame.draw.rect(screen, (20, 25, 34), (graph_x, graph_y, graph_w, graph_h))
    pygame.draw.rect(screen, (58, 70, 94), (graph_x, graph_y, graph_w, graph_h), 1)

    for i in range(6):
        y = graph_y + int(i * graph_h / 5)
        pygame.draw.line(screen, (40, 50, 68), (graph_x, y), (graph_x + graph_w, y), 1)

    for marker in [0, 500, 1000, 1500, 2000, 2500]:
        y = _map_signal_to_graph_y(marker, graph_y, graph_h)
        label = font.render(str(marker), True, (130, 145, 170))
        screen.blit(label, (graph_x + 4, y - 12))

    if len(history) > 1:
        points = []
        step = graph_w / max(GRAPH_POINTS - 1, 1)
        start_idx = max(0, len(history) - GRAPH_POINTS)
        visible = list(history)[start_idx:]
        for i, value in enumerate(visible):
            x = int(graph_x + i * step)
            y = _map_signal_to_graph_y(value, graph_y, graph_h)
            points.append((x, y))
        if len(points) >= 2:
            pygame.draw.lines(screen, (107, 185, 255), False, points, 2)

    thr_y = _map_signal_to_graph_y(state.threshold, graph_y, graph_h)
    rel_y = _map_signal_to_graph_y(state.release_threshold, graph_y, graph_h)
    pygame.draw.line(screen, (255, 214, 92), (graph_x, thr_y), (graph_x + graph_w, thr_y), 1)
    pygame.draw.line(screen, (255, 160, 120), (graph_x, rel_y), (graph_x + graph_w, rel_y), 1)


def run_game():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("EMG Flappy Bird")
    clock = pygame.time.Clock()

    font = pygame.font.SysFont("consolas", 22)
    big_font = pygame.font.SysFont("consolas", 56, bold=True)

    emg = EMGReader(EMG_PORT, EMG_BAUDRATE)
    emg.start()

    bird = Bird()
    pipes = []
    score = 0
    game_state = "menu"
    signal_history = deque(maxlen=GRAPH_POINTS)

    spawn_event = pygame.USEREVENT + 1
    pygame.time.set_timer(spawn_event, PIPE_SPAWN_MS)

    try:
        while True:
            clock.tick(FPS)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return

                if event.type == spawn_event and game_state == "playing":
                    pipes.append(Pipe())

                if event.type == pygame.KEYDOWN:
                    if game_state == "menu" and event.key == pygame.K_RETURN:
                        if emg.state.calibrated:
                            bird = Bird()
                            pipes = []
                            score = 0
                            game_state = "playing"
                            emg.clear_trigger()
                    if event.key == pygame.K_SPACE and game_state == "playing":
                        bird.flap()
                    if event.key == pygame.K_r and game_state == "game_over":
                        bird = Bird()
                        pipes = []
                        score = 0
                        game_state = "playing"
                        emg.clear_trigger()

            if game_state == "playing":
                if emg.consume_trigger():
                    bird.flap()

                bird.update()
                bird_rect = bird.rect()

                # Collision with boundaries
                if bird.y - bird.radius < 0 or bird.y + bird.radius > (HEIGHT - GROUND_HEIGHT):
                    game_state = "game_over"

                for pipe in pipes:
                    pipe.update()

                    if pipe.collides(bird_rect):
                        game_state = "game_over"

                    if (not pipe.passed) and pipe.x + PIPE_WIDTH < bird.x:
                        pipe.passed = True
                        score += 1

                pipes = [p for p in pipes if not p.offscreen()]

            signal_history.append(emg.state.raw_value)

            draw_background(screen)
            if game_state == "menu":
                draw_menu(screen, font, big_font, emg.state)
            else:
                for pipe in pipes:
                    pipe.draw(screen)
                bird.draw(screen)
                draw_hud(screen, font, big_font, score, game_state == "game_over")

            draw_signal_panel(screen, font, emg.state, signal_history)
            pygame.display.flip()
    finally:
        emg.stop()
        pygame.quit()


if __name__ == "__main__":
    try:
        run_game()
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(0)
