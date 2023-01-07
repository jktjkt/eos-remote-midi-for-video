import asyncio
import asyncio_mqtt as am
from contextlib import AsyncExitStack
import json
import os
import sys
import threading

from PySide2.QtCore import Qt, QCoreApplication, QEvent, QObject, Signal, Slot, Property, QTimer, QThread
from PySide2.QtGui import QGuiApplication
from PySide2.QtQml import QQmlApplicationEngine, QQmlContext

import xtouch
import xtouchmini


class InvokeEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, fn, *args, **kwargs):
        QEvent.__init__(self, InvokeEvent.EVENT_TYPE)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs


class Invoker(QObject):
    def event(self, event):
        event.fn(*event.args, **event.kwargs)

        return True


_invoker = Invoker()


def invoke_in_main_thread(fn, *args, **kwargs):
    QCoreApplication.postEvent(_invoker, InvokeEvent(fn, *args, **kwargs))


class CameraManager(QObject):
    def __init__(self, name, switcher_input, do_tally):
        QObject.__init__(self)
        self._camera_name = name
        self._switcher_input = switcher_input
        self._data = {
            'cameramodel': None,
            'lensname': None,
            'autoexposuremode': '<aemode>',
            'autoexposuremodedial': '<dial>',
            'aperture': '<aperture>',
            'shutterspeed': '<shutter>',
            'exposurecompensation': '<exp>',
            'iso': '<iso>',
            'movieservoaf': '<af>',
            'whitebalance': '<wb>',
            'colortemperature': '<color>',
            'whitebalanceadjusta': '-1',
            'whitebalanceadjustb': '0',
        }
        self._allowed = {
            'aperture': [],
            'shutterspeed': [],
            'exposurecompensation': [],
            'iso': [],
            'manualfocusdrive': [],
            'movieservoaf': [],
            'whitebalance': [],
            'colortemperature': [],
            'whitebalanceadjusta': [],
            'whitebalanceadjustb': [],
        }
        self._lock = threading.Lock()
        self._selected_mode = None
        self._last_changed = None
        self._mqtt_send_cam = None
        self._mqtt_send_tally = None
        self._status = None
        self._tally = ''
        self._do_tally = do_tally

        def _expire_last_change():
            self._last_changed = None
            self.last_changed_changed.emit()
        self._last_changed_timeout = QTimer()
        self._last_changed_timeout.timeout.connect(_expire_last_change)
        self._last_changed_timeout.setSingleShot(True)
        self._last_changed_timeout.setInterval(666)
        # self.connect(self, self.last_changed_changed, self._last_changed_timeout, self._last_changed_timeout.start, Qt.QueuedConnection)
        self.last_changed_changed.connect(self._last_changed_timeout.start, Qt.QueuedConnection)

    def read_property(self, name):
        with self._lock:
            return self._data[name]

    def update_data(self, data):
        # safe to call from other threads
        with self._lock:
            for k, v in data.items():
                if self._data[k] == v:
                    continue
                self._data[k] = v
                self._update_last_change(k)
            try:
                print(f'{self._camera_name} {self._data["cameramodel"]} {self._data["lensname"]}')
            except:
                pass
        self.camera_changed.emit()  # FIXME: is it OK to emit like this?

    def store_allowed(self, data):
        # safe to call from other threads
        with self._lock:
            for k, v in data.items():
                self._allowed[k] = v

    camera_changed = Signal()
    tally_changed = Signal()

    cameramodel = Property(str, lambda self: self.read_property('cameramodel'), notify=camera_changed)
    lensname = Property(str, lambda self: self.read_property('lensname'), notify=camera_changed)
    autoexposuremode = Property(str, lambda self: self.read_property('autoexposuremode'), notify=camera_changed)
    autoexposuremodedial = Property(str, lambda self: self.read_property('autoexposuremodedial'), notify=camera_changed)
    aperture = Property(str, lambda self: self.read_property('aperture'), notify=camera_changed)
    shutterspeed = Property(str, lambda self: self.read_property('shutterspeed'), notify=camera_changed)
    exposurecompensation = Property(str, lambda self: self.read_property('exposurecompensation'), notify=camera_changed)
    iso = Property(str, lambda self: self.read_property('iso'), notify=camera_changed)
    movieservoaf = Property(str, lambda self: self.read_property('movieservoaf'), notify=camera_changed)
    whitebalance = Property(str, lambda self: self.read_property('whitebalance'), notify=camera_changed)
    colortemperature = Property(str, lambda self: self.read_property('colortemperature'), notify=camera_changed)
    whitebalanceadjusta = Property(str, lambda self: self.read_property('whitebalanceadjusta'), notify=camera_changed)
    whitebalanceadjustb = Property(str, lambda self: self.read_property('whitebalanceadjustb'), notify=camera_changed)
    status = Property(str, lambda self: self._status, notify=camera_changed)
    tally = Property(str, lambda self: self._tally, notify=tally_changed)
    switcher_input = Property(str, lambda self: self._switcher_input, notify=camera_changed)

    def adjust_relative(self, what, delta):
        if what not in self._allowed:
            raise Exception(f'Cannot control unknown parameter {what}')
        with self._lock:
            current = self._data[what]
            idx = self._allowed[what].index(current)
            if idx + delta >= len(self._allowed[what]):
                print(f'Cannot increase {what} anymore')
                # FIXME: blink something?
                return
            if idx + delta < 0:
                print(f'Cannot decrease {what} anymore')
                # FIXME: blink something?
                return
            new_value = self._allowed[what][idx + delta]
            if new_value == 'Auto':
                print(f'Refusing to set {what} = {new_value} via relative toggle')
                return
            self._send_via_mqtt(what, new_value)

    def adjust_absolute(self, what, value):
        if what not in self._allowed:
            raise Exception(f'Cannot control unknown parameter {what}')
        self._send_via_mqtt(what, value)

    def get_selected_mode(self):
        return self._selected_mode

    def set_selected_mode(self, mode):
        if mode != self._selected_mode:
            self._selected_mode = mode
            self.selected_mode_changed.emit()

    selected_mode_changed = Signal()
    selected_mode = Property(str, get_selected_mode, set_selected_mode, notify=selected_mode_changed)

    @Slot(str, result=bool)
    def handle_key(self, key):
        with self._lock:
            if self._selected_mode not in self._allowed:
                return False

            if self._selected_mode in ('wb',):
                # FIXME
                return False

            if self._selected_mode in ('aperture', 'shutterspeed', 'iso', 'exposurecompensation',):
                delta = 1 if key == 'right' else -1
            else:
                return False
            current = self._data[self._selected_mode]
            try:
                idx = self._allowed[self._selected_mode].index(current)
            except ValueError:
                idx = None
            if delta < 0 and idx == 0:
                print(f'Cannot decrease {self._selected_mode} anymore')
                return True
            if delta > 0 and idx == len(self._allowed[self._selected_mode]) - 1:
                print(f'Cannot increase {self._selected_mode} anymore')
                return True
            new_value = self._allowed[self._selected_mode][idx + delta]
            self._send_via_mqtt(self._selected_mode, new_value)
            return True
        return False

    def _update_last_change(self, what):
        self._last_changed = what
        self.last_changed_changed.emit()

    def _send_via_mqtt(self, key, value):
        if self._mqtt_send_cam is not None:
            print(f'set {key} -> {value}')
            self._mqtt_send_cam(self._camera_name, key, value)
            self._update_last_change(key)

    last_changed_changed = Signal()
    last_changed = Property(str, lambda self: self._last_changed, notify=last_changed_changed)


