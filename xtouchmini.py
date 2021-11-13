# Remote control of Canon EOS cameras for live video streaming
#
# Copyright (C) 2021 Jan Kundrát <jkt@jankundrat.com>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import mido


# I want the highest possible resolution of the LED rings while also changing the indication upon every click.
# The LED ring has 13 LEDs, i.e., one in the central position and six each to the left and to the right.
# The HW can show "in-between" positions by switching on two adjacent LEDs at a time. Unfortunately, the controller
# does not really map these values uniformly; when activating 25 states, no state corresponds to "just the central LED",
# etc. For example, when configured for the range of 1 to 25, the leftmost LED is active for two lowest states, and
# there's no state for the two rightmost LEDs (and no state maps to just-the-central-LED, either). TL;DR: this sucks.
#
# I'm trying to solve this by remapping all rotary encoders to a relative mode, and with an explicit control of
# the LEDs. There are two ways of controling these, the first is via setting the CC to a desired value, which then
# goes via HW's mapping from values to LED positions, which supports two-at-a-time indication. To add an explicit
# "out of range" state at the very ends of the spectrum, we can switch to an explicit LED control which supports
# blinking of individual LEDs (but just one LED at a time).
#
# Regular LED mapping:
# LED1: 0..5
# LED1+2: 6..10
# LED2: 11..15
# LED2+3: 16..21
# LED3: 22..26
# LED3+4: 27..31
# LED4: 32..37
# LED4+5: 38..42
# LED5: 43..47
# LED5+6: 48..53
# LED6: 54..58
# LED6+7: 59..63
# LED7: 64
# LED7+8: 65..69
# LED8: 70..75
# LED8+9: 76..81
# LED9: 82..86
# LED9+10: 87..92
# LED10: 93..98
# LED10+11: 99..104
# LED11: 105..109
# LED11+12: 110.115
# LED12: 116..121
# LED12+13: 122..126
# LED13: 127

LED_STEPS = (-1, 0, 6, 11, 16, 22, 27, 32, 38, 43, 48, 54, 59, 64, 65, 70, 76, 82, 87, 93, 99, 105, 110, 116, 122, 127, 128)

VALUE_MID = 64

ENCODER_TO_FUNCTION = {
    'focus': 0,
    'exposurecompensation': 1,
    'aperture': 2,
    'shutterspeed': 3,
    'iso': 4,
    'colortemperature': 5,
    'whitebalanceadjusta': 6,
    'whitebalanceadjustb': 7,
}


def results_for_function(function):
    if function == 'exposurecompensation':
        return ['-3', '-2.6', '-2.3', '-2', '-1.6', '-1.3', '-1', '-0.6', '-0.3', '0', '0.3', '0.6', '1', '1.3', '1.6', '2', '2.3', '2.6', '3']
    if function == 'aperture':
        return ['1', '1.2', '1.4', '1.6', '1.8', '2', '2.2', '2.5', '2.8', '3.2', '3.5', '4', '4.5', '5', '5.6', '6.3', '7.1', '8', '9', '10', '11', '13', '14', '16', '18', '20', '22']
    if function == 'shutterspeed':
        return [
            # I want to have 1/50s at the neutral position, hence there's no place for these: '1/3200', '1/2500', '1/2000', '1/1600', '1/1250',
            '1/1000', '1/800', '1/640', '1/500', '1/400', '1/320', '1/250', '1/200', '1/160', '1/125', '1/100', '1/80', '1/60', '1/50', '1/40', '1/30', '1/25', '1/20', '1/15', '1/13', '1/10', '1/8', '1/6']
    if function == 'colortemperature':
        # bigger range, needs disabling custom stepping elsewhere
        return [str(x) for x in range(2500, 10001, 100)]
    if function in ('whitebalanceadjusta', 'whitebalanceadjustb'):
        return [str(x) for x in range(-9, 10)]
    if function == 'iso':
        return ['Auto'] + [str(x) for x in (100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6400, 8000, 10000, 12800, 16000, 20000, 25600)]
    return None


def function_for_encoder(encoder):
    candidates = [k for k, v in ENCODER_TO_FUNCTION.items() if v == encoder]
    return candidates[0] if len(candidates) else None


