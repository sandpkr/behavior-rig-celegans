#!/usr/bin/env python3
# ============================================================
# Single Basler camera recording test
# Saves:
#   1. raw Mono8 video as .raw
#   2. frame metadata as .csv
#   3. experiment settings as .json
#   4. small preview video as .avi
#
# Example:
# python single_basler_record.py --duration 30 --fps 14 --output /Users/sk3526/Desktop/basler_test
#
# To list connected cameras:
# python single_basler_record.py --list
# ============================================================

import argparse
import csv
import json
import os
import time
from datetime import datetime

import cv2
import numpy as np
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


def set_node_value_safely(node, value, name):
    try:
        if pylon.IsWritable(node):
            node.SetValue(value)
            print(f"Set {name} = {value}")
        else:
            print(f"Could not set {name}: node is not writable.")
    except Exception as e:
        print(f"Could not set {name}: {e}")


def get_node_value_safely(node, name):
    try:
        if pylon.IsReadable(node):
            return node.GetValue()
    except Exception:
        pass
    return None


def choose_camera(serial=None, index=0):
    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()

    if len(devices) == 0:
        raise RuntimeError("No Basler cameras detected.")

    if serial is not None:
        for dev in devices:
            if dev.GetSerialNumber() == serial:
                return pylon.InstantCamera(tl_factory.CreateDevice(dev)), dev

        raise RuntimeError(f"No camera found with serial number: {serial}")

    if index >= len(devices):
        raise RuntimeError(f"Camera index {index} requested, but only {len(devices)} camera(s) detected.")

    dev = devices[index]
    return pylon.InstantCamera(tl_factory.CreateDevice(dev)), dev


