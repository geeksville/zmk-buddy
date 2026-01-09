"""
ZMK BLE Client - Listens for BLE advertisements from ZMK keyboards.

This module uses the Bleak library to scan for BLE advertisements from ZMK keyboards
that have the Prospector status advertisement module enabled. It parses the 26-byte
manufacturer data payload to extract keyboard status information.

Protocol specification: https://github.com/t-ogura/zmk-config-prospector
Message structure: https://github.com/t-ogura/prospector-zmk-module/blob/main/include/zmk/status_advertisement.h
"""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Callable

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

logger = logging.getLogger(__name__)


# Protocol constants
PROSPECTOR_SERVICE_UUID = bytes([0xAB, 0xCD])
MANUFACTURER_ID = 0xFFFF  # Custom/Local use manufacturer ID


class StatusFlags(IntFlag):
    """Status flags from the ZMK status advertisement (offset 9)."""

    CAPS_WORD = 1 << 0
    CHARGING = 1 << 1
    USB_CONNECTED = 1 << 2
    USB_HID_READY = 1 << 3
    BLE_CONNECTED = 1 << 4
    BLE_BONDED = 1 << 5
    # Bits 6-7 reserved


class ModifierFlags(IntFlag):
    """Modifier key flags (offset 23)."""

    LCTL = 1 << 0  # Left Control
    LSFT = 1 << 1  # Left Shift
    LALT = 1 << 2  # Left Alt
    LGUI = 1 << 3  # Left GUI (Win/Cmd)
    RCTL = 1 << 4  # Right Control
    RSFT = 1 << 5  # Right Shift
    RALT = 1 << 6  # Right Alt
    RGUI = 1 << 7  # Right GUI


class DeviceRole(IntEnum):
    """Device role in split keyboard configuration."""

    STANDALONE = 0
    CENTRAL = 1
    PERIPHERAL = 2


