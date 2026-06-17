import asyncio
import logging
from bleak import BleakScanner, BleakClient

# UUIDs
CMD_CHAR = "0100079a-d102-11e1-9b23-00025b00a5a5"
NOTIFY_CHAR = "0200079a-d102-11e1-9b23-00025b00a5a5"
FE2C_NOTIFY = "fe2c123a-8366-4814-8eb0-01de32100bea"
# Skip 0100079c — subscribing to it crashes the connection
SKIP_CHARS = {"0100079c-d102-11e1-9b23-00025b00a5a5"}

MAX_RECONNECT_ATTEMPTS = 5

# Commands
HELLO_CMD = [0xAA, 0x07, 0x00, 0x00, 0x00, 0x01, 0x23, 0x00, 0x00, 0x12]
REGISTER_CMD = [0xAA, 0x0C, 0x00, 0x00, 0x00, 0x85, 0x41, 0x05, 0x00, 0x00, 0xB5, 0x50, 0xA0, 0x69]
BATTERY_QUERY = [0xAA, 0x07, 0x00, 0x00, 0x06, 0x01, 0x25, 0x00, 0x00]
INFO_QUERY = [0xAA, 0x07, 0x00, 0x00, 0x03, 0x01, 0x28, 0x00, 0x00]
ANC_QUERY = [0xAA, 0x07, 0x00, 0x00, 0x04, 0x04, 0x2A, 0x00, 0x00]

logger = logging.getLogger("OpoBleController")


