#!/usr/bin/env python3
# ============================================================
# live_three_basler_preview.py
#
# Live view from three Basler cameras.
#
# Purpose:
#   - Confirm that all 3 cameras are detected.
#   - Assign each camera to left / center / right.
#   - Preview all three cameras at the same time.
#   - Check focus, field of view, IR illumination, overlap, and orientation.
#
# Install:
#   python3 -m pip install pypylon numpy opencv-python
#
# Run:
#   python3 live_three_basler_preview.py
#
# Stop live view:
#   - Press ENTER in the Terminal
#   - OR click a preview window and press q
#   - OR close any preview window
#
# Notes:
#   - This is for live view only.
#   - It uses GrabStrategy_LatestImageOnly, which is correct for preview.
#   - Do not use this strategy for final recording where every frame matters.
# ============================================================

import cv2
import threading
import time
from pypylon import pylon


def ask_float(prompt, default):
    while True:
        ans = input(f"{prompt} [{default}]: ").strip()
        if ans == "":
            return float(default)
        try:
            return float(ans)
        except ValueError:
            print("Please enter a number.")


def ask_int_or_none(prompt, default=None):
    if default is None:
        prompt_text = f"{prompt} [press ENTER for full/default]"
    else:
        prompt_text = f"{prompt} [{default}]"

    while True:
        ans = input(prompt_text + ": ").strip()
        if ans == "":
            return default
        try:
            return int(ans)
        except ValueError:
            print("Please enter an integer, or press ENTER.")


def list_cameras():
    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()

    print("\n========================================")
    print("Detected Basler cameras")
    print("========================================")

    if len(devices) == 0:
        print("No Basler cameras detected.")
        return []

    for i, dev in enumerate(devices):
        print(
            f"[{i}] Model: {dev.GetModelName()} | "
            f"Serial: {dev.GetSerialNumber()} | "
            f"Class: {dev.GetDeviceClass()}"
        )

    print("")
    return devices


def choose_device_for_role(devices, role):
    print(f"\nAssign camera for: {role.upper()}")
    print("Enter either the camera index or serial number.")
    ans = input(f"{role} camera index/serial: ").strip()

    if ans == "":
        raise RuntimeError(f"No camera selected for {role}.")

    # IMPORTANT:
    # Basler serial numbers are numeric strings, for example 25129018.
    # So we check serial number first. Otherwise Python will mistake the
    # serial number for a camera index.
    for dev in devices:
        if dev.GetSerialNumber() == ans:
            return dev

    # If not a serial number, try camera index.
    try:
        idx = int(ans)
        if 0 <= idx < len(devices):
            return devices[idx]

        raise RuntimeError(
            f"Input {ans} was not a valid serial number or camera index. "
            f"Valid indices are 0 to {len(devices) - 1}."
        )

    except ValueError:
        pass

    available_serials = [dev.GetSerialNumber() for dev in devices]
    raise RuntimeError(
        f"No camera found for {role} using input {ans}. "
        f"Available serials: {available_serials}. "
        f"Valid indices: 0 to {len(devices) - 1}."
    )


def safe_set(node, value, name):
    try:
        node.SetValue(value)
        print(f"  Set {name} = {value}")
        return True
    except Exception as e:
        print(f"  Could not set {name}: {e}")
        return False


def safe_get(node, name):
    try:
        return node.GetValue()
    except Exception as e:
        print(f"  Could not read {name}: {e}")
        return None


def configure_camera(cam, fps, exposure_us, width, height):
    cam.Open()

    # Monochrome camera. Keep as Mono8 for speed.
    safe_set(cam.PixelFormat, "Mono8", "PixelFormat")

    # Optional ROI/downsample test settings.
    if width is not None:
        safe_set(cam.Width, int(width), "Width")

    if height is not None:
        safe_set(cam.Height, int(height), "Height")

    safe_set(cam.ExposureTime, float(exposure_us), "ExposureTime")

    try:
        cam.AcquisitionFrameRateEnable.SetValue(True)
        print("  Set AcquisitionFrameRateEnable = True")
    except Exception as e:
        print(f"  Could not enable AcquisitionFrameRate: {e}")

    try:
        cam.AcquisitionFrameRate.SetValue(float(fps))
        print(f"  Set AcquisitionFrameRate = {fps}")
    except Exception as e:
        print(f"  Could not set AcquisitionFrameRate: {e}")

    settings = {
        "width": int(cam.Width.GetValue()),
        "height": int(cam.Height.GetValue()),
        "pixel_format": safe_get(cam.PixelFormat, "PixelFormat"),
        "exposure_us": safe_get(cam.ExposureTime, "ExposureTime"),
        "fps": safe_get(cam.AcquisitionFrameRate, "AcquisitionFrameRate"),
    }

    return settings


def terminal_stop_listener(stop_event):
    input("\nPress ENTER in this Terminal to stop live view...\n")
    stop_event.set()