class FakeCamera(QObject):
    camera_changed = Signal()
    cameramodel = Property(str, lambda self: None, notify=camera_changed)
    lensname = Property(str, lambda self: None, notify=camera_changed)
    autoexposuremode = Property(str, lambda self: None, notify=camera_changed)
    autoexposuremodedial = Property(str, lambda self: None, notify=camera_changed)
    aperture = Property(str, lambda self: None, notify=camera_changed)
    shutterspeed = Property(str, lambda self: None, notify=camera_changed)
    exposurecompensation = Property(str, lambda self: None, notify=camera_changed)
    iso = Property(str, lambda self: None, notify=camera_changed)
    movieservoaf = Property(str, lambda self: None, notify=camera_changed)
    whitebalance = Property(str, lambda self: None, notify=camera_changed)
    colortemperature = Property(str, lambda self: None, notify=camera_changed)
    whitebalanceadjusta = Property(str, lambda self: None, notify=camera_changed)
    whitebalanceadjustb = Property(str, lambda self: None, notify=camera_changed)
    status = Property(str, lambda self: 'No camera selected', notify=camera_changed)
    tally = Property(str, lambda self: 'on-air', notify=camera_changed)
    last_changed = Property(str, lambda self: '', notify=camera_changed)
    switcher_input = Property(str, lambda self: None, notify=camera_changed)

    def adjust_relative(self, what, delta):
        print(f'No camera selected, cannot control {what}')

    def adjust_absolute(self, what, value):
        print(f'No camera selected, cannot control {what}')

    def read_property(self, name):
        return None


