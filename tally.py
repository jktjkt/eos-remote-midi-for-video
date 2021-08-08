#!/usr/bin/env python3
#
# Remote control of Canon EOS cameras for live video streaming.
# Includes tally LED control on an add-on board.
#
# Copyright (C) 2021 Jan Kundrát <jkt@jankundrat.com>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import asyncio
from contextlib import AsyncExitStack
import socket
import sys
import asyncio_mqtt as am
import gphoto2 as gp
import queue
import threading
import json
try:
    import smbus
except ImportError:
    smbus = None


class I2CRegisters:
    def __init__(self, bus, device):
        self.bus = smbus.SMBus(bus)
        self.address = device

    def write_block(self, register, data):
        self.bus.write_i2c_block_data(self.address, register, data)


class TallyLEDs:
    def __init__(self):
        self.i2c = I2CRegisters(1, 0x0c)
        self.i2c.write_block(0x17, [0xff])
        self.i2c.write_block(0x00, [0x40])

    def tally(self, brightness):
        self.i2c.write_block(0x0b, 6 * [brightness])

    def preview(self, red, green, blue):
        self.i2c.write_block(0x11, [red, green, blue])


class FakeTally:
    def tally(self, brightness):
        print(f'tally: {brightness}')

    def preview(self, red, green, blue):
        print(f'preview: {red} {green} {blue}')
        self.i2c.write_block(0x11, [red, green, blue])


async def do_tally_light(led, messages):
    async for message in messages:
        print(f'tally: {message.payload}')
        brightness = int(message.payload)
        led.tally(brightness)


async def do_preview_light(led, messages):
    async for message in messages:
        print(f'preview: {message.payload}')
        (red, green, blue) = [int(x) for x in message.payload.split(b' ')]
        led.preview(red, green, blue)


class Camera(threading.Thread):
    PROPS_RO = (
        'cameramodel', 'lensname', 'autoexposuremode', 'autoexposuremodedial',
    )
    PROPS_WO = (
        'manualfocusdrive',
    )
    PROPS_RW = (
        'aperture', 'shutterspeed', 'exposurecompensation', 'iso', 'movieservoaf',
        'whitebalance', 'colortemperature', 'whitebalanceadjusta', 'whitebalanceadjustb'
    )

    def __init__(self, event_handler, on_death, on_dump_allowed):
        threading.Thread.__init__(self)
        self.daemon = True
        self.event_handler = event_handler
        self.old_status = None
        self.queue = queue.Queue()
        self.on_death = on_death
        self.on_dump_allowed = on_dump_allowed

    def run(self):
        try:
            self.cam = gp.Camera()
            self.cam.init()
            cfg = self.cam.get_config()

            viewfinder = cfg.get_child_by_name('viewfinder')
            viewfinder.set_value(1)
            self.cam.set_single_config('viewfinder', viewfinder)

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
        except Exception as e:
            self.on_death(e)
            raise

    def on_config_changed(self):
        cfg = self.cam.get_config()
        status = {}
        for name in self.PROPS_RO + self.PROPS_RW:
            try:
                value = cfg.get_child_by_name(name).get_value()
            except gp.GPhoto2Error:
                value = None
            status[name] = value
        if self.old_status != status:
            self.old_status = status
            self.event_handler(**status)

    def apply_command(self, what, value):
        if what == 'DUMP':
            self.old_status = None
            self.on_config_changed()
            cfg = self.cam.get_config()
            allowed = {}
            for k in self.PROPS_RW + self.PROPS_RO:
                try:
                    w = cfg.get_child_by_name(k)
                    allowed[k] = [x for x in w.get_choices()]
                except gp.GPhoto2Error:
                    continue
            self.on_dump_allowed(allowed)
            return

        if what in self.PROPS_RW + self.PROPS_WO:
            cfg = self.cam.get_config()
            try:
                w = cfg.get_child_by_name(what)
            except gp.GPhoto2Error:
                print(f'Unsupported property: {what}')
                return
            if w.get_type() == gp.GP_WIDGET_RADIO or w.get_type() == gp.GP_WIDGET_MENU:
                if value not in w.get_choices():
                    possibilities = ', '.join(w.get_choices())
                    print(f'!!! Cannot set {what} to {value}. Allowed values: {possibilities}')
                    return
            if w.get_value() == value:
                return
            w.set_value(value)
            print(f' set {what} = {value}')
            self.cam.set_single_config(what, w)
            if what == 'colortemperature':
                self.apply_command('whitebalance', 'Color Temperature')


