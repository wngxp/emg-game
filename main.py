import random
import sys
import threading
import time
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


@dataclass
class EmgState:
    raw_value: float = 0.0
    baseline: float = 0.0
    threshold: float = 50.0
    connected: bool = False
    calibrated: bool = False
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

            # Calibration phase: gather baseline + noise estimate
            samples = []
            start = time.time()
            while self._running and (time.time() - start) < CALIBRATION_SECONDS:
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

                self.state.baseline = baseline
                self.state.threshold = threshold
                self.state.calibrated = True
                self.state.message = "Calibrated. Flex to flap."

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
                if is_peak and (now - self._last_trigger_time) >= TRIGGER_DEBOUNCE_SEC:
                    self.state.trigger = True
                    self._last_trigger_time = now

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


class Bird:
    def __init__(self):
        self.x = WIDTH * 0.25
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
        self.x = WIDTH + PIPE_WIDTH
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

    screen.fill(sky)
    pygame.draw.rect(screen, grass, (0, HEIGHT - GROUND_HEIGHT - 8, WIDTH, 8))
    pygame.draw.rect(screen, ground, (0, HEIGHT - GROUND_HEIGHT, WIDTH, GROUND_HEIGHT))


def draw_hud(screen, font, big_font, score, state: EmgState, game_over):
    score_txt = big_font.render(str(score), True, (255, 255, 255))
    screen.blit(score_txt, (WIDTH // 2 - score_txt.get_width() // 2, 20))

    emg_txt = font.render(
        f"EMG: {state.raw_value:.1f} | threshold: {state.threshold:.1f}",
        True,
        (20, 20, 20),
    )
    screen.blit(emg_txt, (18, 18))

    status = "CONNECTED" if state.connected else "DISCONNECTED"
    status_color = (20, 120, 20) if state.connected else (180, 50, 40)
    st = font.render(f"{status} | {state.message}", True, status_color)
    screen.blit(st, (18, 46))

    control = font.render("Control: EMG spike or SPACE", True, (20, 20, 20))
    screen.blit(control, (18, 74))

    if game_over:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 110))
        screen.blit(overlay, (0, 0))

        title = big_font.render("Game Over", True, (255, 255, 255))
        tip = font.render("Press R to restart", True, (255, 255, 255))
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, HEIGHT // 2 - 35))
        screen.blit(tip, (WIDTH // 2 - tip.get_width() // 2, HEIGHT // 2 + 20))


def run_game():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("EMG Flappy Bird")
    clock = pygame.time.Clock()

    font = pygame.font.SysFont("consolas", 24)
    big_font = pygame.font.SysFont("consolas", 56, bold=True)

    emg = EMGReader(EMG_PORT, EMG_BAUDRATE)
    emg.start()

    bird = Bird()
    pipes = []
    score = 0
    game_over = False

    spawn_event = pygame.USEREVENT + 1
    pygame.time.set_timer(spawn_event, PIPE_SPAWN_MS)

    try:
        while True:
            clock.tick(FPS)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return

                if event.type == spawn_event and not game_over:
                    pipes.append(Pipe())

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE and not game_over:
                        bird.flap()
                    if event.key == pygame.K_r and game_over:
                        bird = Bird()
                        pipes = []
                        score = 0
                        game_over = False

            if not game_over:
                if emg.consume_trigger():
                    bird.flap()

                bird.update()
                bird_rect = bird.rect()

                # Collision with boundaries
                if bird.y - bird.radius < 0 or bird.y + bird.radius > (HEIGHT - GROUND_HEIGHT):
                    game_over = True

                for pipe in pipes:
                    pipe.update()

                    if pipe.collides(bird_rect):
                        game_over = True

                    if (not pipe.passed) and pipe.x + PIPE_WIDTH < bird.x:
                        pipe.passed = True
                        score += 1

                pipes = [p for p in pipes if not p.offscreen()]

            draw_background(screen)
            for pipe in pipes:
                pipe.draw(screen)
            bird.draw(screen)
            draw_hud(screen, font, big_font, score, emg.state, game_over)

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
