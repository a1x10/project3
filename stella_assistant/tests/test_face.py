import pygame
import pytest

from stella.config import Config
from stella.face.emotions import EMOTIONS, PRESETS, preset, resolve
from stella.face.face import Face
from stella.face.renderer import AnimState, FaceRenderer


@pytest.fixture(scope="module", autouse=True)
def pg():
    pygame.display.init()
    pygame.font.init()
    yield
    pygame.quit()


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_emotion_renders(name):
    r = FaceRenderer((800, 480), supersample=1)
    surf = pygame.Surface((800, 480))
    p = preset(name)
    st = AnimState(t=1.0, gaze=(p.gaze_x, p.gaze_y), speech=0.5, mic=0.5)
    eyes = r.eye_positions(p, st)
    for _ in range(20):
        r.update(0.05, p, eyes)
    r.render(surf, p, st)
    # открытые глаза — много светлых пикселей; у спящей — только линии век и бровей
    lit = sum(1 for x in range(0, 800, 4) for y in range(0, 480, 4) if max(surf.get_at((x, y))[:3]) > 120)
    bright = sum(1 for x in range(0, 800, 8) for y in range(0, 480, 8) if surf.get_at((x, y)).r > 200)
    if name == "sleep":
        assert lit > 20 and bright < 10
    else:
        assert bright > 50


def test_resolve_russian_names():
    assert resolve("радость") == "joy"
    assert resolve("злость") == "anger"
    assert resolve("скуку") == "boredom"
    assert resolve("симпатию") == "love"
    assert resolve("что-то непонятное") == "neutral"
    assert set(EMOTIONS) <= set(PRESETS)


def test_lerp_and_intensity():
    half = preset("anger", 0.5)
    full = preset("anger")
    neutral = preset("neutral")
    assert neutral.brow_angle > half.brow_angle > full.brow_angle
    assert half.tint[0] > neutral.tint[0] - 1


def test_face_controller_transitions():
    cfg = Config()
    face = Face(cfg, headless=True)
    face.set_emotion("fear", 1.0, hold=5)
    for _ in range(60):
        face.update(1 / 30)
    assert face.params.eye_h > 1.1          # глаза широко раскрыты
    face.set_state("sleep")
    for _ in range(90):
        face.update(1 / 30)
    assert face.params.closed > 0.9         # спит — глаза закрыты