async def cancel_tasks(tasks):
    for task in tasks:
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def dump_messages(messages):
    async for message in messages:
        print(f'{message.topic=} {message.payload=}')


async def update_camera_screen(cameras, messages):
    async for message in messages:
        _, camera_name, _ = message.topic.split('/', 2)
        if not camera_name in cameras:
            print(f'No camera handler for {message.topic}')
            continue
        data = json.loads(message.payload)
        cameras[camera_name].update_data(data)


async def update_camera_allowed(cameras, messages):
    async for message in messages:
        _, camera_name, _ = message.topic.split('/', 2)
        if not camera_name in cameras:
            print(f'No camera handler for {message.topic}')
            continue
        data = json.loads(message.payload)
        cameras[camera_name].store_allowed(data)


async def update_camera_status(cameras, messages):
    async for message in messages:
        _, camera_name, _ = message.topic.split('/', 2)
        if not camera_name in cameras:
            print(f'No camera handler for {message.topic}')
            continue
        cameras[camera_name]._status = message.payload.decode('utf-8')
        cameras[camera_name].update_data(dict())


async def update_camera_tally(cameras, messages):
    async for message in messages:
        tally = json.loads(message.payload)['tally']
        for name, cam in cameras.items():
            if cam._switcher_input is not None:
                if cam._switcher_input not in tally.keys():
                    print(f'Wrong input definition for {cam._camera_name}')
                    continue
                if cam._mqtt_send_tally is not None:
                    is_program, is_preview = tally[cam._switcher_input]
                    if is_program:
                        cam._mqtt_send_tally(name, 'tally', '80' if cam._do_tally else '0')
                        cam._mqtt_send_tally(name, 'preview', '50 0 0')
                        cam._tally = 'program'
                    elif is_preview:
                        cam._mqtt_send_tally(name, 'tally', '0')
                        cam._mqtt_send_tally(name, 'preview', '0 20 0')
                        cam._tally = 'preview'
                    else:
                        cam._mqtt_send_tally(name, 'tally', '0')
                        cam._mqtt_send_tally(name, 'preview', '0 0 0')
                        cam._tally = ''
                    cam.tally_changed.emit()  # FIXME: is it OK to emit like this?


class ShouldExit(Exception):
    pass


class MessageBus(QThread):
    def __init__(self, cameras):
        QThread.__init__(self)
        self.cameras = cameras
        self.start_event = threading.Event()
        self.exit_future = None
        self._switch_aux = None

    def request_exit(self):
        # can be only called when self.start_event was waited for
        self.exit_future.set_result(None)

    async def main(self):
        loop = asyncio.get_running_loop()
        self.exit_future = loop.create_future()

        async with AsyncExitStack() as stack:
            tasks = set()
            stack.push_async_callback(cancel_tasks, tasks)
            client = am.Client('localhost')
            await stack.enter_async_context(client)

            # FIXME: all cams

            topic_allowed = 'camera/+/allowed/#'
            camera_metadata_msgs = await stack.enter_async_context(client.filtered_messages(topic_allowed))
            tasks.add(asyncio.create_task(update_camera_allowed(self.cameras, camera_metadata_msgs)))

            topic_settings = 'camera/+/current/#'
            camera_update_msgs = await stack.enter_async_context(client.filtered_messages(topic_settings))
            tasks.add(asyncio.create_task(update_camera_screen(self.cameras, camera_update_msgs)))

            topic_status = 'camera/+/status'
            camera_status_msgs = await stack.enter_async_context(client.filtered_messages(topic_status))
            tasks.add(asyncio.create_task(update_camera_status(self.cameras, camera_status_msgs)))

            topic_atem_tally_source = 'atem/+/tally-source'
            atem_tally_msgs = await stack.enter_async_context(client.filtered_messages(topic_atem_tally_source))
            tasks.add(asyncio.create_task(update_camera_tally(self.cameras, atem_tally_msgs)))

            for topic in (topic_allowed, topic_settings, topic_status, topic_atem_tally_source):
                await client.subscribe(topic)

            async def wait_for_requested_exit():
                await self.exit_future
                raise ShouldExit()

            tasks.add(asyncio.create_task(wait_for_requested_exit()))

            def on_mqtt_send_cam_requested(camera_name, key, value):
                if client is not None:
                    asyncio.run_coroutine_threadsafe(client.publish(f'camera/{camera_name}/set/{key}', value), loop)

            def on_mqtt_send_tally_requested(camera_name, led, value):
                if client is not None:
                    asyncio.run_coroutine_threadsafe(client.publish(f'camera/{camera_name}/{led}', value), loop)

            for camera in self.cameras.values():
                camera._mqtt_send_cam = on_mqtt_send_cam_requested
                camera._mqtt_send_tally = on_mqtt_send_tally_requested

            def on_mqtt_send_aux_out(output):
                if client is not None:
                    data = {'index': 0, 'source': output}
                    asyncio.run_coroutine_threadsafe(client.publish(f'atem/extreme/set/aux-source', json.dumps(data)), loop)

            self._switch_aux = on_mqtt_send_aux_out

            self.start_event.set()

            await client.publish('camera/dump-all', '.')

            try:
                await asyncio.gather(*tasks)
            except ShouldExit:
                pass

    def run(self):
        asyncio.run(self.main())


