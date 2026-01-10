# TODO

misc unformatted notes - not yet useful...

* test passing in my custom yaml
* add layer detection due to bluetooth
* show zmk bluetooth info in window
* show zmk bluetooth info in system tray
* take a short video
* fix pypi publish


## keymap editor

best: https://nickcoutsos.github.io/keymap-editor/ but doesn't work with miryoku
Use this to render: https://github.com/caksoylar/keymap-drawer?tab=readme-ov-file#try-it-as-a-web-application
Installed into devcontainer or at https://keymap-drawer.streamlit.app/

### In my custom tool

Look at how the prospector status_foo.c code is subscribing for events and then sending them over BLE.  Possibly have PC subscribe NATIVELY - so no need to prospector dongle!
to show layer changes - https://github.com/t-ogura/zmk-config-prospector?tab=readme-ov-file#-protocol-specification 
But first do it as a streamdeck button because easy
To write a kde widget: https://develop.kde.org/docs/plasma/widget/setup/ 

In learning mode: initially show all keys, as you get keys right (user typed but didn't press backspace) fade them out.  So eventually you just see the keys you haven't learned yet.


* !Render with https://github.com/caksoylar/keymap-drawer/blob/main/keymap_drawer/draw/draw.py
* ! Pass in draw_layers = foo to limit to a single current layer
* Modify ZMK to send a special message (protobuf?) when a layer change occurs - Just sending raw scancodes
is not useful because you don't know how the keymap is applied.
* test zmk studio usage https://zmk.dev/docs/features/studio - possibly use their protobufs as a way of adding live keypress data, so that they can use it as well.
* use a subclass of Notification to send layer change notifications: https://github.com/zmkfirmware/zmk-studio-messages/blob/main/proto/zmk/studio.proto#L38
* also send raw key press scancodes because it might be cool
* for proof of concept just start sending at boot - for real code wait until gatt/serial connect fom PC to turn that feature on/off (no point wasting battery if feature unused) (Treat the CCCD Write (0x01) as your "Session Start." - Treat the CCCD Write (0x00) or Link Disconnect as your "Session End.")
* possibly use "advertisement/GAP" packets as lower overhead/less reliable raw scancode notifications?
* this says they are using GATT Indications for messages from device to PC which is 'not great' - slow and synchronous.  Check to see if they can use notififcations instead https://zmk.dev/docs/development/studio-rpc-protocol.
* possibly fix flatpak for them https://github.com/zmkfirmware/zmk-studio/issues/91 
* could use F13-F20 for early proof of concept  
* ask keymap-drawer author how he wants this, as a PR or just use his thing as a library
* Eventually use a similar mechanism to provide easy runtime macro setting from host PC.  Kinda a host side zmk utility similar to studio
* status packet definition here: https://github.com/t-ogura/prospector-zmk-module/blob/main/include/zmk/status_advertisement.h 

## Dongle config

https://github.com/englmaxi/zmk-dongle-display?tab=readme-ov-file 
per 
https://www.reddit.com/r/ErgoMechKeyboards/comments/1ppscyc/help_add_a_dongle_to_a_repository/nuoxxms/
https://beekeeb.com/how-to-add-dongle-and-prospector-support-to-hshs52-hshs46/
https://zmk.dev/docs/development/hardware-integration/dongle

Probably the code for my version is here.  https://github.com/a741725193/zmk-corne-dongle is better?

It seems to pull in prospector-zmk-module from https://github.com/tokyo2006/prospector-zmk-module but that is just a fork of https://github.com/carrefinho/prospector-zmk-module 
But the new version of prospector-zmk (with satalite code added) is at https://github.com/t-ogura/prospector-zmk-module
It receives statust broadcasts here https://github.com/t-ogura/prospector-zmk-module/blob/main/src/status_scanner.c 
Sends broadcasts here: https://github.com/t-ogura/prospector-zmk-module/blob/main/src/status_advertisement.c

The underlying driver seems to be this! https://github.com/englmaxi/zmk-dongle-display 


### Prospector satalite config

* Add status broadcasts to the keyboard code https://github.com/t-ogura/zmk-config-prospector
* Update zmk-sofle-dongle to receive and display those broadcasts

## Project idea: zmk macros

* record keypresses and mouse movements by talking protobuf to keyboard (capture events at the zmk level?)
* allow user to save/share those macro files
* send macro files to device (assigning them to a key)
* But macros ON device are inherently problematic.  Perhaps better to just use an existing on PC linux macro 
layer? https://www.reddit.com/r/ErgoMechKeyboards/comments/1h557mt/zmk_macro_over_bluetooth_any_way_to_increase_speed/
Existing projects:
https://github.com/AntiMicroX/antimicrox
https://github.com/alper-han/CrossMacro?tab=readme-ov-file
(ugly) https://github.com/sezanzeb/input-remapper

## Live keyboard layout displays

A desktop helper app (in python?) that talks to zwk and:
* show current mode/layer, current key layout/presses, battery levels

Dev of this app is nice, I said I'd add BT ZMK support: https://github.com/maatthc/keyboard_layers_app_companion
FIXME tell him about the new python thing?

Rawhid is probably not the answer - that's the layer that is used to send protobufs to/from the keyboard
* ZMK module to add raw-hid: https://github.com/zzeneg/zmk-raw-hid
* The host side code for receiving this raw press data: https://github.com/zzeneg/qmk-hid-host?tab=readme-ov-file
* Possibly use https://github.com/woboq/qmetaobject-rs or https://github.com/KDE/rust-qt-binding-generator to write a tiny KDE tray widget 
* Example of how to write custom zmk widget: https://github.com/zzeneg/zmk-nice-view-hid
* Very pretty keyboard that uses this: https://github.com/zzeneg/stront

Possibly just add extra outputs to the layer switch buttons in the zmk keymap.  gemini says the best way is to use F13 through F24 - because linux drops everything else.  &kp F13.
Change the U_LT() macro defs in in miroku to add this behavior.  

Gemini says it is best to define new Report IDs
The Mechanism: Report IDs
You don't jam your custom data into the standard 8-byte keyboard report (that would break the Boot Protocol spec). Instead, you define multiple "Reports" within your descriptor, distinguished by a 1-byte prefix called the Report ID.

Here is how the traffic looks on the wire:

Report ID 1 (Standard): 01 <Modifiers> <Reserved> <Key1> <Key2>...

OS Driver: hid-input (Treats this as a keyboard).

Report ID 2 (Consumer): 02 <VolUp> <PlayPause>...

OS Driver: hid-input (Treats this as media buttons).

Report ID 3 (Vendor/Custom): 03 <MyCustomByte> <MyOtherByte>...

OS Driver: hid-generic (Ignores it, but exposes it via /dev/hidraw).

How to Implement It (The "Safe" Way)
To define "keys" that standard OS drivers won't touch (avoiding conflicts), you use Vendor Defined Usage Pages.

The Usage Page: The USB HID spec reserves 0xFF00 through 0xFFFF for vendors.

Standard Keyboard is Page 0x07.

Consumer (Media) is Page 0x0C.

Your Custom Stuff should be Page 0xFF60 (or similar).

The Descriptor: You modify your device's HID Descriptor to declare this new collection.

C

// Conceptual Descriptor Segment
0x06, 0x60, 0xFF,  // Usage Page (Vendor Defined 0xFF60)
0x09, 0x61,        // Usage (Vendor Defined 0x61 - "My Custom Thing")
0xA1, 0x01,        // Collection (Application)
0x85, 0x03,        //   Report ID (3) <--- The magic discriminator
0x15, 0x00,        //   Logical Minimum (0)
0x26, 0xFF, 0x00,  //   Logical Maximum (255)
0x75, 0x08,        //   Report Size (8 bits)
0x95, 0x20,        //   Report Count (32 bytes)
0x81, 0x02,        //   Input (Data, Var, Abs)
0xC0               // End Collection
