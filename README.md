# Remote camera operations via MIDI

Not every camera is (wo)maned by an operator, and this repo is about allowing their remote control from a MIDI console.
The (only) focus is on live video streaming, so the interface is *opinionated*.
Auto ISO is assumed, and 1/50s is the shutter speed of choice.
Tested with Canon EOS 5D IV and Canon EOS RP on Linux.

## Local access

Use Behringer X-Touch Mini to drive a camera that is directly connected via USB.
Encoder mapping:

- Manual focus
- Exposure compensation
- Aperture
- Shutter speed (1/50s at the 12'o-clock position)
- unassigned
- White Balance: click for AWB, spin for Kelvins
- WB Blue/Amber
- WB Magenta/Green

The MIDI controller requires a special configuration.
That's a one-time thing which currently requires Behringer's Windows editor software.

TODO: enable/disable AF. Needs some gphoto2 changes?

## Remote access

This part is not implemented yet.
Use Behringer X-Touch in the combined Xctrl + HUI mode.
Connect a single-board computer to each (remote) camera via USB.
Use the spare buttons for camera preview control via Atem Mini, then spin the jog wheel for focus fine tuning.
This will probably require some proxy messaging server to work around Atem Mini connection limit.

TODO: implement this. Get the Atem Mini Extreme for that AUX bus so as not to interfere with multiview.