async def push_to_camera(camera, messages):
    async for message in messages:
        for prop in Camera.PROPS_RW + Camera.PROPS_WO:
            if message.topic.endswith(f'/{prop}'):
                value = message.payload.decode('utf-8')
                print(f'MQTT -> camera: {prop} = {value}')
                camera.queue.put([prop, value])


async def do_republish(camera, messages):
    async for message in messages:
        print(f'MQTT: asked to republish')
        camera.queue.put(['DUMP', None])


async def cancel_tasks(tasks):
    for task in tasks:
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def main(led):
    loop = asyncio.get_running_loop()
    camera_exception_f = loop.create_future()
    client = None
    my_hostname = socket.gethostname()
    topic_tally = f'camera/{my_hostname}/tally'
    topic_preview = f'camera/{my_hostname}/preview'
    topic_status = f'camera/{my_hostname}/status'
    topic_camera = f'camera/{my_hostname}/set/#'
    camera_current = f'camera/{my_hostname}/current'
    camera_allowed = f'camera/{my_hostname}/allowed'
    topic_republish = 'camera/dump-all'

    def on_camera_change(**kwargs):
        print(f'camera -> MQTT: {kwargs}')
        if client is not None:
            asyncio.run_coroutine_threadsafe(client.publish(camera_current, json.dumps(kwargs)), loop)

    def on_camera_allowed(values):
        print(f'camera -> allowed values: {values}')
        if client is not None:
            asyncio.run_coroutine_threadsafe(client.publish(camera_allowed, json.dumps(values)), loop)

    def on_camera_death(e):
        loop.call_soon_threadsafe(camera_exception_f.set_exception, e)

    async def wait_for_camera_death():
        try:
            await camera_exception_f
        except Exception as e:
            await client.publish(f'{topic_status}', repr(e))
            raise

    camera = Camera(event_handler=on_camera_change, on_death=on_camera_death, on_dump_allowed=on_camera_allowed)

    async def join_camera():
        res = await camera.future
        if res is not None:
            await client.publish(topic_status, str(res))
            raise res

    while True:
        # Endless network reconnects while the camera works. Should be restarted externally when the camera disconnects.
        try:
            async with AsyncExitStack() as stack:
                tasks = set()
                stack.push_async_callback(cancel_tasks, tasks)

                will = am.Will(topic=topic_status, payload='offline')
                client = am.Client(sys.argv[1], keepalive=3, client_id=f'cam-{my_hostname}', will=will)
                await stack.enter_async_context(client)

                tally_msgs = await stack.enter_async_context(client.filtered_messages(topic_tally))
                tasks.add(asyncio.create_task(do_tally_light(led, tally_msgs), name='mqtt->tally'))

                preview_msgs = await stack.enter_async_context(client.filtered_messages(topic_preview))
                tasks.add(asyncio.create_task(do_preview_light(led, preview_msgs), name='mqtt->preview'))

                cam_msgs = await stack.enter_async_context(client.filtered_messages(topic_camera))
                tasks.add(asyncio.create_task(push_to_camera(camera, cam_msgs), name='mqtt->camera'))

                republish_msgs = await stack.enter_async_context(client.filtered_messages(topic_republish))
                tasks.add(asyncio.create_task(do_republish(camera, republish_msgs), name='republish from camera'))

                for topic in (topic_tally, topic_preview, topic_camera, topic_republish):
                    await client.subscribe(topic)

                await client.publish(topic_status, 'online')
                camera.queue.put(['DUMP', None])
                camera.start()

                tasks.add(asyncio.create_task(wait_for_camera_death(), name='catch camera exceptions'))

                await asyncio.gather(*tasks)

        except am.MqttError as e:
            print(f'MQTT error: {e}')
        finally:
            await asyncio.sleep(1)

try:
    if smbus is not None:
        led = TallyLEDs()
    else:
        led = FakeTally()
    asyncio.run(main(led), debug=True)
finally:
    if smbus is not None:
        led.i2c.write_block(0x0b, 9 * [0x00])