@dataclass
class ZMKStatusAdvertisement:
    """
    Parsed ZMK status advertisement data (26 bytes).

    BLE Advertisement Format:
    | Offset | Field | Size | Description |
    |--------|-------|------|-------------|
    | 0-1 | Manufacturer ID | 2 bytes | 0xFF 0xFF (Custom/Local use) |
    | 2-3 | Service UUID | 2 bytes | 0xAB 0xCD (Prospector Protocol ID) |
    | 4 | Protocol Version | 1 byte | Protocol version (current: 0x01) |
    | 5 | Battery Level | 1 byte | Main battery 0-100% |
    | 6 | Active Layer | 1 byte | Current layer 0-15 |
    | 7 | Profile Slot | 1 byte | BLE profile 0-4 |
    | 8 | Connection Count | 1 byte | Number of connected BLE devices 0-5 |
    | 9 | Status Flags | 1 byte | USB/BLE/Charging/Caps Lock bits |
    | 10 | Device Role | 1 byte | 0=Standalone, 1=Central, 2=Peripheral |
    | 11 | Device Index | 1 byte | Split keyboard index (0=left, 1=right) |
    | 12-14 | Peripheral Batteries | 3 bytes | Left/Right/Aux battery levels |
    | 15-18 | Layer Name | 4 bytes | ASCII layer identifier |
    | 19-22 | Keyboard ID | 4 bytes | Hash of keyboard name |
    | 23 | Modifier Flags | 1 byte | L/R Ctrl,Shift,Alt,GUI states |
    | 24 | WPM Value | 1 byte | Words per minute 0-255 |
    | 25 | Channel | 1 byte | Channel number 0-255 |
    """

    # Header fields
    manufacturer_id: int
    service_uuid: bytes
    version: int

    # Status fields
    battery_level: int
    active_layer: int
    profile_slot: int
    connection_count: int
    status_flags: StatusFlags
    device_role: DeviceRole
    device_index: int

    # Peripheral batteries (for split keyboards)
    peripheral_batteries: tuple[int, int, int]

    # Identification
    layer_name: str
    keyboard_id: int

    # Input state
    modifier_flags: ModifierFlags
    wpm_value: int
    channel: int

    # Metadata (not from advertisement payload)
    rssi: int = 0
    device_address: str = ""
    device_name: str = ""

    @classmethod
    def from_manufacturer_data(
        cls,
        data: bytes,
        rssi: int = 0,
        device_address: str = "",
        device_name: str = "",
    ) -> ZMKStatusAdvertisement | None:
        """
        Parse a 26-byte manufacturer data payload into a ZMKStatusAdvertisement.

        Args:
            data: The 26-byte manufacturer data payload
            rssi: Signal strength in dBm
            device_address: BLE device address
            device_name: Device name from scan response

        Returns:
            Parsed ZMKStatusAdvertisement or None if parsing fails
        """
        if len(data) != 26:
            logger.debug(f"Invalid payload length: {len(data)} (expected 26)")
            return None

        # Check service UUID (bytes 2-3 should be 0xAB 0xCD)
        if data[2:4] != PROSPECTOR_SERVICE_UUID:
            logger.debug(f"Invalid service UUID: {data[2:4].hex()}")
            return None

        try:
            # Parse the structure
            manufacturer_id = struct.unpack("<H", data[0:2])[0]
            service_uuid = data[2:4]
            version = data[4]
            battery_level = data[5]
            active_layer = data[6]
            profile_slot = data[7]
            connection_count = data[8]
            status_flags = StatusFlags(data[9])
            device_role = DeviceRole(data[10])
            device_index = data[11]
            peripheral_batteries = (data[12], data[13], data[14])

            # Layer name is 4 bytes, null-terminated
            layer_name_bytes = data[15:19]
            layer_name = layer_name_bytes.rstrip(b"\x00").decode("ascii", errors="replace")

            # Keyboard ID is a 4-byte hash
            keyboard_id = struct.unpack("<I", data[19:23])[0]

            modifier_flags = ModifierFlags(data[23])
            wpm_value = data[24]
            channel = data[25]

            return cls(
                manufacturer_id=manufacturer_id,
                service_uuid=service_uuid,
                version=version,
                battery_level=battery_level,
                active_layer=active_layer,
                profile_slot=profile_slot,
                connection_count=connection_count,
                status_flags=status_flags,
                device_role=device_role,
                device_index=device_index,
                peripheral_batteries=peripheral_batteries,
                layer_name=layer_name,
                keyboard_id=keyboard_id,
                modifier_flags=modifier_flags,
                wpm_value=wpm_value,
                channel=channel,
                rssi=rssi,
                device_address=device_address,
                device_name=device_name,
            )
        except (struct.error, ValueError) as e:
            logger.debug(f"Failed to parse advertisement: {e}")
            return None

    @property
    def is_usb_connected(self) -> bool:
        """Check if the keyboard is connected via USB."""
        return bool(self.status_flags & StatusFlags.USB_CONNECTED)

    @property
    def is_usb_hid_ready(self) -> bool:
        """Check if USB HID is ready."""
        return bool(self.status_flags & StatusFlags.USB_HID_READY)

    @property
    def is_ble_connected(self) -> bool:
        """Check if the keyboard is connected via BLE."""
        return bool(self.status_flags & StatusFlags.BLE_CONNECTED)

    @property
    def is_charging(self) -> bool:
        """Check if the keyboard is charging."""
        return bool(self.status_flags & StatusFlags.CHARGING)

    @property
    def is_caps_word(self) -> bool:
        """Check if caps word mode is active."""
        return bool(self.status_flags & StatusFlags.CAPS_WORD)

    @property
    def has_left_ctrl(self) -> bool:
        """Check if left control is pressed."""
        return bool(self.modifier_flags & ModifierFlags.LCTL)

    @property
    def has_left_shift(self) -> bool:
        """Check if left shift is pressed."""
        return bool(self.modifier_flags & ModifierFlags.LSFT)

    @property
    def has_left_alt(self) -> bool:
        """Check if left alt is pressed."""
        return bool(self.modifier_flags & ModifierFlags.LALT)

    @property
    def has_left_gui(self) -> bool:
        """Check if left GUI (Win/Cmd) is pressed."""
        return bool(self.modifier_flags & ModifierFlags.LGUI)

    @property
    def has_right_ctrl(self) -> bool:
        """Check if right control is pressed."""
        return bool(self.modifier_flags & ModifierFlags.RCTL)

    @property
    def has_right_shift(self) -> bool:
        """Check if right shift is pressed."""
        return bool(self.modifier_flags & ModifierFlags.RSFT)

    @property
    def has_right_alt(self) -> bool:
        """Check if right alt is pressed."""
        return bool(self.modifier_flags & ModifierFlags.RALT)

    @property
    def has_right_gui(self) -> bool:
        """Check if right GUI (Win/Cmd) is pressed."""
        return bool(self.modifier_flags & ModifierFlags.RGUI)

    @property
    def active_modifiers(self) -> list[str]:
        """Get list of currently active modifier names."""
        modifiers = []
        if self.has_left_ctrl:
            modifiers.append("LCtrl")
        if self.has_right_ctrl:
            modifiers.append("RCtrl")
        if self.has_left_shift:
            modifiers.append("LShift")
        if self.has_right_shift:
            modifiers.append("RShift")
        if self.has_left_alt:
            modifiers.append("LAlt")
        if self.has_right_alt:
            modifiers.append("RAlt")
        if self.has_left_gui:
            modifiers.append("LGUI")
        if self.has_right_gui:
            modifiers.append("RGUI")
        return modifiers