class OpoBleController:
    def __init__(self):
        self.client = None
        self.device = None
        self.is_connected = False
        self.authenticated = False
        self.cmd_char = None
        self.notify_char = None
        self.intentional_disconnect = False
        self._reconnecting = False
        self._reconnect_attempts = 0
        self._battery_poll_task = None

        # State
        self.battery_left = 0
        self.battery_right = 0
        self.battery_case = 0

        # Callbacks
        self.on_state_changed = None
        self.on_battery_updated = None

    async def scan_and_connect(self):
        self.intentional_disconnect = False
        self.cmd_char = None
        self.notify_char = None
        logger.info("Scanning for OnePlus/Nord devices...")

        try:
            devices = await BleakScanner.discover()
        except Exception as e:
            logger.error(f"Scan failed: {e}")
            if self.on_state_changed:
                self.on_state_changed("disconnected")
            return False

        target_device = None
        for d in devices:
            if d.name and ("Nord Buds" in d.name or "OnePlus" in d.name):
                target_device = d
                break

        if not target_device:
            logger.error("No compatible device found.")
            if self.on_state_changed:
                self.on_state_changed("disconnected")
            return False

        logger.info(f"Found device: {target_device.name} [{target_device.address}]")
        self.device = target_device
        self.client = BleakClient(
            target_device.address,
            disconnected_callback=self._handle_disconnect,
        )

        try:
            await self.client.connect()
            self.is_connected = True
            self._reconnect_attempts = 0
            logger.info("Connected to device.")

            # Subscribe to all notifiable chars EXCEPT the known-bad one
            for service in self.client.services:
                for char in service.characteristics:
                    if char.uuid.lower() == CMD_CHAR:
                        self.cmd_char = char
                        logger.info(f"  CMD: {char.uuid}")

                    if char.uuid.lower() == NOTIFY_CHAR:
                        self.notify_char = char

                    if char.uuid.lower() in SKIP_CHARS:
                        logger.info(f"  SKIP: {char.uuid} (known to crash)")
                        continue

                    if "notify" in char.properties:
                        try:
                            await self.client.start_notify(char, self._notification_handler)
                            logger.info(f"  SUB: {char.uuid}")
                        except Exception as e:
                            logger.warning(f"  FAIL: {char.uuid}: {e}")

            if not self.cmd_char:
                logger.error("CRITICAL: Command characteristic not found!")
                return False

            asyncio.create_task(self._authenticate())
            return True

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.is_connected = False
            if self.on_state_changed:
                self.on_state_changed("disconnected")
            return False

    async def _auto_reconnect(self):
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            self._reconnect_attempts += 1
            if self._reconnect_attempts > MAX_RECONNECT_ATTEMPTS:
                logger.error(f"Max reconnect attempts ({MAX_RECONNECT_ATTEMPTS}) reached. Giving up.")
                return
            delay = min(5 * self._reconnect_attempts, 15)
            logger.info(f"Auto-reconnect attempt {self._reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS} in {delay}s...")
            await asyncio.sleep(delay)
            if not self.is_connected and not self.intentional_disconnect:
                if self.on_state_changed:
                    self.on_state_changed("connecting")
                await self.scan_and_connect()
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
        finally:
            self._reconnecting = False

    def _handle_disconnect(self, client):
        logger.warning("Device disconnected.")
        self.is_connected = False
        self.authenticated = False
        if self._battery_poll_task:
            self._battery_poll_task.cancel()
            self._battery_poll_task = None
        if self.on_state_changed:
            self.on_state_changed("disconnected")

        if not self.intentional_disconnect:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._auto_reconnect())
            except RuntimeError:
                pass

    def _notification_handler(self, sender, data: bytearray):
        hex_data = " ".join([f"{b:02X}" for b in data])
        logger.info(f"[RX] ({len(data)}b) from {sender}: {hex_data}")

        if len(data) < 3:
            return

        if len(data) >= 10 and data[4] == 0x06 and data[5] == 0x81:
            self._parse_battery(data)
        elif len(data) >= 10 and data[4] == 0x04 and data[5] == 0x84:
            self._parse_anc(data)
        elif data[2] == 0x81:
            logger.info("Registration acknowledged.")

    def _parse_battery(self, data):
        logger.info(f"Battery Packet ({len(data)}b): {data.hex()}")
        # Log every byte for debugging
        for i, b in enumerate(data):
            logger.info(f"  byte[{i}] = 0x{b:02X} ({b})")
        try:
            # OPO battery response format:
            # Bytes 0-3: header (AA LEN 00 00)
            # Byte 4: CAT (0x06 = battery)
            # Byte 5: SUB (0x81 = response)
            # Byte 6: SEQ
            # Byte 7+: data payload with battery values
            #
            # From HeyMelody decompilation, battery values appear at:
            #   Left bud:  look for values 0-100 in bytes 8-15
            #   Right bud: next position
            #   Case: next position
            if len(data) >= 16:
                self.battery_left = data[12]
                self.battery_right = data[14]
                self.battery_case = data[16] if len(data) > 16 else 0
            elif len(data) >= 11:
                self.battery_left = data[8]
                self.battery_right = data[9]
                self.battery_case = data[10]

            # Sanity-check: values should be 0-100
            for attr in ('battery_left', 'battery_right', 'battery_case'):
                val = getattr(self, attr)
                if val > 100:
                    logger.warning(f"{attr} = {val} (>100, likely wrong offset)")
                    setattr(self, attr, 0)

            logger.info(f"Battery -> L:{self.battery_left}% R:{self.battery_right}% C:{self.battery_case}%")
            if self.on_battery_updated:
                self.on_battery_updated(self.battery_left, self.battery_right, self.battery_case)
        except Exception as e:
            logger.error(f"Failed to parse battery: {e}")

    def _parse_anc(self, data):
        if len(data) >= 10:
            mode = data[9]
            logger.info(f"ANC Mode -> {mode}")
            if self.on_state_changed:
                self.on_state_changed(f"anc:{mode}")

    async def _send_command(self, cmd_bytes):
        if not self.is_connected or not self.cmd_char:
            return False
        hex_data = " ".join([f"{b:02X}" for b in cmd_bytes])
        logger.info(f"[TX] {hex_data}")
        try:
            await self.client.write_gatt_char(self.cmd_char, bytes(cmd_bytes), response=False)
            return True
        except Exception as e:
            err = str(e)
            logger.error(f"Write failed: {err}")
            if "UnknownObject" in err or "Not connected" in err or "DBus" in err:
                self._handle_disconnect(self.client)
            return False

    async def _try_read_notify(self):
        """Try to directly read the notify characteristic as a fallback."""
        if not self.notify_char or not self.is_connected:
            return
        try:
            data = await self.client.read_gatt_char(self.notify_char)
            if data and len(data) > 0:
                hex_data = " ".join([f"{b:02X}" for b in data])
                logger.info(f"[READ] ({len(data)}b): {hex_data}")
                self._notification_handler(self.notify_char, bytearray(data))
            else:
                logger.info("[READ] Empty response from notify char")
        except Exception as e:
            logger.warning(f"[READ] Failed: {e}")

    async def _authenticate(self):
        logger.info("Waiting 2s for BlueZ GATT to settle...")
        await asyncio.sleep(2.0)
        if not self.is_connected:
            return

        logger.info("Sending HELLO...")
        if not await self._send_command(HELLO_CMD):
            return

        await asyncio.sleep(2.0)
        if not self.is_connected:
            return

        logger.info("Sending REGISTER...")
        if not await self._send_command(REGISTER_CMD):
            return

        await asyncio.sleep(1.5)
        if not self.is_connected:
            return

        self.authenticated = True
        logger.info("Authenticated.")

        if self.on_state_changed:
            self.on_state_changed("connected")

        # Query initial state
        await self._send_command(INFO_QUERY)
        await asyncio.sleep(0.5)
        if not self.is_connected:
            return

        await self._send_command(BATTERY_QUERY)
        await asyncio.sleep(1.0)
        # Try reading the response directly if notifications aren't working
        await self._try_read_notify()
        if not self.is_connected:
            return

        await self._send_command(ANC_QUERY)
        await asyncio.sleep(1.0)
        await self._try_read_notify()

        # Start periodic battery polling
        self._battery_poll_task = asyncio.create_task(self._battery_poll_loop())

    async def _battery_poll_loop(self):
        """Poll battery every 60s."""
        try:
            while self.is_connected and self.authenticated:
                await asyncio.sleep(60)
                if self.is_connected and self.authenticated:
                    await self._send_command(BATTERY_QUERY)
                    await asyncio.sleep(1.0)
                    await self._try_read_notify()
        except asyncio.CancelledError:
            pass

    async def set_anc_mode(self, mode_hex: int):
        if not self.authenticated:
            logger.error("Not authenticated yet.")
            return
        cmd = [0xAA, 0x0A, 0x00, 0x00, 0x04, 0x04, 0x42, 0x03, 0x00, 0x01, 0x01, mode_hex]
        logger.info(f"Setting ANC mode to {mode_hex}")
        await self._send_command(cmd)

    async def disconnect(self):
        self.intentional_disconnect = True
        if self._battery_poll_task:
            self._battery_poll_task.cancel()
            self._battery_poll_task = None
        if self.client and self.is_connected:
            await self.client.disconnect()
