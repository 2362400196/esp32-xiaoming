# -*- coding: utf-8 -*-
"""COM3 串口日志抓取：写到 device_serial.log，带接收时间戳。"""
import serial, sys, time
PORT, BAUD = 'COM3', 115200
OUT = r'C:\Users\23624\Desktop\esp32-xiaoming\device_serial.log'
ser = serial.Serial(PORT, BAUD, timeout=1)
tsvc = time.strftime('%Y-%m-%d %H:%M:%S')
with open(OUT, 'a', encoding='utf-8', errors='replace') as f:
    f.write(f'\n===== capture start {tsvc} =====\n')
    f.flush()
    buf = b''
    while True:
        data = ser.read(4096)
        if data:
            buf += data
            *lines, buf = buf.split(b'\n')
            now = time.strftime('%H:%M:%S')
            for ln in lines:
                try:
                    text = ln.decode('utf-8', 'replace').rstrip('\r')
                except Exception:
                    text = repr(ln)
                f.write(f'[{now}] {text}\n')
            f.flush()
