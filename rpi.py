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
from PySide2.QtQuick import QQuickView

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


class SwitcherState(QObject):
    def __init__(self):
        QObject.__init__(self)
        self._aux = 'MVW'

    prop_changed = Signal()
    aux_content = Property(str, lambda self: self._aux, notify=prop_changed)


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
        self._last_changed_timeout.setInterval(1000)
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
        print(f'MQTT: {message.topic}: {message.payload}')


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
            client = am.Client('fdd5:c0a3:13e3:2666::11')
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
        print(f'on_midi_change: what={what} value={value}')
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
    os.environ['QT_QPA_PLATFORM'] = 'eglfs'
    os.environ['QT_QPA_EGLFS_ALWAYS_SET_MODE'] = '1'
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    switcher_state = SwitcherState()
    engine.rootContext().setContextProperty("switcher_state", switcher_state)
    cam_switched = QTimer()
    cam_switched.setSingleShot(True)
    cam_switched.setInterval(0)
    engine.rootContext().setContextProperty("cam_switched", cam_switched)

    cams = dict((name, CameraManager(name, switcher_input, do_tally)) for name, switcher_input, do_tally in (
        ('rpi-00000000538f432e', '1', False), # R6 24-240
        # ('rpi-00000000ef688e57', '1', False), # 70-200 vzadu
        ('rpi-00000000xxxxxxxx', '2', False), # RP + 24-105 "mobilni"
        ('rpi-00000000b3a1193a', '3', False), # kazatelna
        ('rpi-00000000363468bb', '4', False), # sirokey za oltarem
        ('rpi-00000000yyyyyyyy', '5', False), # RP + 24-105 variabilni, vzadu, unmanned
        ('rpi-00000000d56be96f', '6', False), # dirigent
        ('rpi-00000000e7ee04d2', '7', False), # 24-105 RP Damian
    ))

    def switch_camera_xtouch_mini(which):
        ctx = engine.rootContext()
        target_cam = next((cam for cam in cams.values() if cam.switcher_input == str(which)), midi_ctl._fake_camera)
        invoke_in_main_thread(QQmlContext.setContextProperty, ctx, "camera", target_cam)
        midi_ctl.select_camera(target_cam)
        if target_cam is not midi_ctl._fake_camera and midi_ctl._auto_switch_aux:
            midi_ctl._switch_aux(str(which))
        else:
            midi_ctl._switch_aux('MVW')
        invoke_in_main_thread(QTimer.start, cam_switched)


    # timer = QTimer()
    # timer.timeout.connect(lambda: camera.update_data({'iso': '200'} if camera.read_property('iso') == '100' else {'iso': '100'}))
    # timer.start(1000)

    engine.load('PiMain.qml')
    if not engine.rootObjects():
        sys.exit(-1)

    bus = MessageBus(cams)
    bus.start()
    bus.start_event.wait()

    def switch_aux(out):
        bus._switch_aux(out)
        switcher_state._aux = out
        switcher_state.prop_changed.emit()

    midi_ctl = MiniMidiHandler(switch_camera=switch_camera_xtouch_mini, switch_aux=switch_aux)
    switch_camera_xtouch_mini('')

    ret = app.exec_()
    bus.request_exit()
    bus.wait()
    sys.exit(ret)