def record_single_camera(
    output_dir,
    duration_sec=30,
    fps=14.0,
    exposure_us=9997.0,
    width=None,
    height=None,
    serial=None,
    camera_index=0,
    preview_scale=0.25,
):
    os.makedirs(output_dir, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    experiment_dir = os.path.join(output_dir, f"single_camera_test_{timestamp_str}")
    os.makedirs(experiment_dir, exist_ok=True)

    camera, device_info = choose_camera(serial=serial, index=camera_index)

    camera_name = device_info.GetModelName()
    camera_serial = device_info.GetSerialNumber()

    raw_path = os.path.join(experiment_dir, "camera_raw_mono8.raw")
    csv_path = os.path.join(experiment_dir, "frame_metadata.csv")
    json_path = os.path.join(experiment_dir, "recording_config.json")
    preview_path = os.path.join(experiment_dir, "preview_downsampled.avi")

    print("\nUsing camera:")
    print(f"  Model:  {camera_name}")
    print(f"  Serial: {camera_serial}")
    print(f"\nSaving to:\n  {experiment_dir}\n")

    camera.Open()

    try:
        # ------------------------------------------------------------
        # Camera configuration
        # ------------------------------------------------------------

        # Use Mono8 to reduce data size and simplify downstream analysis.
        try:
            camera.PixelFormat.SetValue("Mono8")
            print("Set PixelFormat = Mono8")
        except Exception as e:
            print(f"Could not set PixelFormat to Mono8: {e}")

        # Optional width and height.
        # If not given, use the camera's current/default full frame.
        if width is not None:
            set_node_value_safely(camera.Width, int(width), "Width")

        if height is not None:
            set_node_value_safely(camera.Height, int(height), "Height")

        # Exposure time.
        set_node_value_safely(camera.ExposureTime, float(exposure_us), "ExposureTime")

        # Frame rate.
        try:
            camera.AcquisitionFrameRateEnable.SetValue(True)
            print("Set AcquisitionFrameRateEnable = True")
        except Exception as e:
            print(f"Could not enable AcquisitionFrameRate: {e}")

        try:
            camera.AcquisitionFrameRate.SetValue(float(fps))
            print(f"Set AcquisitionFrameRate = {fps}")
        except Exception as e:
            print(f"Could not set AcquisitionFrameRate: {e}")

        actual_width = int(camera.Width.GetValue())
        actual_height = int(camera.Height.GetValue())

        actual_fps = get_node_value_safely(camera.AcquisitionFrameRate, "AcquisitionFrameRate")
        actual_exposure = get_node_value_safely(camera.ExposureTime, "ExposureTime")
        actual_pixel_format = get_node_value_safely(camera.PixelFormat, "PixelFormat")

        print("\nFinal camera settings:")
        print(f"  Width:        {actual_width}")
        print(f"  Height:       {actual_height}")
        print(f"  PixelFormat:  {actual_pixel_format}")
        print(f"  Exposure us:  {actual_exposure}")
        print(f"  FPS:          {actual_fps}")

        expected_frames = int(round(duration_sec * fps))

        config = {
            "camera_model": camera_name,
            "camera_serial": camera_serial,
            "duration_sec": duration_sec,
            "requested_fps": fps,
            "actual_fps_node_value": actual_fps,
            "requested_exposure_us": exposure_us,
            "actual_exposure_us": actual_exposure,
            "width": actual_width,
            "height": actual_height,
            "pixel_format": actual_pixel_format,
            "expected_frames": expected_frames,
            "raw_file": os.path.basename(raw_path),
            "metadata_file": os.path.basename(csv_path),
            "preview_file": os.path.basename(preview_path),
            "raw_format_note": "uint8 Mono8 frames written sequentially, frame shape = height x width",
        }

        with open(json_path, "w") as f:
            json.dump(config, f, indent=4)

        # ------------------------------------------------------------
        # Preview video writer
        # ------------------------------------------------------------
        preview_w = max(1, int(round(actual_width * preview_scale)))
        preview_h = max(1, int(round(actual_height * preview_scale)))

        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        preview_writer = cv2.VideoWriter(
            preview_path,
            fourcc,
            float(fps),
            (preview_w, preview_h),
            True,
        )

        if not preview_writer.isOpened():
            print("Warning: preview video writer did not open. Raw recording will still be saved.")
            preview_writer = None

        # ------------------------------------------------------------
        # Start acquisition
        # ------------------------------------------------------------
        print("\nStarting recording...")
        print(f"Target duration: {duration_sec} sec")
        print(f"Target frames:   {expected_frames}")

        frame_count = 0
        failed_count = 0

        t_start_wall = time.time()
        t_start_perf = time.perf_counter()

        camera.StartGrabbingMax(expected_frames, pylon.GrabStrategy_OneByOne)

        with open(raw_path, "wb") as raw_file, open(csv_path, "w", newline="") as csv_file:
            writer = csv.writer(csv_file)

            writer.writerow([
                "saved_frame_index",
                "grab_succeeded",
                "camera_block_id",
                "camera_timestamp",
                "computer_time_sec",
                "elapsed_sec",
                "height",
                "width",
            ])

            while camera.IsGrabbing():
                grab_result = camera.RetrieveResult(
                    5000,
                    pylon.TimeoutHandling_ThrowException
                )

                try:
                    computer_time_sec = time.time()
                    elapsed_sec = time.perf_counter() - t_start_perf

                    if grab_result.GrabSucceeded():
                        frame = grab_result.Array

                        if frame.dtype != np.uint8:
                            frame = frame.astype(np.uint8)

                        raw_file.write(frame.tobytes(order="C"))

                        block_id = getattr(grab_result, "BlockID", None)
                        camera_timestamp = getattr(grab_result, "TimeStamp", None)

                        writer.writerow([
                            frame_count,
                            1,
                            block_id,
                            camera_timestamp,
                            computer_time_sec,
                            elapsed_sec,
                            frame.shape[0],
                            frame.shape[1],
                        ])

                        if preview_writer is not None:
                            small = cv2.resize(
                                frame,
                                (preview_w, preview_h),
                                interpolation=cv2.INTER_AREA
                            )

                            # Convert grayscale preview to BGR for safer video writing.
                            small_bgr = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
                            preview_writer.write(small_bgr)

                        frame_count += 1

                    else:
                        failed_count += 1
                        writer.writerow([
                            frame_count,
                            0,
                            None,
                            None,
                            computer_time_sec,
                            elapsed_sec,
                            actual_height,
                            actual_width,
                        ])

                finally:
                    grab_result.Release()

        t_end_wall = time.time()
        actual_duration = t_end_wall - t_start_wall
        measured_fps = frame_count / actual_duration if actual_duration > 0 else np.nan

        if preview_writer is not None:
            preview_writer.release()

        camera.StopGrabbing()

        print("\nRecording finished.")
        print(f"Saved frames:     {frame_count}")
        print(f"Failed grabs:     {failed_count}")
        print(f"Actual duration:  {actual_duration:.3f} sec")
        print(f"Measured FPS:     {measured_fps:.3f}")

        print("\nFiles saved:")
        print(f"  Raw video:       {raw_path}")
        print(f"  Metadata CSV:    {csv_path}")
        print(f"  Config JSON:     {json_path}")
        print(f"  Preview video:   {preview_path}")

        print("\nImportant:")
        print("  The .raw file is not directly viewable.")
        print("  Use the preview .avi to quickly check the recording.")
        print("  The .raw file is for later analysis with the saved width/height in the JSON file.")

    finally:
        if camera.IsGrabbing():
            camera.StopGrabbing()
        camera.Close()


def main():
    parser = argparse.ArgumentParser(description="Single Basler camera recording test.")

    parser.add_argument("--list", action="store_true", help="List connected Basler cameras and exit.")

    parser.add_argument("--output", type=str, default="./basler_single_camera_output",
                        help="Output folder.")

    parser.add_argument("--duration", type=float, default=30,
                        help="Recording duration in seconds.")

    parser.add_argument("--fps", type=float, default=14,
                        help="Requested frame rate.")

    parser.add_argument("--exposure", type=float, default=9997,
                        help="Exposure time in microseconds.")

    parser.add_argument("--width", type=int, default=None,
                        help="Optional image width. If omitted, use current/full width.")

    parser.add_argument("--height", type=int, default=None,
                        help="Optional image height. If omitted, use current/full height.")

    parser.add_argument("--serial", type=str, default=None,
                        help="Optional camera serial number.")

    parser.add_argument("--camera_index", type=int, default=0,
                        help="Camera index if serial number is not provided.")

    parser.add_argument("--preview_scale", type=float, default=0.25,
                        help="Scale factor for preview video.")

    args = parser.parse_args()

    if args.list:
        list_cameras()
        return

    record_single_camera(
        output_dir=args.output,
        duration_sec=args.duration,
        fps=args.fps,
        exposure_us=args.exposure,
        width=args.width,
        height=args.height,
        serial=args.serial,
        camera_index=args.camera_index,
        preview_scale=args.preview_scale,
    )


if __name__ == "__main__":
    main()