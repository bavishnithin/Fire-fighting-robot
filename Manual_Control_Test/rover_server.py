#!/usr/bin/env python3
import cv2
import json
import socket
import threading
import time
from flask import Flask, Response
import RPi.GPIO as GPIO

HTTP_PORT = 5000
UDP_PORT = 5005
CAMERA_INDEX = 0

# BCM pin numbering
IN1, IN2, IN3, IN4 = 25, 27, 22, 23
ENA, ENB = 12, 13
SERVO_PIN = 18
RELAY_PIN = 16

PWM_FREQUENCY = 1000
DEFAULT_SPEED = 0.40

app = Flask(__name__)
camera = None
state_lock = threading.Lock()
current_angle = 90
pump_is_on = False
left_pwm = right_pwm = servo_pwm = None


# Exact relay syntax confirmed working in your test:
def relay_on():
    global pump_is_on
    GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)
    pump_is_on = True
    print("Pump ON")


def relay_off():
    global pump_is_on
    GPIO.setup(RELAY_PIN, GPIO.IN)
    pump_is_on = False
    print("Pump OFF")


def set_motor_speeds(left, right):
    left = max(-1.0, min(1.0, float(left)))
    right = max(-1.0, min(1.0, float(right)))

    if left > 0:
        GPIO.output(IN1, GPIO.HIGH); GPIO.output(IN2, GPIO.LOW)
    elif left < 0:
        GPIO.output(IN1, GPIO.LOW); GPIO.output(IN2, GPIO.HIGH)
    else:
        GPIO.output(IN1, GPIO.LOW); GPIO.output(IN2, GPIO.LOW)

    if right > 0:
        GPIO.output(IN3, GPIO.HIGH); GPIO.output(IN4, GPIO.LOW)
    elif right < 0:
        GPIO.output(IN3, GPIO.LOW); GPIO.output(IN4, GPIO.HIGH)
    else:
        GPIO.output(IN3, GPIO.LOW); GPIO.output(IN4, GPIO.LOW)

    left_pwm.ChangeDutyCycle(abs(left) * 100)
    right_pwm.ChangeDutyCycle(abs(right) * 100)


def stop_motors():
    set_motor_speeds(0, 0)


def set_servo_angle(angle):
    global current_angle
    angle = max(0, min(180, int(angle)))
    duty = 2.5 + (angle / 180.0) * 10.0
    servo_pwm.ChangeDutyCycle(duty)
    time.sleep(0.25)
    servo_pwm.ChangeDutyCycle(0)
    current_angle = angle
    print(f"Servo angle: {angle}")


def setup_gpio():
    global left_pwm, right_pwm, servo_pwm
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup([IN1, IN2, IN3, IN4], GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup([ENA, ENB], GPIO.OUT, initial=GPIO.LOW)

    left_pwm = GPIO.PWM(ENA, PWM_FREQUENCY)
    right_pwm = GPIO.PWM(ENB, PWM_FREQUENCY)
    left_pwm.start(0)
    right_pwm.start(0)

    GPIO.setup(SERVO_PIN, GPIO.OUT)
    servo_pwm = GPIO.PWM(SERVO_PIN, 50)
    servo_pwm.start(0)

    relay_off()
    print("GPIO ready: ENA=GPIO12, ENB=GPIO13 PWM.")


def handle_command(command):
    global current_angle
    kind = command.get("type")
    with state_lock:
        if kind == "drive":
            set_motor_speeds(command.get("left", 0), command.get("right", 0))
        elif kind == "stop":
            stop_motors()
        elif kind == "pump":
            if bool(command.get("state", False)):
                relay_on()
            else:
                relay_off()
        elif kind == "pump_toggle":
            if pump_is_on:
                relay_off()
            else:
                relay_on()
        elif kind == "servo":
            set_servo_angle(command.get("angle", current_angle))


def udp_control_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"UDP control listening on port {UDP_PORT}")
    while True:
        data, _ = sock.recvfrom(2048)
        try:
            handle_command(json.loads(data.decode("utf-8")))
        except Exception as exc:
            print(f"Control command error: {exc}")


def frame_generator():
    global camera
    while True:
        if camera is None or not camera.isOpened():
            time.sleep(0.2)
            continue
        ok, frame = camera.read()
        if not ok:
            time.sleep(0.05)
            continue
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if ok:
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" +
                   encoded.tobytes() + b"\r\n")


@app.route("/")
def index():
    return "Rover server running. Camera: /stream"


@app.route("/stream")
def stream():
    return Response(frame_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


def main():
    global camera
    setup_gpio()
    camera = cv2.VideoCapture(CAMERA_INDEX)
    print("Camera opened." if camera.isOpened()
          else "WARNING: Camera not opened; try CAMERA_INDEX=1.")
    threading.Thread(target=udp_control_loop, daemon=True).start()
    print(f"Video: http://<PI_IP>:{HTTP_PORT}/stream")
    try:
        app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True, use_reloader=False)
    finally:
        try:
            stop_motors()
            relay_off()
            servo_pwm.stop()
            left_pwm.stop()
            right_pwm.stop()
        except Exception:
            pass
        if camera is not None:
            camera.release()
        GPIO.cleanup()


if __name__ == "__main__":
    main()