class MidiHandler:
    MIDI_CONTROL_FANCY = 1
    MIDI_CONTROL_SHUTTER_AND_ISO = 2
    MIDI_CONTROL_WB = 3

    def __init__(self, switch_camera):
        self.target_camera = None
        self._fake_camera = FakeCamera()
        self.midi_mode = self.MIDI_CONTROL_FANCY
        self.broken_auto_iso = False
        self.xtouch = xtouch.XTouch('X-Touch X-TOUCH_INT',
                                    on_wheel=lambda diff: self.handle_midi_wheel(diff),
                                    on_button=lambda button, pressed: self.handle_midi_button(button, pressed))
        self.select_camera(self._fake_camera)
        self._switch_camera = switch_camera

    def select_camera(self, target_camera):
        if target_camera == self.target_camera:
            return
        if self.target_camera is not None:
            self.target_camera.camera_changed.disconnect()
        self.target_camera = target_camera
        self.target_camera.camera_changed.connect(lambda: self.propagate_to_midi())
        self.propagate_to_midi()
        self.target_camera.camera_changed.emit()  # FIXME: is it OK to emit like this?

    def propagate_to_midi(self):
        self.broken_auto_iso = self.target_camera.read_property('cameramodel') in (
            'Canon EOS 6D',
            'Canon EOS 5D Mark II',
            'Canon EOS 5D Mark III',
        )
        if self.target_camera is self._fake_camera:
            for ctrl in ('marker', 'nudge', 'cycle', 'drop', 'replace', 'click', 'solo'):
                self.xtouch.control_led(ctrl, False)
        elif self.midi_mode == self.MIDI_CONTROL_FANCY:
            if self.broken_auto_iso:
                self.xtouch.control_led('marker', True)
                self.xtouch.control_led('nudge', True)
                self.xtouch.control_led('cycle', True)
            elif self.target_camera.read_property('autoexposuremode') == 'Manual':
                self.xtouch.control_led('marker', True)
                self.xtouch.control_led('nudge', False)
                self.xtouch.control_led('cycle', False)
            elif self.target_camera.read_property('autoexposuremode') == 'AV':
                # we assume auto ISO, but we do not check that because the camera reports *actual* ISO value for some time
                # after things like shutter half-release
                self.xtouch.control_led('marker', False)
                self.xtouch.control_led('nudge', False)
                self.xtouch.control_led('cycle', True)
            else:
                self.xtouch.control_led('marker', False)
                self.xtouch.control_led('nudge', True)
                self.xtouch.control_led('cycle', True)
            self.xtouch.control_led('drop', False)
            self.xtouch.control_led('replace', False)
            self.xtouch.control_led('click', False)
            self.xtouch.control_led('solo', False)
            self.xtouch.control_led('zoom', self.target_camera.read_property('iso') == 'Auto')

            # AF
            self.xtouch.control_led('scrub', self.target_camera.read_property('movieservoaf') == 'On')

        elif self.midi_mode == self.MIDI_CONTROL_SHUTTER_AND_ISO:
            self.xtouch.control_led('marker', False)
            self.xtouch.control_led('nudge', False)
            self.xtouch.control_led('cycle', False)
            self.xtouch.control_led('drop', True)
            self.xtouch.control_led('replace', False)
            self.xtouch.control_led('click', False)
            self.xtouch.control_led('solo', False)
            self.xtouch.control_led('scrub', False)
            self.xtouch.control_led('zoom', self.target_camera.read_property('iso') == 'Auto')

        elif self.midi_mode == self.MIDI_CONTROL_WB:
            self.xtouch.control_led('marker', False)
            self.xtouch.control_led('nudge', False)
            self.xtouch.control_led('cycle', False)
            self.xtouch.control_led('drop', False)
            self.xtouch.control_led('replace', False)
            self.xtouch.control_led('click', False)
            self.xtouch.control_led('solo', True)
            self.xtouch.control_led('scrub', self.target_camera.read_property('whitebalance') != 'Color Temperature')
            self.xtouch.control_led('zoom', self.target_camera.read_property('whitebalanceadjusta') == '0'
                                    and self.target_camera.read_property('whitebalanceadjustb') == '0')

    def handle_midi_button(self, button, pressed):
        if not pressed:
            return

        if button in ('marker', 'nudge', 'cycle'):
            self.midi_mode = self.MIDI_CONTROL_FANCY
            self.propagate_to_midi()
            return
        if button == 'drop':
            self.midi_mode = self.MIDI_CONTROL_SHUTTER_AND_ISO
            self.propagate_to_midi()
            return
        if button == 'solo':
            self.midi_mode = self.MIDI_CONTROL_WB
            self.propagate_to_midi()
            return

        if button == 'previous':
            self._switch_camera('btn1')
        elif button == 'next':
            self._switch_camera('btn2')
        elif button in ('stop',):
            self._switch_camera('btn3')
        elif button == 'play':
            self._switch_camera('btn4')
        elif button == 'rec':
            self._switch_camera('btn5')

        if self.midi_mode == self.MIDI_CONTROL_FANCY:
            if button == 'scrub':
                try:
                    self.target_camera.adjust_absolute('movieservoaf', 'On')
                except Exception:
                    pass  # might not be supported at all

            if self.target_camera.read_property('autoexposuremode') == 'AV':
                up_down_prop = 'exposurecompensation'
            else:
                up_down_prop = 'iso' if self.broken_auto_iso else 'exposurecompensation'
            if button == 'left':
                self.target_camera.adjust_relative('aperture', -1)
            if button == 'right':
                self.target_camera.adjust_relative('aperture', 1)
            if button == 'up':
                self.target_camera.adjust_relative(up_down_prop, 1)
            if button == 'down':
                self.target_camera.adjust_relative(up_down_prop, -1)
            if button == 'zoom' and not self.broken_auto_iso:
                self.target_camera.adjust_absolute('iso', 'Auto')

        elif self.midi_mode == self.MIDI_CONTROL_SHUTTER_AND_ISO:
            if button == 'up':
                self.target_camera.adjust_relative('iso', 1)
            if button == 'down':
                self.target_camera.adjust_relative('iso', -1)
            if button == 'left':
                self.target_camera.adjust_relative('shutterspeed', -1)
            if button == 'right':
                self.target_camera.adjust_relative('shutterspeed', 1)
            if button == 'zoom' and not self.broken_auto_iso:
                self.target_camera.adjust_absolute('iso', 'Auto')

        elif self.midi_mode == self.MIDI_CONTROL_WB:
            if button == 'scrub':
                self.target_camera.adjust_absolute('whitebalance', 'Auto')
            if button == 'up':
                self.target_camera.adjust_relative('whitebalanceadjustb', 1)
            if button == 'down':
                self.target_camera.adjust_relative('whitebalanceadjustb', -1)
            if button == 'left':
                self.target_camera.adjust_relative('whitebalanceadjusta', -1)
            if button == 'right':
                self.target_camera.adjust_relative('whitebalanceadjusta', 1)
            if button == 'zoom':
                self.target_camera.adjust_absolute('whitebalanceadjusta', '0')
                self.target_camera.adjust_absolute('whitebalanceadjustb', '0')

    def handle_midi_wheel(self, diff):
        if self.midi_mode == self.MIDI_CONTROL_FANCY:
            try:
                self.target_camera.adjust_absolute('movieservoaf', 'Off')
            except Exception:
                pass  # might not be supported at all
            focus = None
            if diff > 0:
                if diff < 2:
                    focus = 'Far 1'
                elif diff < 4:
                    focus = 'Far 2'
                else:
                    focus = 'Far 3'
            elif diff < 0:
                if diff > -2:
                    focus = 'Near 1'
                elif diff > -4:
                    focus = 'Near 2'
                else:
                    focus = 'Near 3'
            self.target_camera.adjust_absolute('manualfocusdrive', focus)
        elif self.midi_mode == self.MIDI_CONTROL_WB:
            self.target_camera.adjust_absolute('whitebalance', 'Color Temperature')
            self.target_camera.adjust_relative('colortemperature', 1 if diff > 0 else -1)


