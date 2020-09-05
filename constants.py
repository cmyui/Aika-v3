# -*- coding: utf-8 -*-

from typing import Final
from enum import IntEnum
import re

regexes = {
    'beatmap_url': re.compile(r'(?:https?://)?(?:www.)?akatsuki.pw/b/(?P<bid>\d{1,7})/?'),
    'song_name': re.compile(r'(?P<artist>.+) - (?P<sn>.+)\[(?P<diff>.+)\]'),
    'cmd_prefix': re.compile(r'^[\x21-\x3F\x41-\x7E]{1,8}$'),
    'mention': re.compile(r'<@!?(?P<id>\d{18,20})>'),
    'duration': re.compile(r'^(?P<duration>[1-9]\d*)(?P<period>s|m|h|d|w)?$')
}

class Ansi(IntEnum):
    # Default colours
    BLACK:   Final[int] = 30
    RED:     Final[int] = 31
    GREEN:   Final[int] = 32
    YELLOW:  Final[int] = 33
    BLUE:    Final[int] = 34
    MAGENTA: Final[int] = 35
    CYAN:    Final[int] = 36
    WHITE:   Final[int] = 37

    # Light colours
    GRAY:          Final[int] = 90
    LIGHT_RED:     Final[int] = 91
    LIGHT_GREEN:   Final[int] = 92
    LIGHT_YELLOW:  Final[int] = 93
    LIGHT_BLUE:    Final[int] = 94
    LIGHT_MAGENTA: Final[int] = 95
    LIGHT_CYAN:    Final[int] = 96
    LIGHT_WHITE:   Final[int] = 97

    RESET: Final[int] = 0

    def __repr__(self) -> str:
        return f'\x1b[{self.value}m'

class Mods(IntEnum):
    NOMOD:       Final[int] = 0
    NOFAIL:      Final[int] = 1 << 0
    EASY:        Final[int] = 1 << 1
    TOUCHSCREEN: Final[int] = 1 << 2
    HIDDEN:      Final[int] = 1 << 3
    HARDROCK:    Final[int] = 1 << 4
    SUDDENDEATH: Final[int] = 1 << 5
    DOUBLETIME:  Final[int] = 1 << 6
    RELAX:       Final[int] = 1 << 7
    HALFTIME:    Final[int] = 1 << 8
    NIGHTCORE:   Final[int] = 1 << 9
    FLASHLIGHT:  Final[int] = 1 << 10
    AUTOPLAY:    Final[int] = 1 << 11
    SPUNOUT:     Final[int] = 1 << 12
    RELAX2:      Final[int] = 1 << 13
    PERFECT:     Final[int] = 1 << 14
    KEY4:        Final[int] = 1 << 15
    KEY5:        Final[int] = 1 << 16
    KEY6:        Final[int] = 1 << 17
    KEY7:        Final[int] = 1 << 18
    KEY8:        Final[int] = 1 << 19
    KEYMOD:      Final[int] = 1 << 20
    FADEIN:      Final[int] = 1 << 21
    RANDOM:      Final[int] = 1 << 22
    LASTMOD:     Final[int] = 1 << 23
    KEY9:        Final[int] = 1 << 24
    KEY10:       Final[int] = 1 << 25
    KEY1:        Final[int] = 1 << 26
    KEY3:        Final[int] = 1 << 27
    KEY2:        Final[int] = 1 << 28
    SCOREV2:     Final[int] = 1 << 29

    SPEED_CHANGING: Final[int] = DOUBLETIME | NIGHTCORE | HALFTIME
