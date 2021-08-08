# Remote control of Canon EOS cameras for live video streaming
#
# Copyright (C) 2021 Jan Kundrát <jkt@jankundrat.com>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import mido


# Assumes the XctlHUI mode on X-Touch
class XTouch:
    KEYS = {
        0x0c: {
            5: 'hui',
        },
        0x0d: {
            0: 'down',
            1: 'left',
            2: 'zoom',
            3: 'right',
            4: 'up',
            5: 'scrub',
            6: 'solo',
        },
        0x0e: {
            1: 'previous',
            2: 'next',
            3: 'stop',
            4: 'play',
            5: 'rec',
        },
        0x0f: {
            2: 'click',
            3: 'cycle',
            4: 'marker',
        },
        0x10: {
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
        self.m_out = mido.open_output(name)
        # self.m_out.send(mido.Message.from_bytes([0xb0, 0x0c, 0x0d]))
        # self.m_out.send(mido.Message.from_bytes([0xb0, 0x2c, 0x45]))
        # self.m_out.send(mido.Message.from_bytes([0xf0, 0x00, 0x00, 0x66, 0x05, 0x00, 0x11, 0x1f, 0x0e, 0x1d, 0x0c, 0x1b, 0x0a, 0x19, 0x08, 0x17, 0xf7]))

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
            if message.channel != 0x00:
                raise Exception(f'X-Touch sent unrecognized {message}')
            if message.control == 0x0f:
                if self.previous_value is not None:
                    raise Exception(f'X-Touch: {self.previous_value=} and just got {message=}')
                self.previous_value = message.value
                if message.value not in self.KEYS.keys():
                    raise Exception(f'X-Touch: {message=} not recopgnized for a first event')
                return None

            if message.control == 0x0d:
                if message.value > 0x40:
                    return ('wheel', message.value - 0x40)
                else:
                    return ('wheel', -message.value)
            elif message.control == 0x2f:
                if self.previous_value is None:
                    raise Exception(f'X-Touch: got {message=} with no previous message recorded')
                candidates = self.KEYS[self.previous_value]
                key = candidates.get(message.value, None)
                pressed = False
                if key is None:
                    key = candidates.get(message.value - 0x40, None)
                    pressed = True
                if key is None:
                    raise Exception(f'X-Touch: got unrecognized {message=} with {self.previous_value=}')
                # self.m_out.send(mido.Message.from_bytes([0xb0, 0x0c, self.previous_value]))
                # self.m_out.send(mido.Message.from_bytes([0xb0, 0x2c, message.value]))
                self.previous_value = None
                return (key, pressed)
            else:
                raise Exception('X-Touch: unhandled: {message}')
        else:
            raise Exception(f'X-Touch unhandled: {message}')

    def _find_by_name(self, what):
        for zone, x in self.KEYS.items():
            for port, name in x.items():
                if name == what:
                    return (zone, port)
        return None

    def control_led(self, button, on):
        x = self._find_by_name(button)
        if x is None:
            raise Exception(f'X-Touch: dunno how to control LED {button}')
        (zone, port) = x
        self.m_out.send(mido.Message.from_bytes([0xb0, 0x0c, zone]))
        self.m_out.send(mido.Message.from_bytes([0xb0, 0x2c, port + (0x40 if on else 0x0)]))

if __name__ == '__main__':
    class Handler:
        def __init__(self):
            self.midi = XTouch('X-Touch X-TOUCH_INT',
                               on_wheel=lambda diff: print(f'wheel {diff}'),
                               on_button=lambda what, pressed: print(f'{what} {"pressed" if pressed else "released"}'),
                               )

    x = Handler()
    import time
    for i in range(100):
        x.midi.control_led('rec', True)
        time.sleep(0.3)
        x.midi.control_led('rec', False)
        time.sleep(0.3)
    time.sleep(666)
