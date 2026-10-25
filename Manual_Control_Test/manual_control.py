#!/usr/bin/env python3
"""Windows laptop controller. Keys: W/S drive, A/D turn, E/C speed, P pump,
[ / ] servo angle, Space stop, Q quit."""
import ctypes
import json
import socket
import time
import cv2

PI_IP = "10.244.175.134"  # Change this to the Pi's current IP
UDP_PORT = 5005
STREAM_URL = f"http://{PI_IP}:5000/stream"

speed = 0.40
MIN_SPEED, MAX_SPEED, SPEED_STEP = 0.15, 1.00, 0.05
TURN_SCALE = 0.75
servo_angle = 90
pump_on = False

VK = {"A":0x41, "C":0x43, "D":0x44, "E":0x45, "P":0x50,
      "Q":0x51, "S":0x53, "W":0x57, "SPACE":0x20,
      "LEFT_BRACKET":0xDB, "RIGHT_BRACKET":0xDD}
user32 = ctypes.windll.user32
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def key_down(name):
    return bool(user32.GetAsyncKeyState(VK[name]) & 0x8000)


def send(payload):
    sock.sendto(json.dumps(payload).encode("utf-8"), (PI_IP, UDP_PORT))


def main():
    global speed, servo_angle, pump_on
    print("W/S drive | A/D turn | E speed up | C speed down | P pump toggle")
    print("[ / ] servo | Space stop | Q quit")
    cap = cv2.VideoCapture(STREAM_URL)
    last = {k: False for k in ("E", "C", "P", "LEFT_BRACKET", "RIGHT_BRACKET")}

    try:
        while True:
            ok, frame = cap.read()
            if ok:
                cv2.imshow("Rover Camera", frame)

            now = {k: key_down(k) for k in last}
            if now["E"] and not last["E"]:
                speed = min(MAX_SPEED, round(speed + SPEED_STEP, 2))
                print(f"Speed: {speed:.2f} ({speed*100:.0f}%)")
            if now["C"] and not last["C"]:
                speed = max(MIN_SPEED, round(speed - SPEED_STEP, 2))
                print(f"Speed: {speed:.2f} ({speed*100:.0f}%)")
            if now["P"] and not last["P"]:
                pump_on = not pump_on
                send({"type":"pump", "state":pump_on})
                print("Pump ON" if pump_on else "Pump OFF")
            if now["LEFT_BRACKET"] and not last["LEFT_BRACKET"]:
                servo_angle = max(0, servo_angle - 5)
                send({"type":"servo", "angle":servo_angle})
                print(f"Servo: {servo_angle}")
            if now["RIGHT_BRACKET"] and not last["RIGHT_BRACKET"]:
                servo_angle = min(180, servo_angle + 5)
                send({"type":"servo", "angle":servo_angle})
                print(f"Servo: {servo_angle}")
            last = now

            if key_down("SPACE"):
                send({"type":"stop"})
                left = right = 0
            else:
                throttle = (1 if key_down("W") else 0) - (1 if key_down("S") else 0)
                steer = (1 if key_down("D") else 0) - (1 if key_down("A") else 0)
                left = max(-1, min(1, throttle * speed - steer * speed * TURN_SCALE))
                right = max(-1, min(1, throttle * speed + steer * speed * TURN_SCALE))
                send({"type":"drive", "left":left, "right":right})

            if key_down("Q") or (cv2.waitKey(1) & 0xFF == ord("q")):
                break
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            send({"type":"stop"})
            send({"type":"pump", "state":False})
        except Exception:
            pass
        cap.release()
        cv2.destroyAllWindows()
        sock.close()


if __name__ == "__main__":
    main()