def main():
    devices = list_cameras()

    if len(devices) < 3:
        print("Fewer than 3 cameras detected. Connect all three cameras and try again.")
        return

    print("You will now assign cameras to physical positions.")
    print("Tip: use serial numbers for final rig setup, because camera index order can change.\n")

    left_dev = choose_device_for_role(devices, "left")
    center_dev = choose_device_for_role(devices, "center")
    right_dev = choose_device_for_role(devices, "right")

    selected_serials = [
        left_dev.GetSerialNumber(),
        center_dev.GetSerialNumber(),
        right_dev.GetSerialNumber(),
    ]

    if len(set(selected_serials)) != 3:
        print("\nERROR: You selected the same camera more than once.")
        print("Selected serials:", selected_serials)
        return

    camera_specs = [
        ("left", left_dev),
        ("center", center_dev),
        ("right", right_dev),
    ]

    dev_by_role = {role: dev for role, dev in camera_specs}

    print("\n========================================")
    print("Camera assignment")
    print("========================================")
    print(f"LEFT:   {left_dev.GetModelName()} | Serial: {left_dev.GetSerialNumber()}")
    print(f"CENTER: {center_dev.GetModelName()} | Serial: {center_dev.GetSerialNumber()}")
    print(f"RIGHT:  {right_dev.GetModelName()} | Serial: {right_dev.GetSerialNumber()}")

    proceed = input("\nDoes this assignment look correct? Type y to continue: ").strip().lower()
    if proceed != "y":
        print("Stopped before opening cameras.")
        return

    print("\n========================================")
    print("Live view settings")
    print("========================================")
    fps = ask_float("Preview fps", 5.0)
    exposure_us = ask_float("Exposure time in microseconds", 5000.0)
    width = ask_int_or_none("Width", None)
    height = ask_int_or_none("Height", None)
    scale = ask_float("Display scale", 0.20)

    print("\nOpening cameras...\n")

    tl_factory = pylon.TlFactory.GetInstance()
    cameras = {}
    settings = {}

    try:
        for role, dev in camera_specs:
            print(f"\nConfiguring {role.upper()} camera | Serial: {dev.GetSerialNumber()}")
            cam = pylon.InstantCamera(tl_factory.CreateDevice(dev))
            cam_settings = configure_camera(cam, fps, exposure_us, width, height)
            cameras[role] = cam
            settings[role] = cam_settings

        print("\n========================================")
        print("Final camera settings")
        print("========================================")
        for role in ["left", "center", "right"]:
            dev = dev_by_role[role]
            s = settings[role]
            print(
                f"{role.upper():6s} | Serial {dev.GetSerialNumber()} | "
                f"{s['width']} x {s['height']} | {s['pixel_format']} | "
                f"exposure {s['exposure_us']} us | fps node {s['fps']}"
            )

        print("\nStarting live view.")
        print("Stop options:")
        print("  1. Press ENTER in Terminal")
        print("  2. Click a preview window and press q")
        print("  3. Close any preview window\n")

        stop_event = threading.Event()
        listener = threading.Thread(target=terminal_stop_listener, args=(stop_event,), daemon=True)
        listener.start()

        for cam in cameras.values():
            cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

        last_time = time.time()
        displayed_frames = 0
        display_fps = 0.0

        window_names = {
            "left": "LEFT camera",
            "center": "CENTER camera",
            "right": "RIGHT camera",
        }

        while not stop_event.is_set():
            any_failed = False

            for role in ["left", "center", "right"]:
                cam = cameras[role]

                if not cam.IsGrabbing():
                    any_failed = True
                    continue

                grab_result = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)

                try:
                    if grab_result.GrabSucceeded():
                        frame = grab_result.Array

                        preview_w = max(1, int(frame.shape[1] * scale))
                        preview_h = max(1, int(frame.shape[0] * scale))

                        preview = cv2.resize(
                            frame,
                            (preview_w, preview_h),
                            interpolation=cv2.INTER_AREA,
                        )

                        preview_bgr = cv2.cvtColor(preview, cv2.COLOR_GRAY2BGR)

                        text = (
                            f"{role.upper()} | Serial {dev_by_role[role].GetSerialNumber()} | "
                            f"display fps {display_fps:.1f} | ENTER terminal or q window to quit"
                        )

                        cv2.putText(
                            preview_bgr,
                            text,
                            (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.7,
                            (255, 255, 255),
                            2,
                            cv2.LINE_AA,
                        )

                        cv2.imshow(window_names[role], preview_bgr)

                finally:
                    grab_result.Release()

            displayed_frames += 1
            now = time.time()

            if now - last_time >= 1.0:
                display_fps = displayed_frames / (now - last_time)
                displayed_frames = 0
                last_time = now

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                stop_event.set()

            # Stop if any window was closed manually.
            for role, win_name in window_names.items():
                try:
                    if cv2.getWindowProperty(win_name, cv2.WND_PROP_VISIBLE) < 1:
                        stop_event.set()
                except Exception:
                    pass

            if any_failed:
                print("One or more cameras stopped grabbing.")
                stop_event.set()

        print("\nStopping live view...")

    finally:
        for role, cam in cameras.items():
            try:
                if cam.IsGrabbing():
                    cam.StopGrabbing()
            except Exception:
                pass

            try:
                cam.Close()
                print(f"Closed {role} camera.")
            except Exception:
                pass

        cv2.destroyAllWindows()
        print("Done. Cameras released safely.")


if __name__ == "__main__":
    main()