class MiniMidiHandler:
    def __init__(self, switch_camera, switch_aux):
        self.target_camera = None
        self._fake_camera = FakeCamera()
        self.xtouch = xtouchmini.XTouchMini('X-TOUCH MINI MIDI 1',
                                            on_change=lambda what, value: self.on_midi_change(what, value),
                                            on_button=lambda button, down: self.on_midi_button(button, down))
        self.select_camera(self._fake_camera)
        self._switch_camera = switch_camera
        self.on_midi_button(14, False)
        self._switch_aux = switch_aux

    def on_midi_change(self, what, value):
        print(f'on_midi_change: {what=} {value=}')
        allowed = self.target_camera._allowed[what]
        if value in allowed:
            self.target_camera.adjust_absolute(what, value)
        else:
            print(f'!! Cannot set {what} to {value}. Allowed: {allowed}')
            self.propagate_to_midi()

    def on_midi_button(self, button, down):
        if down:
            return
        if button >= 0 and button <= 7:
            self._switch_camera(str(button + 1))
            # for x in range(0, 9):
            #     self.xtouch.set_led(x, 'on' if x == button else 'off')
        elif button == 14:
            self._auto_switch_aux = True
            self.xtouch.set_led(14, 'on')
            self.xtouch.set_led(15, 'off')
            if self.target_camera.switcher_input:
                self._switch_aux(str(self.target_camera.switcher_input))
        elif button == 15:
            self._switch_aux('MVW')
            self._auto_switch_aux = False
            self.xtouch.set_led(14, 'off')
            self.xtouch.set_led(15, 'on')

    def select_camera(self, target_camera):
        for x in range(0, 9):
            self.xtouch.set_led(x, 'on' if target_camera.switcher_input == str(x + 1) else 'off')
        if target_camera == self.target_camera:
            return
        if self.target_camera is not None:
            self.target_camera.camera_changed.disconnect()
        self.target_camera = target_camera
        self.target_camera.camera_changed.connect(lambda: self.propagate_to_midi())
        self.target_camera.camera_changed.emit()  # FIXME: is it OK to emit like this?

    def propagate_to_midi(self):
        if self.target_camera.read_property('cameramodel') is None:
            for encoder in xtouchmini.ENCODER_TO_FUNCTION.values():
                self.xtouch.leds_special(encoder, 'off')
            return

        for key, encoder in xtouchmini.ENCODER_TO_FUNCTION.items():
            if key == 'focus':
                # magic
                if self.target_camera.read_property('movieservoaf') == 'On':
                    self.xtouch.leds_special(encoder, 'all-on')
                else:
                    self.xtouch.leds_special(encoder, 'blink-center')
                continue

            val = self.target_camera.read_property(key)
            known_values = xtouchmini.results_for_function(key)
            try:
                idx = known_values.index(val)
            except ValueError:
                idx = None
            if idx is not None:
                midi_val = self.xtouch.range_for(encoder)[idx]
                print(f' midi: encoder {encoder} -> #{known_values.index(val)} (out of {len(known_values)})')
                self.xtouch.do_set_value(encoder, midi_val)
            else:
                print(f' midi: encoder {encoder}: no match for value {val}')
                self.xtouch.leds_special(encoder, 'blink-all')

            if key == 'colortemperature':
                wb = self.target_camera.read_property('whitebalance')
                if wb == 'Color Temperature':
                    pass
                elif wb == 'Auto':
                    print(f' midi: encoder {encoder}: all-on for AWB')
                    self.xtouch.leds_special(encoder, 'all-on')
                else:
                    print(f' midi: encoder {encoder}: WB neither AWB nor K')
                    self.xtouch.leds_special(encoder, 'blink-all')



