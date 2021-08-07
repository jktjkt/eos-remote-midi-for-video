# Remote control of Canon EOS cameras for live video streaming
#
# Copyright (C) 2021 Jan Kundrát <jkt@jankundrat.com>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import mido


# Assumes the XctlHUI mode on X-Touch
class XTouch:
    KEYS = {
        13: {
            0: 'down',
            1: 'left',
            2: 'zoom',
            3: 'right',
            4: 'up',
            5: 'scrub',
            6: 'solo',
        },
        14: {
            1: 'previous',
            2: 'next',
            3: 'stop',
            4: 'play',
            5: 'rec',
        },
        15: {
            4: 'marker',
            3: 'cycle',
            2: 'click',
        },
        16: {
            0: 'nudge',
            2: 'drop',
            3: 'replace',
        },
    }

    def __init__(self, name, on_wheel, on_button):
        self.on_wheel = on_wheel
        self.on_button = on_button
        self.previous_value = None
        self.m_in = mido.open_input(name, callback=lambda x: self.on_midi(x))
        # FIXME: figure out how to handle LEDs in these buttons...

    def on_midi(self, message):
        res = self.parse_midi(message)
        if res is None:
            return
        what, action = res
        if what == 'wheel':
            self.on_wheel(action)
        else:
            self.on_button(what, action)

    def parse_midi(self, message):
        if message.type == 'control_change':
            if message.channel != 0:
                raise Exception(f'X-Touch sent unrecognized {message}')
            if message.control == 15:
                if self.previous_value is not None:
                    raise Exception(f'X-Touch: {self.previous_value=} and just got {message=}')
                self.previous_value = message.value
                if message.value not in self.KEYS.keys():
                    raise Exception(f'X-Touch: {message=} not recopgnized for a first event')
                return None

            if message.control == 13:
                if message.value > 64:
                    return ('wheel', message.value - 64)
                else:
                    return ('wheel', -message.value)
            elif message.control == 47:
                if self.previous_value is None:
                    raise Exception(f'X-Touch: got {message=} with no previous message recorded')
                candidates = self.KEYS[self.previous_value]
                key = candidates.get(message.value, None)
                pressed = False
                if key is None:
                    key = candidates.get(message.value - 64, None)
                    pressed = True
                if key is None:
                    raise Exception(f'X-Touch: got unrecognized {message=} with {self.previous_value=}')
                self.previous_value = None
                return (key, pressed)
            else:
                raise Exception('X-Touch: unhandled: {message}')
        else:
            raise Exception(f'X-Touch unhandled: {message}')


class Handler:
    def __init__(self):
        self.midi = XTouch('X-Touch X-TOUCH_INT',
                           on_wheel=lambda diff: print(f'wheel {diff}'),
                           on_button=lambda what, pressed: print(f'{what} {"pressed" if pressed else "released"}'),
                           )


x = Handler()
import time
time.sleep(666)
