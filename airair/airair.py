#!/usr/bin/env python

from __future__ import print_function

import datetime
import os
import sys

import btle


VERBOSE = False
TIMESTAMP = True

AIRAIR_MAC_ADDR = "20:CD:39:7B:F3:38"
AIRAIR_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
AIRAIR_CHARACTERISTIC_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
AIRAIR_HANDLE = 0x11

CCCD_UUID = 0x2902

# data fields
DATA_HEADER            = 0  # Header, 0xFF, Constant
DATA_PROTOCOL_VERSION  = 1  # Protocol, 0x01, Version 1
DATA_HARDWARE_VERSION  = 2  # Hardware, 0x01, Version 1
DATA_INFO_TYPE         = 3  # Info, 0xA1, data from Air.Air!
DATA_DENSITY_V_H       = 4  # Data0, 0x**, high byte of V_out
DATA_DENSITY_V_L       = 5  # Data1, 0x**, low byte of V_out
DATA_TEMPERATURE       = 6  # Data2, 0x**, Degrees Celsius, (Data2 - 0x20)
DATA_BATTERY_VOLTAGE   = 7  # Data3, [0x00-0x05], 0=5%, 1=20%, 2=40%, 3=60%, 4=80%, 5=100%
DATA_V_OC              = 8  # Data4, 0x44, (BYTE8 / 255), calibration constant
DATA_K_VALUE           = 9  # Data5, 0x3D, (BYTE9 / 255), calibration constant
DATA_SAMPLING_INTERVAL = 10 # Data6, 0x**, notify interval, used when plotting values
DATA_RESERVED0         = 11 # Data7, 0x00, Constant
DATA_RESERVED1         = 12 # Data8, 0x00, Constant
DATA_RESERVED2         = 13 # Data9, 0x00, Constant
DATA_RESERVED3         = 14 # Data10, 0x00, Constant
DATA_CHECKSUM          = 15 # Checksum, 0x**, (0xFF & (BYTE0 + ... + BYTE14))

# data field constants
AIR_HEADER = 0xFF
AIR_PROTOCOL = 0x01
AIR_HARDWARE = 0x01
AIR_INFO = 0xA1
AIR_TEMP_OFFSET = 0x20
#AIR_V_OC = 0x44
#AIR_K_VALUE = 0x3D

# data packet values
AIR_PKT_VALS = [
    (AIR_HEADER, True),
    (AIR_PROTOCOL, True),
    (AIR_HARDWARE, True),
    (AIR_INFO, True),
    (0x00, False),
    (0x00, False),
    (0x00, False),
    (0x00, False),
    (0x00, False),
    (0x00, False),
    (0x00, False),
    (0x00, True),
    (0x00, True),
    (0x00, True),
    (0x00, True),
    (0x00, False)]


# last sampled battery value
battery = None

# last sampled temperature value
temperature = None

# last sampled quality value
quality = None


def getQuality(vals):
    '''
    V_out = 3.3*((BYTE4 << 5) | BYTE5)/1024
    V_oc = Output Voltage when no dust detected
    Dust Concentration: ((V_out - V_oc) * 100) / K
    (0.1 mg/m^3)
    '''
    v_out = (3.3 * ((vals[DATA_DENSITY_V_H] << 5) | vals[DATA_DENSITY_V_L])) / 1024.0
    v_oc = vals[DATA_V_OC] / 255.0
    kVal = vals[DATA_K_VALUE] / 255.0
    quality = (v_out - v_oc) * 100.0 / kVal
    if False:
        print("VALS:", vals)
        print("V_H:", vals[DATA_DENSITY_V_H], ", V_L:", vals[DATA_DENSITY_V_L])
        print("V_HL:", ((vals[DATA_DENSITY_V_H] << 5) | vals[DATA_DENSITY_V_L]))
        print("VOUT:", v_out, ", VOC:", v_oc, ", V_D:", v_out - v_oc)
        print("K_VALUE:", kVal)
        print("QUALITY:", quality)
        print("\n")
    return quality


class MyDelegate(btle.DefaultDelegate):
    def __init__(self):
        btle.DefaultDelegate.__init__(self)
        self.dataBuf = []

    def handleNotification(self, hnd, data):
        #### TODO figure out how to do this without globals
        global battery
        global temperature
        global quality

        numVals = len(data)
        self.dataBuf += [ord(d) for d in data]
        dataLen = len(self.dataBuf)

        if dataLen >= 16:
            # got a full packet, so extract and process it
            vals = self.dataBuf[:16]
            self.dataBuf = self.dataBuf[16:]
        else:
            # partial packet, assemble more packets
            ##sys.stderr.write("Warning: partial packet\n")
            return

        i = 0
        for datum, (val, mask) in zip(vals, AIR_PKT_VALS):
            if mask and datum != val:
                sys.stderr.write("Error: invalid value in field {0} ({1} != {2})\n".format(i, datum, val))
                return
            i += 1
        if VERBOSE:
            print("Data:", [hex(v) for v in vals])
        battery = vals[DATA_BATTERY_VOLTAGE]
        temperature = vals[DATA_TEMPERATURE] - AIR_TEMP_OFFSET
        quality = getQuality(vals)
        if VERBOSE:
            print("Battery: {0}; Temp: {1}; Quality: {2}".format(battery, temperature, quality))
        if TIMESTAMP:
            time = datetime.datetime.now().isoformat()
            print(time, battery, temperature, quality)
        else:
            print(battery, temperature, quality)
        sys.stdout.flush()


if __name__ == '__main__':
    script_path = os.path.join(os.path.abspath(os.path.dirname(__file__)))
    helperExe = os.path.join(script_path, "bluepy-helper")
    if not os.path.isfile(helperExe):
        raise ImportError("Cannot find required executable '%s'" % helperExe)

    devAddr = AIRAIR_MAC_ADDR
    addrType = "public"
    if VERBOSE:
        print("Connecting to: {}, address type: {}".format(devAddr, addrType))
    conn = btle.Peripheral(devAddr, addrType)
    delegate = MyDelegate()
    conn.setDelegate(delegate)
    try:
        svc = conn.getServiceByUUID(AIRAIR_SERVICE_UUID)
        if VERBOSE:
            print(str(svc))
        ch = svc.getCharacteristics(AIRAIR_CHARACTERISTIC_UUID)[0]
        if VERBOSE:
            print("    {}, hnd={}, supports {}".format(ch, hex(ch.handle), ch.propertiesToString()))
        cccd = ch.getDescriptors(forUUID=CCCD_UUID)[0]
        cccd.write(b"\x01\x00", True)
        while True:
            r = conn.waitForNotifications(2.0)
            if not r:
                sys.stderr.write("Warning: Notification timeout\n")
    finally:
        conn.disconnect()