if __name__ == "__main__":
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
    app = QGuiApplication(sys.argv)

    engine = QQmlApplicationEngine()

    cams = dict((name, CameraManager(name, switcher_input, do_tally)) for name, switcher_input, do_tally in (
        #'rpi-00000000ef688e57',
        #'rpi-00000000e7ee04d2',

        # # rpi-00000000363468bb: vlevo 35mm, 172.26.70.19
        # ('rpi-00000000363468bb', '6'),
        # # rpi-00000000e7ee04d2: vpravo 35mm, 172.26.70.20
        # ('rpi-00000000e7ee04d2', '7'),
        # # rpi-00000000d56be96f: uprostred tele, 172.26.70.21
        # # rpi-00000000ef688e57: 24-105 vzadu, 172.26.70.34
        # ('rpi-00000000ef688e57', '3'),
        ('rpi-00000000d56be96f', '2', False),
        ('rpi-00000000363468bb', '6', False), # samyang nahore
        ('rpi-00000000ef688e57', '1', False),
        ('rpi-00000000e7ee04d2', '5', False), # 5d3 nahore

        ('rpi-00000000b3a1193a', '4', False), # 5div vlevo dole

        # 5Diii 35
        # ('rpi-00000000d56be96f', None),
        # 5Div 70-200
        # ('rpi-00000000b3a1193a', None),
        # WTF?
        # ('rpi-00000000ef688e57', None),
        # RP Fortna
        # with that wooden thingy
        # ('rpi-00000000538f432e', '3'),
    ))

    def switch_camera_xtouch(which):
        if which == 'btn1':
            # tmp_cam = cams['rpi-00000000d56be96f']
            tmp_cam = cams['rpi-00000000b3a1193a']
            target_led = 'previous'
        elif which == 'btn2':
            tmp_cam = cams['rpi-00000000363468bb']
            target_led = 'next'
        elif which == 'btn3':
            tmp_cam = cams['rpi-00000000e7ee04d2']
            target_led = 'stop'
        elif which == 'btn4':
            tmp_cam = cams['rpi-00000000ef688e57']
            target_led = 'play'
        # elif which == 'btn5':
        #     tmp_cam = cams['rpi-00000000538f432e']
        #     target_led = 'rec'
        else:
            tmp_cam = midi_ctl._fake_camera
            target_led = None
        ctx = engine.rootContext()
        invoke_in_main_thread(QQmlContext.setContextProperty, ctx, "camera", tmp_cam)
        midi_ctl.select_camera(tmp_cam)
        for led in 'previous', 'next', 'stop', 'play', 'rec':
            midi_ctl.xtouch.control_led(led, target_led == led)
        if target_led is None:
            for led in (
                'marker', 'nudge', 'cycle', 'drop', 'replace', 'click', 'solo', 'scrub',
                'zoom', 'left', 'right', 'up', 'down'):
                midi_ctl.xtouch.control_led(led, False)

    def switch_camera_xtouch_mini(which):
        ctx = engine.rootContext()
        target_cam = next((cam for cam in cams.values() if cam.switcher_input == str(which)), midi_ctl._fake_camera)
        invoke_in_main_thread(QQmlContext.setContextProperty, ctx, "camera", target_cam)
        midi_ctl.select_camera(target_cam)
        if target_cam is not midi_ctl._fake_camera and midi_ctl._auto_switch_aux:
            midi_ctl._switch_aux(str(which))
        else:
            midi_ctl._switch_aux('MVW')


    # timer = QTimer()
    # timer.timeout.connect(lambda: camera.update_data({'iso': '200'} if camera.read_property('iso') == '100' else {'iso': '100'}))
    # timer.start(1000)

    engine.load('OneCamView.qml')
    if not engine.rootObjects():
        sys.exit(-1)

    bus = MessageBus(cams)
    bus.start()
    bus.start_event.wait()

    # midi_ctl = MidiHandler(switch_camera=switch_camera_xtouch)
    # switch_camera_xtouch('')
    midi_ctl = MiniMidiHandler(switch_camera=switch_camera_xtouch_mini, switch_aux=bus._switch_aux)
    switch_camera_xtouch_mini('')

    ret = app.exec_()
    bus.request_exit()
    bus.wait()
    sys.exit(ret)
