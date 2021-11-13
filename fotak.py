# Remote control of Canon EOS cameras for live video streaming
#
# Copyright (C) 2021 Jan Kundrát <jkt@jankundrat.com>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import gphoto2 as gp
import mido
import queue
from xtouchmini import XTouchMini, ENCODER_TO_FUNCTION


class Camera:
    def __init__(self, event_handler):
        self.cam = gp.Camera()
        self.cam.init()
        cfg = self.cam.get_config()
        viewfinder = cfg.get_child_by_name('viewfinder')
        viewfinder.set_value(1)
        self.cam.set_single_config('viewfinder', viewfinder)
        self.old_status = None
        self.event_handler = event_handler
        self.queue = queue.Queue()

    def on_config_changed(self):
        cfg = self.cam.get_config()
        aperture = cfg.get_child_by_name('aperture')
        shutterspeed = cfg.get_child_by_name('shutterspeed')
        exposure_compensation = cfg.get_child_by_name('exposurecompensation')
        iso = cfg.get_child_by_name('iso')
        wb = cfg.get_child_by_name('whitebalance')
        wb_temperature = cfg.get_child_by_name('colortemperature')
        wb_shift_a = cfg.get_child_by_name('whitebalanceadjusta')
        wb_shift_b = cfg.get_child_by_name('whitebalanceadjustb')
        if wb.get_value() == 'Color Temperature':
            wb_info = f'{wb_temperature.get_value()}K'
        else:
            wb_info = wb.get_value()
        if wb_shift_a.get_value() != '0':
            shift = int(wb_shift_a.get_value())
            if shift > 0:
                wb_info += f' A{shift}'
            else:
                wb_info += f' B{-shift}'
        if wb_shift_b.get_value() != '0':
            shift = int(wb_shift_b.get_value())
            if shift > 0:
                wb_info += f' G{shift}'
            else:
                wb_info += f' M{-shift}'
        status = f'F/{aperture.get_value()} {shutterspeed.get_value()}s {exposure_compensation.get_value()} EV ISO {iso.get_value()} WB {wb_info}'
        if self.old_status != status:
            print(status)
            self.old_status = status
            self.event_handler()

    def apply_command(self, what, value):
        if what in ('exposurecompensation', 'aperture', 'iso', 'shutterspeed',
                    'whitebalance', 'colortemperature', 'whitebalanceadjusta', 'whitebalanceadjustb',
                    'manualfocusdrive', 'movieservoaf'):
            cfg = self.cam.get_config()
            try:
                w = cfg.get_child_by_name(what)
            except gp.GPhoto2Error:
                print(f'Unsupported by camera: {what}')
                if what == 'movieservoaf':
                    self.event_handler()
                return

            if w.get_type() == gp.GP_WIDGET_RADIO or w.get_type() == gp.GP_WIDGET_MENU:
                if value not in w.get_choices():
                    possibilities = ', '.join(w.get_choices())
                    print(f'!!! Cannot set {what} to {value}. Allowed values: {possibilities}')
                    self.event_handler()
                    return
            if w.get_value() == value:
                return
            w.set_value(value)
            print(f' set {what} = {value}')
            self.cam.set_single_config(what, w)
            if what == 'colortemperature':
                self.apply_command('whitebalance', 'Color Temperature')

    def run(self):
        while True:
            event_type, event_data = self.cam.wait_for_event(10)
            if event_type == gp.GP_EVENT_UNKNOWN:
                self.on_config_changed()
            elif event_type == gp.GP_EVENT_TIMEOUT:
                pass
            else:
                print(f'unhandled gphoto2 thingy {event_type}')

            try:
                what, value = self.queue.get(block=False)
            except queue.Empty:
                continue
            self.apply_command(what, value)


class Handler:
    def __init__(self):
        self.midi = None
        self.camera = Camera(event_handler=lambda **kwargs: self.on_camera_change(**kwargs))
        self.midi = XTouchMini('X-TOUCH MINI MIDI 1', on_change=lambda what, value: self.on_midi_change(what, value))
        # self.midi = XTouchMini('X-TOUCH MINI:X-TOUCH MINI MIDI 1 40:0', on_change=lambda what, value: self.on_midi_change(what, value))
        self.old = None

    def on_camera_change(self):
        if self.midi is None:
            return

        cfg = self.camera.cam.get_config()
        for key, encoder in ENCODER_TO_FUNCTION.items():
            if key == 'focus':
                # magic
                try:
                    if cfg.get_child_by_name('movieservoaf').get_value() == 'On':
                        self.midi.leds_special(encoder, 'all-on')
                    else:
                        self.midi.leds_special(encoder, 'blink-center')
                except gp.GPhoto2Error:
                    self.midi.leds_special(encoder, 'blink-center')
                continue

            w = cfg.get_child_by_name(key)
            val = w.get_value()
            allowed = self.midi.results[encoder]
            try:
                idx = allowed.index(val)
            except ValueError:
                idx = None
            if idx is not None:
                midi_val = self.midi.range_for(encoder)[idx]
                if self.midi.faders[encoder] != midi_val:
                    print(f' midi: encoder {encoder} -> #{allowed.index(val)} (out of {len(allowed)})')
                    self.midi.do_set_value(encoder, midi_val)
            else:
                print(f' midi: encoder {encoder}: no match for value {val}')
                self.midi.leds_special(encoder, 'blink-all')

            if key == 'colortemperature':
                wb = cfg.get_child_by_name('whitebalance').get_value()
                if wb == 'Color Temperature':
                    pass
                elif wb == 'Auto':
                    print(f' midi: encoder {encoder}: all-on for AWB')
                    self.midi.leds_special(encoder, 'all-on')
                else:
                    print(f' midi: encoder {encoder}: WB neither AWB nor K')
                    self.midi.leds_special(encoder, 'blink-all')

    def on_midi_change(self, what, value):
        self.camera.queue.put([what, value])

    def run(self):
        self.camera.run()


x = Handler()
x.run()
