# For Developers: Cracking the OnePlus/BBK BLE Protocol

If you are trying to write a client for OnePlus, Oppo, Realme, or other BBK ecosystem earbuds (like the Nord Buds 3 Pro), this document contains everything we learned while reverse-engineering the proprietary OPO Bluetooth Low Energy (BLE) protocol.

## 1. Connection Architecture (The "Ghost Device" Trap)

The most common trap when building a desktop client is trying to scan for the earbuds' BLE advertisements (which rotate MAC addresses) and connecting directly to that BLE MAC. 

**What happens if you do that:**
You successfully connect, but you create a *duplicate* "Miscellaneous" Bluetooth device in the OS. Worse, the earbuds **will not send any `[RX]` notifications** over this secondary connection.

**The Solution:**
The earbuds expect BLE GATT commands to be sent *over the existing Classic Bluetooth connection*. You must find the MAC address of the paired "Headset" (e.g., via `bluetoothctl devices Paired`) and pass *that* MAC address to `BleakClient`. 

## 2. Service and Characteristics

The earbuds use the proprietary **OPO Protocol Service**:
- **Service UUID:** `0000079A-D102-11E1-9B23-00025B00A5A5`
- **Command (Write) Char:** `0100079A-D102-11E1-9B23-00025B00A5A5` (Write Without Response)
- **Notify (Response) Char:** `0200079A-D102-11E1-9B23-00025B00A5A5`

**Crucial Notes on Subscriptions:**
1. **The Trap Characteristic:** Do **NOT** blindly subscribe to all characteristics. Subscribing to `0100079c-d102-11e1-9b23-00025b00a5a5` triggers a GATT "Unlikely Error" and immediately crashes the connection.
2. **The Missing Responses:** Sometimes the earbuds route their notifications through a completely different service. You should subscribe to **both** `0200079a...` AND the alternate channel `fe2c123a-8366-4814-8eb0-01de32100bea` to ensure you receive responses.

## 3. The Authentication Handshake

You cannot just connect and send an ANC command. The earbuds will silently ignore you. You must establish an authenticated session first, with strict timing delays.

1. Connect to the device and subscribe to notifications.
2. **Wait ~2.0 seconds** for BlueZ/GATT to settle.
3. **Send HELLO:** `[0xAA, 0x07, 0x00, 0x00, 0x00, 0x01, 0x23, 0x00, 0x00, 0x12]`
4. **Wait ~2.0 seconds** for the device to initialize the session.
5. **Send REGISTER:** `[0xAA, 0x0C, 0x00, 0x00, 0x00, 0x85, 0x41, 0x05, 0x00, 0x00, 0xB5, 0x50, 0xA0, 0x69]`
    * *(Note: `B5 50 A0 69` is a magic device token that acts as the authenticator)*
6. **Wait ~1.5 seconds**.
7. You are now authenticated and can send commands.

## 4. OPO Packet Structure

All commands and responses follow this exact byte format:

| Byte Offset | Field | Description |
| :--- | :--- | :--- |
| `0` | **SOF** | Start of Frame. Always `0xAA`. |
| `1` | **LEN** | Length of the packet starting from byte 4 (CAT) to the end. |
| `2-3` | **PAD** | Padding. Always `0x00 0x00`. |
| `4` | **CAT** | Category (`0x00`=System, `0x03`=Info, `0x04`=ANC, `0x05`=EQ, `0x06`=Battery) |
| `5` | **SUB** | Sub-command (`0x01`=Query, `0x04`=Set, `0x81`/`0x84`=Responses) |
| `6` | **SEQ** | Sequence number (increments to match requests/responses). |
| `7+` | **DATA** | Variable length payload. |

*(Note: There is no CRC/Checksum byte at the end. The length byte determines the boundary).*

## 5. Useful Commands

**Toggle ANC Modes:**
Send: `[0xAA, 0x0A, 0x00, 0x00, 0x04, 0x04, 0x42, 0x03, 0x00, 0x01, 0x01, MODE]`
* `MODE = 0x01`: ANC On
* `MODE = 0x02`: Transparency
* `MODE = 0x04`: ANC Off (Normal)

**Query Battery:**
Send: `[0xAA, 0x07, 0x00, 0x00, 0x06, 0x01, 0x25, 0x00, 0x00]`

**Query ANC Status:**
Send: `[0xAA, 0x07, 0x00, 0x00, 0x04, 0x04, 0x2A, 0x00, 0x00]`

## 6. Parsing Battery Responses

When the earbuds reply to a battery query, they send a packet where `CAT = 0x06` and `SUB = 0x81`.
The byte offsets for the battery percentages vary depending on the packet length:

* **If Length >= 16 bytes:**
  * Left Bud: `byte[12]`
  * Right Bud: `byte[14]`
  * Case: `byte[16]`
* **If Length >= 11 bytes (Shorter payload):**
  * Left Bud: `byte[8]`
  * Right Bud: `byte[9]`
  * Case: `byte[10]`

All values are standard integers from `0` to `100`. If you get a value > 100, you are reading the wrong byte offset.

## 7. Development Tips & Troubleshooting

1. **Write Type:** Always use **Write Without Response** (`response=False` in Bleak). The command characteristic does not support ATT acknowledgements. If you try to write *with* response, CoreBluetooth/BlueZ will hang or silently fail.
2. **The "HeyMelody" Block:** The earbuds can only maintain one active control session. If the official HeyMelody app is open on an attached phone, it will monopolize the notification channel, and your desktop app will receive 0 bytes in response. Tell users to disconnect the phone app first.
3. **Read Fallback:** If you're struggling with unstable notification delivery on Linux, you can occasionally call a direct GATT `Read` on the notification characteristic immediately after sending a query. Sometimes the data is sitting on the characteristic but the notification trigger dropped.