@dataclass
class ZMKDevice:
    """Represents a discovered ZMK keyboard device."""

    address: str
    name: str
    keyboard_id: int
    last_advertisement: ZMKStatusAdvertisement | None = None
    last_seen: float = 0.0  # Unix timestamp


# Type alias for the callback
StatusCallback = Callable[[ZMKStatusAdvertisement], None]


@dataclass
class ZMKScanner:
    """
    BLE scanner for ZMK keyboards with Prospector status advertisement.

    This class provides an async interface for scanning and receiving
    status updates from ZMK keyboards.

    Example:
        async def on_status(status: ZMKStatusAdvertisement):
            print(f"Layer: {status.active_layer}, Battery: {status.battery_level}%")

        scanner = ZMKScanner()
        scanner.add_callback(on_status)
        await scanner.start()
        # ... later ...
        await scanner.stop()
    """

    _scanner: BleakScanner | None = field(default=None, init=False, repr=False)
    _devices: dict[str, ZMKDevice] = field(default_factory=dict, init=False)
    _callbacks: list[StatusCallback] = field(default_factory=list, init=False)
    _running: bool = field(default=False, init=False)
    _scan_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    def add_callback(self, callback: StatusCallback) -> None:
        """
        Register a callback to receive status updates.

        Args:
            callback: Function to call when a new status advertisement is received
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: StatusCallback) -> None:
        """
        Unregister a status callback.

        Args:
            callback: The callback to remove
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _detection_callback(self, device: BLEDevice, advertisement_data: AdvertisementData) -> None:
        """Internal callback for BLE advertisement detection."""
        # Check for manufacturer data with our manufacturer ID
        manufacturer_data = advertisement_data.manufacturer_data.get(MANUFACTURER_ID)
        if manufacturer_data is None:
            return

        # Try to parse the advertisement
        status = ZMKStatusAdvertisement.from_manufacturer_data(
            data=manufacturer_data,
            rssi=advertisement_data.rssi if advertisement_data.rssi else 0,
            device_address=device.address,
            device_name=advertisement_data.local_name or device.name or "",
        )

        if status is None:
            return

        # Update or create device entry
        import time

        now = time.time()

        if device.address not in self._devices:
            self._devices[device.address] = ZMKDevice(
                address=device.address,
                name=status.device_name,
                keyboard_id=status.keyboard_id,
            )
            logger.info(f"Discovered new ZMK device: {status.device_name} ({device.address})")

        zmk_device = self._devices[device.address]
        zmk_device.last_advertisement = status
        zmk_device.last_seen = now

        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(status)
            except Exception as e:
                logger.error(f"Error in status callback: {e}")

    async def start(self) -> None:
        """
        Start scanning for ZMK devices.

        This will begin listening for BLE advertisements from ZMK keyboards.
        Discovered devices and their status updates will be provided via
        registered callbacks.
        """
        if self._running:
            logger.warning("Scanner is already running")
            return

        logger.info("Starting ZMK BLE scanner...")
        self._running = True

        # Create scanner with detection callback
        self._scanner = BleakScanner(detection_callback=self._detection_callback)

        try:
            await self._scanner.start()
            logger.info("ZMK BLE scanner started successfully")
        except Exception as e:
            self._running = False
            self._scanner = None
            logger.error(f"Failed to start BLE scanner: {e}")
            raise

    async def stop(self) -> None:
        """
        Stop scanning for ZMK devices.

        This will stop the BLE scanner. Registered callbacks will no longer
        receive updates until start() is called again.
        """
        if not self._running:
            return

        logger.info("Stopping ZMK BLE scanner...")
        self._running = False

        if self._scanner:
            try:
                await self._scanner.stop()
            except Exception as e:
                logger.error(f"Error stopping scanner: {e}")
            finally:
                self._scanner = None

        logger.info("ZMK BLE scanner stopped")

    @property
    def is_running(self) -> bool:
        """Check if the scanner is currently running."""
        return self._running

    def get_devices(self) -> list[ZMKDevice]:
        """
        Get list of all discovered ZMK devices.

        Returns:
            List of ZMKDevice objects for all discovered keyboards
        """
        return list(self._devices.values())

    def get_device(self, address: str) -> ZMKDevice | None:
        """
        Get a specific device by its BLE address.

        Args:
            address: The BLE address of the device

        Returns:
            The ZMKDevice if found, None otherwise
        """
        return self._devices.get(address)

    def get_device_by_name(self, name: str) -> ZMKDevice | None:
        """
        Get a specific device by its name.

        Args:
            name: The name of the device

        Returns:
            The first ZMKDevice with a matching name, or None
        """
        for device in self._devices.values():
            if device.name == name:
                return device
        return None

    def get_latest_status(self, address: str) -> ZMKStatusAdvertisement | None:
        """
        Get the latest status advertisement for a device.

        Args:
            address: The BLE address of the device

        Returns:
            The latest ZMKStatusAdvertisement or None if not available
        """
        device = self._devices.get(address)
        return device.last_advertisement if device else None

    def clear_devices(self) -> None:
        """Clear all discovered devices."""
        self._devices.clear()


# Convenience functions for simple usage


async def scan_for_devices(timeout: float = 5.0) -> list[ZMKDevice]:
    """
    Scan for ZMK devices for a specified duration.

    This is a convenience function for one-shot scanning.

    Args:
        timeout: How long to scan in seconds

    Returns:
        List of discovered ZMKDevice objects
    """
    scanner = ZMKScanner()
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    return scanner.get_devices()


async def get_first_device(timeout: float = 10.0) -> ZMKDevice | None:
    """
    Scan until the first ZMK device is found or timeout.

    Args:
        timeout: Maximum time to wait in seconds

    Returns:
        The first discovered ZMKDevice or None if timeout
    """
    scanner = ZMKScanner()
    found_event = asyncio.Event()
    found_device: list[ZMKDevice] = []

    def on_status(status: ZMKStatusAdvertisement) -> None:
        if not found_device:
            device = scanner.get_device(status.device_address)
            if device:
                found_device.append(device)
                found_event.set()

    scanner.add_callback(on_status)

    try:
        await scanner.start()
        try:
            await asyncio.wait_for(found_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
    finally:
        await scanner.stop()

    return found_device[0] if found_device else None