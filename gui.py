import asyncio
import asyncio_mqtt as am
from contextlib import AsyncExitStack
import json
import os
import sys
import threading

from PySide2.QtCore import Qt, QObject, Signal, Slot, Property, QTimer, QThread
from PySide2.QtGui import QGuiApplication
from PySide2.QtQml import QQmlApplicationEngine

import xtouch


class CameraManager(QObject):
    def __init__(self, name):
        QObject.__init__(self)
        self._camera_name = name
        self._data = {
            'cameramodel': '<camera>',
            'lensname': '<lens>',
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
        self._mqtt_send = None

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
        self.camera_changed.emit()  # FIXME: is it OK to emit like this?

    def store_allowed(self, data):
        # safe to call from other threads
        with self._lock:
            for k, v in data.items():
                self._allowed[k] = v

    camera_changed = Signal()

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
        if self._mqtt_send is not None:
            print(f'set {key} -> {value}')
            self._mqtt_send(self._camera_name, key, value)
            self._update_last_change(key)

    last_changed_changed = Signal()
    last_changed = Property(str, lambda self: self._last_changed, notify=last_changed_changed)


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


class ShouldExit(Exception):
    pass



class MessageBus(QThread):
    def __init__(self, cameras):
        QThread.__init__(self)
        self.cameras = cameras
        self.start_event = threading.Event()
        self.exit_future = None

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

            for topic in (topic_allowed, topic_settings):
                await client.subscribe(topic)

            async def wait_for_requested_exit():
                await self.exit_future
                raise ShouldExit()

            tasks.add(asyncio.create_task(wait_for_requested_exit()))

            def on_mqtt_send_requested(camera_name, key, value):
                if client is not None:
                    asyncio.run_coroutine_threadsafe(client.publish(f'camera/{camera_name}/set/{key}', value), loop)

            for camera in self.cameras.values():
                camera._mqtt_send = on_mqtt_send_requested

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

    def __init__(self, target_camera):
        self.target_camera = target_camera
        self.midi_mode = self.MIDI_CONTROL_FANCY
        self.xtouch = xtouch.XTouch('X-Touch X-TOUCH_INT',
                                    on_wheel=lambda diff: self.handle_midi_wheel(diff),
                                    on_button=lambda button, pressed: self.handle_midi_button(button, pressed))
        self.target_camera.camera_changed.connect(lambda: self.propagate_to_midi())

    def propagate_to_midi(self):
        if self.midi_mode == self.MIDI_CONTROL_FANCY:
            self.xtouch.control_led('drop', False)
            self.xtouch.control_led('replace', False)
            self.xtouch.control_led('click', False)
            self.xtouch.control_led('solo', False)
            if self.target_camera.read_property('autoexposuremode') == 'Manual':
                self.xtouch.control_led('marker', True)
                self.xtouch.control_led('nudge', False)
                self.xtouch.control_led('cycle', False)
            elif self.target_camera.read_property('autoexposuremode') == 'AV':
                # we assume auto ISO, but we do not check that because the camera reports *actual* ISO value for some time
                # after things like shutter half-release
                self.xtouch.control_led('marker', False)
                self.xtouch.control_led('nudge', True)
                self.xtouch.control_led('cycle', False)
            else:
                self.xtouch.control_led('marker', False)
                self.xtouch.control_led('nudge', False)
                self.xtouch.control_led('cycle', True)
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

        if self.midi_mode == self.MIDI_CONTROL_FANCY:
            if button == 'scrub':
                try:
                    self.target_camera.adjust_absolute('movieservoaf', 'On')
                except Exception:
                    pass  # might not be supported at all

            if button == 'left':
                self.target_camera.adjust_relative('aperture', -1)
            if button == 'right':
                self.target_camera.adjust_relative('aperture', 1)
            if button == 'up':
                self.target_camera.adjust_relative('exposurecompensation', 1)
            if button == 'down':
                self.target_camera.adjust_relative('exposurecompensation', -1)
            if button == 'zoom':
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
            if button == 'zoom':
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



if __name__ == "__main__":
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
    app = QGuiApplication(sys.argv)

    engine = QQmlApplicationEngine()

    cams = dict((name, CameraManager(name)) for name in ('rpi-00000000ef688e57', 'rpi-00000000e7ee04d2',))

    tmp_cam = cams['rpi-00000000e7ee04d2']
    # tmp_cam = cams['rpi-00000000ef688e57']

    ctx = engine.rootContext()
    ctx.setContextProperty("camera", tmp_cam)

    # timer = QTimer()
    # timer.timeout.connect(lambda: camera.update_data({'iso': '200'} if camera.read_property('iso') == '100' else {'iso': '100'}))
    # timer.start(1000)

    engine.load('OneCamView.qml')
    if not engine.rootObjects():
        sys.exit(-1)

    bus = MessageBus(cams)
    bus.start()
    bus.start_event.wait()

    midi_ctl = MidiHandler(tmp_cam)

    ret = app.exec_()
    bus.request_exit()
    bus.wait()
    sys.exit(ret)
