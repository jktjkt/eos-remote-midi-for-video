import asyncio
from contextlib import AsyncExitStack
import socket
import sys
import asyncio_mqtt as am
import smbus


async def do_tally_light(messages):
    async for message in messages:
        print(f'tally: {message.payload}')
        brightness = int(message.payload)
        LEDs.tally(brightness)


async def do_preview_light(messages):
    async for message in messages:
        print(f'preview: {message.payload}')
        (red, green, blue) = [int(x) for x in message.payload.split(b' ')]
        LEDs.preview(red, green, blue)


async def do_keepalive(client, topic):
    while True:
        await client.publish(topic, 1)
        await asyncio.sleep(3)


async def run(server):
    my_hostname = socket.gethostname()
    topic_tally = f'tally/{my_hostname}/tally'
    topic_preview = f'tally/{my_hostname}/preview'
    topic_ping = f'tally/{my_hostname}/alive'
    async with AsyncExitStack() as stack:
        tasks = set()
        stack.push_async_callback(cancel_tasks, tasks)
        client = am.Client(server)
        await stack.enter_async_context(client)

        tally_msgs = await stack.enter_async_context(client.filtered_messages(topic_tally))
        tasks.add(asyncio.create_task(do_tally_light(tally_msgs)))

        preview_msgs = await stack.enter_async_context(client.filtered_messages(topic_preview))
        tasks.add(asyncio.create_task(do_preview_light(preview_msgs)))

        for topic in (topic_tally, topic_preview):
            await client.subscribe(topic)

        tasks.add(asyncio.create_task(do_keepalive(client, topic_ping)))

        await asyncio.gather(*tasks)


async def cancel_tasks(tasks):
    for task in tasks:
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def main():
    while True:
        try:
            await run(sys.argv[1])
        except am.MqttError as e:
            print(f'MQTT error: {e}')
        finally:
            await asyncio.sleep(1)


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


try:
    LEDs = TallyLEDs()
    asyncio.run(main())
finally:
    LEDs.i2c.write_block(0x0b, 9 * [0x00])
