# Setup

## Addressing & connections

Oranzovy router.

```
ip -6 a add fdd5:c0a3:13e3:2666::11/64 dev enp2s0f0
```

Multiview always-on: HDMI OUT 2
Aux for camera control: HDMI OUT 1

## MQTT

```
mosquitto -v -c ~/work/led-pekac/fw/board/pi/mosquitto.conf
```

## NOT HERE: MIDI

```
cd ~/work/prog/eos-remote-midi-for-video
nix-shell build.nix
python gui.py
```

## RPi4 MIDI + indication:

- Extreme HDMI OUT 1 -> Mini IN 1
- RPi HDMI0 (next to the USB-C PD) -> Mini IN 2

```
ssh pi@malina-zavrena bash -c "'cd app ; . .ve/bin/activate; python3 rpi.py'"
```

## Atem

```
cd ~/work/prog/pyatem
. .py39-v2/bin/activate
python3 -m openswitcher_proxy --config proxy.toml
```
