#!/usr/bin/env python3
# ============================================================
# Live Basler camera preview
#
# Example:
#   python3 live_basler_preview.py --list
#   python3 live_basler_preview.py --fps 14 --exposure 9997 --scale 0.25
#
# Press:
#   q  = quit
#   s  = save current preview image as snapshot.png
# ============================================================

import argparse
import cv2
import time
from datetime import datetime
from pypylon import pylon


def list_cameras():
    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()

    if len(devices) == 0:
        print("No Basler cameras detected.")
        return

    print("\nDetected Basler cameras:")
    for i, dev in enumerate(devices):
        print(f"  [{i}]")
        print(f"      Model:  {dev.GetModelName()}")
        print(f"      Serial: {dev.GetSerialNumber()}")
        print(f"      Class:  {dev.GetDeviceClass()}")
    print("")


def choose_camera(serial=None, camera_index=0):
    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()

    if len(devices) == 0:
        raise RuntimeError("No Basler cameras detected.")

    if serial is not None:
        for dev in devices:
            if dev.GetSerialNumber() == serial:
                return pylon.InstantCamera(tl_factory.CreateDevice(dev)), dev

        raise RuntimeError(f"No camera found with serial number: {serial}")

    if camera_index >= len(devices):
        raise RuntimeError(
            f"Camera index {camera_index} requested, but only {len(devices)} camera(s) detected."
        )

    dev = devices[camera_index]
    return pylon.InstantCamera(tl_factory.CreateDevice(dev)), dev


def safe_set(node, value, name):
    try:
        if pylon.IsWritable(node):
            node.SetValue(value)
            print(f"Set {name} = {value}")
        else:
            print(f"Could not set {name}: node not writable.")
    except Exception as e:
        print(f"Could not set {name}: {e}")


def live_preview(
    serial=None,
    camera_index=0,
    fps=14.0,
    exposure_us=9997.0,
    width=None,
    height=None,
    scale=0.25,
):
    camera, dev = choose_camera(serial=serial, camera_index=camera_index)

    print("\nUsing camera:")
    print(f"  Model:  {dev.GetModelName()}")
    print(f"  Serial: {dev.GetSerialNumber()}")

    camera.Open()

    try:
        # Use grayscale image for IR worm imaging.
        try:
            camera.PixelFormat.SetValue("Mono8")
            print("Set PixelFormat = Mono8")
        except Exception as e:
            print(f"Could not set PixelFormat to Mono8: {e}")

        if width is not None:
            safe_set(camera.Width, int(width), "Width")

        if height is not None:
            safe_set(camera.Height, int(height), "Height")

        safe_set(camera.ExposureTime, float(exposure_us), "ExposureTime")

        try:
            camera.AcquisitionFrameRateEnable.SetValue(True)
            print("Set AcquisitionFrameRateEnable = True")
        except Exception as e:
            print(f"Could not enable frame rate control: {e}")

        try:
            camera.AcquisitionFrameRate.SetValue(float(fps))
            print(f"Set AcquisitionFrameRate = {fps}")
        except Exception as e:
            print(f"Could not set AcquisitionFrameRate: {e}")

        actual_width = int(camera.Width.GetValue())
        actual_height = int(camera.Height.GetValue())

        print("\nLive preview started.")
        print(f"Image size: {actual_width} x {actual_height}")
        print("Press q to quit.")
        print("Press s to save a snapshot.\n")

        # LatestImageOnly is good for live preview because it prevents lag.
        # For real recording, we used OneByOne to avoid silently skipping frames.
        camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

        last_time = time.time()
        frame_counter = 0
        displayed_fps = 0.0

        while camera.IsGrabbing():
            grab_result = camera.RetrieveResult(
                5000,
                pylon.TimeoutHandling_ThrowException
            )

            try:
                if grab_result.GrabSucceeded():
                    frame = grab_result.Array

                    frame_counter += 1
                    now = time.time()

                    if now - last_time >= 1.0:
                        displayed_fps = frame_counter / (now - last_time)
                        frame_counter = 0
                        last_time = now

                    preview_w = max(1, int(frame.shape[1] * scale))
                    preview_h = max(1, int(frame.shape[0] * scale))

                    preview = cv2.resize(
                        frame,
                        (preview_w, preview_h),
                        interpolation=cv2.INTER_AREA
                    )

                    # Add text overlay.
                    preview_bgr = cv2.cvtColor(preview, cv2.COLOR_GRAY2BGR)
                    cv2.putText(
                        preview_bgr,
                        f"Live preview | displayed FPS: {displayed_fps:.1f} | q=quit | s=snapshot",
                        (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA
                    )

                    cv2.imshow("Basler live preview", preview_bgr)

                    key = cv2.waitKey(1) & 0xFF

                    if key == ord("q"):
                        print("Quitting live preview.")
                        break

                    if key == ord("s"):
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"snapshot_{timestamp}.png"
                        cv2.imwrite(filename, frame)
                        print(f"Saved full-resolution snapshot: {filename}")

            finally:
                grab_result.Release()

    finally:
        if camera.IsGrabbing():
            camera.StopGrabbing()
        camera.Close()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="Live preview from one Basler camera.")

    parser.add_argument("--list", action="store_true", help="List connected cameras and exit.")
    parser.add_argument("--serial", type=str, default=None, help="Camera serial number.")
    parser.add_argument("--camera_index", type=int, default=0, help="Camera index if serial is not given.")

    parser.add_argument("--fps", type=float, default=14.0, help="Requested frame rate.")
    parser.add_argument("--exposure", type=float, default=9997.0, help="Exposure time in microseconds.")

    parser.add_argument("--width", type=int, default=None, help="Optional camera width.")
    parser.add_argument("--height", type=int, default=None, help="Optional camera height.")
    parser.add_argument("--scale", type=float, default=0.25, help="Display scale for preview window.")

    args = parser.parse_args()

    if args.list:
        list_cameras()
        return

    live_preview(
        serial=args.serial,
        camera_index=args.camera_index,
        fps=args.fps,
        exposure_us=args.exposure,
        width=args.width,
        height=args.height,
        scale=args.scale,
    )


if __name__ == "__main__":
    main()