class XTouchMini:
    def __init__(self, name, on_change):
        self.m_in = mido.open_input(name, callback=lambda x: self.on_midi(x))
        self.m_out = mido.open_output(name)

        # standard mode (A/B layers)
        self.m_out.send(mido.Message('control_change', channel=1, control=127, value=1))
        self.faders = [VALUE_MID] * 8

        for control in range(0, 8):
            # FIXME: explicitly switch to "relative 1" mode for all rotary encoders if possible.
            # FIXME: currently needs an explicit X-Touch Mini profile.
            if function_for_encoder(control) is None:
                self.leds_special(control, 'off')
            elif function_for_encoder(control) == 'focus':
                self.leds_special(control, 'off')
            else:
                # Switch LEDs to the "pan" mode. This is redundant because it's already set up via the X-Touch Mini edit app.
                self.m_out.send(mido.Message('control_change', channel=0, control=control + 1, value=1))
                # start in the central position
                self.m_out.send(mido.Message('control_change', channel=10, control=control + 1, value=self.faders[control]))

        self.on_change = on_change
        self.results = [results_for_function(function_for_encoder(encoder)) for encoder in range(0, 8)]

    def range_for(self, encoder):
        if encoder == ENCODER_TO_FUNCTION['exposurecompensation']:
            return LED_STEPS[4:-4]
        if encoder in (ENCODER_TO_FUNCTION['whitebalanceadjusta'], ENCODER_TO_FUNCTION['whitebalanceadjustb']):
            return LED_STEPS[4:-4]
        if encoder == ENCODER_TO_FUNCTION['shutterspeed']:
            return LED_STEPS[0:-5]
        if encoder == ENCODER_TO_FUNCTION['colortemperature']:
            return [int(x * 127 / 76.0) for x in range(0, 76)]
        return LED_STEPS

    def leds_special(self, encoder, what):
        control = encoder + 1 + 8
        if what == 'blink-left':
            value = 14
        elif what == 'blink-right':
            value = 26
        elif what == 'off':
            value = 0
        elif what == 'all-on':
            value = 27
        elif what == 'blink-all':
            value = 28
        elif what == 'blink-center':
            value = 20
        else:
            raise Exception(f'Unknown LED encoder operation {what}')
        self.m_out.send(mido.Message('control_change', channel=0, control=control, value=value))

    def do_next_value_for(self, encoder, delta):
        allowed = self.range_for(encoder)
        try:
            if delta > 0:
                candidates = [x for x in allowed if x > self.faders[encoder]]
                # val = candidates[3 if len(candidates) > 3 and delta > 2 else 0]
                val = candidates[0]
            else:
                candidates = [x for x in allowed if x < self.faders[encoder]]
                # val = candidates[-4 if len(candidates) > 3 and delta < -2 else -1]
                val = candidates[-1]
        except IndexError:
            val = allowed[0 if delta < 0 else -1]

        # print(f'{self.faders[encoder]} -> {val}')
        self.do_set_value(encoder, val)

    def do_set_value(self, encoder, val):
        self.faders[encoder] = val
        if val == -1:
            self.leds_special(encoder, 'blink-left')
        elif val == 128:
            self.leds_special(encoder, 'blink-right')
        else:
            self.m_out.send(mido.Message('control_change', channel=10, control=encoder + 1, value=val))

    def on_midi(self, message):
        if message.type == 'control_change':
            if message.control == 9:
                # main fader, ignore this
                return
            if message.channel != 10 or message.control > 8:
                # not encoders, ignore this
                return
            # all encoders are in relative mode, i.e.:
            # 1 = gentle to the right, 7 = hard to the right
            # 127 = gentle to the left, 121 = hard to the left
            delta = message.value - 128 if message.value > 120 else message.value
            encoder = message.control - 1

            if function_for_encoder(encoder) is None:
                self.leds_special(encoder, 'off')
                return

            self.do_next_value_for(encoder, delta)

            if encoder in ENCODER_TO_FUNCTION.values():
                idx = self.range_for(encoder).index(self.faders[encoder])
                key = function_for_encoder(encoder)
                if key == 'focus':
                    self.faders[encoder] = VALUE_MID
                    self.m_out.send(mido.Message('control_change', channel=message.channel, control=message.control, value=self.faders[encoder]))
                    self.leds_special(encoder, 'blink-center')
                    if delta > 0:
                        if delta < 2:
                            value = 'Far 1'
                        elif delta < 4:
                            value = 'Far 2'
                        else:
                            value = 'Far 3'
                    else:
                        if delta > -2:
                            value = 'Near 1'
                        elif delta > -4:
                            value = 'Near 2'
                        else:
                            value = 'Near 3'
                    self.on_change('movieservoaf', 'Off')
                    self.on_change('manualfocusdrive', value)
                else:
                    self.on_change(key, self.results[encoder][idx])

        elif message.type in ('note_on', 'note_off',):
            # note_on: button down, note_off: button up
            # encoders: note 0..7, buttons first row: note 8..15, buttons second row: 16..23
            if message.note >= 0 and message.note <= 7 and message.type == 'note_on':
                function = function_for_encoder(message.note)
                if function == 'colortemperature':
                    self.leds_special(message.note, 'all-on')
                    self.on_change('whitebalance', 'Auto')
                if function in ('whitebalanceadjusta', 'whitebalanceadjustb'):
                    # reset to the middle
                    # update the MIDI controller's idea
                    self.faders[message.note] = VALUE_MID
                    self.m_out.send(mido.Message('control_change', channel=10, control=message.note + 1,
                                                 value=self.faders[message.note]))
                    idx = self.range_for(message.note).index(self.faders[message.note])
                    self.on_change(function, self.results[message.note][idx])
                if function == 'focus':
                    self.on_change('movieservoaf', 'On')
                    self.leds_special(message.note, 'all-on')
        else:
            print(f'!!! unhandled MIDI in: {message}')

