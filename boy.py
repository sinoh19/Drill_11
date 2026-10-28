from pico2d import (
    load_image, get_canvas_width,
    SDL_KEYDOWN, SDL_KEYUP, SDLK_LEFT, SDLK_RIGHT, SDLK_a, SDLK_LSHIFT,
    SDLK_RSHIFT,
)
from time import monotonic
from math import pi
from transitions import Machine, State


IDLE_FRAMES = 8
IDLE_FPS = 8
RUN_FRAMES = 8
RUN_FPS = 12
RUN_SPEED = 200  # Pixels per second.
REST_DELAY = 5.0  # Seconds without keyboard input while IDLE.
AUTO_RUN_DURATION = 5.0
AUTO_RUN_MAX_SCALE = 2.0
DASH_SPEED = 800  # Pixels per second: 120 pixels per dash.
DASH_DURATION = 0.15
DASH_COOLDOWN = 0.5  # Measured from the start of a dash.


class AutoRun(State):
    def __init__(self):
        super().__init__('AUTO_RUN', on_enter='enter_auto_run')


class Boy:
    def __init__(self):
        self.x, self.y = 400, 90
        self.frame = 0
        self.face_dir = 1
        self.image = load_image('animation_sheet.png')
        self.last_update = monotonic()
        self.idle_since = self.last_update
        self.held_keys = []  # The last pressed key takes priority.
        self.held_shift_keys = set()
        self.dash_remaining = 0.0
        self.dash_ready_at = 0.0

        self.state_machine = Machine(
            model=self,
            states=[
                {'name': 'IDLE', 'on_enter': 'enter_idle'},
                {'name': 'RUN_LEFT', 'on_enter': 'enter_run_left'},
                {'name': 'RUN_RIGHT', 'on_enter': 'enter_run_right'},
                {'name': 'REST', 'on_enter': 'enter_rest'},
                {'name': 'DASH', 'on_enter': 'enter_dash'},
                AutoRun(),
            ],
            initial='IDLE',
            auto_transitions=False,
        )
        # Internal transition: animate without leaving or re-entering IDLE.
        self.state_machine.add_transition(
            trigger='tick', source='IDLE', dest=None, after='update_idle'
        )
        self.state_machine.add_transition(
            trigger='tick', source=['RUN_LEFT', 'RUN_RIGHT'],
            dest=None, after='update_run'
        )
        self.state_machine.add_transition(
            trigger='tick', source='AUTO_RUN', dest=None,
            after='update_auto_run'
        )
        self.state_machine.add_transition('run_left', '*', 'RUN_LEFT')
        self.state_machine.add_transition('run_right', '*', 'RUN_RIGHT')
        self.state_machine.add_transition('auto_run', '*', 'AUTO_RUN')
        self.state_machine.add_transition('stop', '*', 'IDLE')
        self.state_machine.add_transition('sleep', 'IDLE', 'REST')
        self.state_machine.add_transition('wake', 'REST', 'IDLE')
        self.state_machine.add_transition('tick', 'REST', None)
        self.state_machine.add_transition(
            'dash', ['RUN_LEFT', 'RUN_RIGHT'], 'DASH', conditions='can_dash'
        )
        self.state_machine.add_transition('tick', 'DASH', None, after='update_dash')
        self.state_machine.add_transition(
            'finish_dash', 'DASH', 'IDLE', after='sync_movement'
        )

    def handle_event(self, event):
        if event.type not in (SDL_KEYDOWN, SDL_KEYUP):
            return
        if self.state == 'REST':
            if event.type != SDL_KEYDOWN:
                return
            self.wake()
        if self.state == 'IDLE':
            self.idle_since = monotonic()
        if event.type == SDL_KEYDOWN and event.key == SDLK_a:
            if self.state != 'AUTO_RUN':
                self.auto_run()
            return
        if event.key in (SDLK_LSHIFT, SDLK_RSHIFT):
            if event.type == SDL_KEYUP:
                self.held_shift_keys.discard(event.key)
            elif event.key not in self.held_shift_keys:
                self.held_shift_keys.add(event.key)
                if self.state in ('RUN_LEFT', 'RUN_RIGHT'):
                    self.dash()
            return
        if event.key not in (SDLK_LEFT, SDLK_RIGHT):
            return

        if event.type == SDL_KEYDOWN:
            # Ignore repeated keydown events while a key is held.
            if event.key in self.held_keys:
                if self.state == 'AUTO_RUN':
                    self.sync_movement()
                return
            self.held_keys.append(event.key)
        elif event.key in self.held_keys:
            self.held_keys.remove(event.key)

        # Remember inputs during a dash, but finish in the original direction.
        if self.state != 'DASH':
            self.sync_movement()

    def sync_movement(self):
        if not self.held_keys:
            if self.state != 'IDLE':
                self.stop()
        elif self.held_keys[-1] == SDLK_LEFT:
            if self.state != 'RUN_LEFT':
                self.run_left()
        elif self.state != 'RUN_RIGHT':
            self.run_right()

    def enter_idle(self):
        self.frame = 0
        self.idle_since = monotonic()

    def enter_rest(self):
        self.frame = 0

    def can_dash(self):
        return monotonic() >= self.dash_ready_at

    def enter_dash(self):
        self.frame = 0
        self.dash_remaining = DASH_DURATION
        self.dash_ready_at = monotonic() + DASH_COOLDOWN

    def enter_run_left(self):
        self.frame = 0
        self.face_dir = -1

    def enter_run_right(self):
        self.frame = 0
        self.face_dir = 1

    def enter_auto_run(self):
        self.frame = 0
        self.auto_run_started_at = monotonic()

    def update(self):
        now = monotonic()
        delta_time = now - self.last_update
        self.last_update = now
        self.tick(delta_time)

    def update_idle(self, delta_time):
        self.frame = (self.frame + IDLE_FPS * delta_time) % IDLE_FRAMES
        if monotonic() - self.idle_since >= REST_DELAY:
            self.sleep()

    def update_run(self, delta_time):
        self.frame = (self.frame + RUN_FPS * delta_time) % RUN_FRAMES
        self.x += self.face_dir * RUN_SPEED * delta_time
        self.x = max(25, min(get_canvas_width() - 25, self.x))

    def update_auto_run(self, delta_time):
        elapsed = monotonic() - self.auto_run_started_at
        if elapsed >= AUTO_RUN_DURATION:
            self.stop()
            return

        speed = RUN_SPEED + (DASH_SPEED - RUN_SPEED) * (
            elapsed / AUTO_RUN_DURATION
        )
        self.frame = (self.frame + RUN_FPS * delta_time) % RUN_FRAMES
        self.x += self.face_dir * speed * delta_time
        right_edge = get_canvas_width() - 25
        if self.x <= 25:
            self.x = 25
            self.face_dir = 1
        elif self.x >= right_edge:
            self.x = right_edge
            self.face_dir = -1

    def update_dash(self, delta_time):
        # Limit travel even if a frame takes longer than the entire dash.
        dash_time = min(delta_time, self.dash_remaining)
        self.frame = (self.frame + RUN_FPS * 2 * dash_time) % RUN_FRAMES
        self.x += self.face_dir * DASH_SPEED * dash_time
        self.x = max(25, min(get_canvas_width() - 25, self.x))
        self.dash_remaining = max(0.0, self.dash_remaining - dash_time)
        if self.dash_remaining == 0.0:
            self.finish_dash()

    def draw(self):
        if self.state == 'IDLE':
            self.draw_idle()
        elif self.state == 'REST':
            self.draw_rest()
        elif self.state == 'DASH':
            self.draw_dash()
        elif self.state == 'AUTO_RUN':
            self.draw_auto_run()
        else:
            self.draw_run()

    def draw_auto_run(self):
        elapsed = monotonic() - self.auto_run_started_at
        scale = 1.0 + (AUTO_RUN_MAX_SCALE - 1.0) * min(
            elapsed / AUTO_RUN_DURATION, 1.0
        )
        row = 100 if self.face_dir == 1 else 0
        size = 100 * scale
        self.image.clip_draw(
            int(self.frame) * 100, row, 100, 100,
            self.x, self.y + (size - 100) / 2, size, size
        )

    def draw_dash(self):
        row = 100 if self.face_dir == 1 else 0
        # Lean forward with a lower, wider running pose for the burst.
        self.image.clip_composite_draw(
            int(self.frame) * 100, row, 100, 100,
            -self.face_dir * pi / 12, '', self.x, self.y - 5, 110, 90
        )

    def draw_rest(self):
        # Rotate the idle sprite onto its back and lower it to the grass.
        row = 300 if self.face_dir == 1 else 200
        angle = self.face_dir * pi / 2
        self.image.clip_composite_draw(
            0, row, 100, 100, angle, '', self.x, self.y - 30, 100, 100
        )

    def draw_run(self):
        # Running rows: left at y=0, right at y=100.
        row = 100 if self.face_dir == 1 else 0
        self.image.clip_draw(int(self.frame) * 100, row, 100, 100, self.x, self.y)

    def draw_idle(self):
        frame = int(self.frame)
        if self.face_dir == 1:
            self.image.clip_draw(frame * 100, 300, 100, 100, self.x, self.y)
        else:
            self.image.clip_draw(frame * 100, 200, 100, 100, self.x, self.y)
