#!/usr/bin/env python3
# ============================================================
# stitch_three_camera_raw_to_avi.py
#
# Quick offline stitching / preview maker for the 3-camera thermotaxis rig.
#
# What this does now:
#   - Reads left / center / right raw Mono8 camera files.
#   - Uses each camera's recording_config.json to get width and height.
#   - Makes a stitched .avi preview and saves it in the same experiment folder.
#   - Supports simple side-by-side stitching with optional overlap cropping.
#
# Important:
#   This is NOT yet geometric calibration / homography-based stitching.
#   This is the first practical step: frame-by-frame combined video preview.
#
# Later, after using a calibration board, we can replace the simple concat step
# with true homography-based alignment and blending.
#
# Install:
#   python3 -m pip install numpy opencv-python
#
# Example:
#   python3 stitch_three_camera_raw_to_avi.py \
#       --input_folder /Users/sk3526/Desktop/tri_cam_test/three_camera_20260520_110838 \
#       --fps 10 \
#       --scale 0.25
#
# Stop early test:
#   python3 stitch_three_camera_raw_to_avi.py \
#       --input_folder /Users/sk3526/Desktop/tri_cam_test/three_camera_20260520_110838 \
#       --fps 10 \
#       --scale 0.25 \
#       --max_frames 100
# ============================================================

import argparse
import csv
import json
import os
from pathlib import Path

import cv2
import numpy as np


def find_file(folder, candidates):
    folder = Path(folder)
    for name in candidates:
        p = folder / name
        if p.exists():
            return p
    return None


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def count_metadata_frames(metadata_csv):
    """Count written frames from metadata CSV."""
    if metadata_csv is None or not Path(metadata_csv).exists():
        return None

    count = 0
    with open(metadata_csv, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(row.get("grab_succeeded", "")).strip() == "1":
                count += 1
    return count


def get_camera_files(input_folder, role):
    """
    Expected files from our acquisition code:
        left_camera_raw_mono8.raw
        left_recording_config.json
        left_frame_metadata.csv
    """
    raw_path = find_file(input_folder, [
        f"{role}_camera_raw_mono8.raw",
        f"{role}.raw",
        f"{role}_raw.raw",
    ])

    config_path = find_file(input_folder, [
        f"{role}_recording_config.json",
        f"{role}_config.json",
    ])

    metadata_path = find_file(input_folder, [
        f"{role}_frame_metadata.csv",
        f"{role}_metadata.csv",
    ])

    if raw_path is None:
        raise FileNotFoundError(f"Could not find raw file for role '{role}' in {input_folder}")

    if config_path is None:
        raise FileNotFoundError(f"Could not find config JSON for role '{role}' in {input_folder}")

    config = load_json(config_path)

    width = int(config["width"])
    height = int(config["height"])

    frame_bytes = width * height  # Mono8 uint8
    raw_size = raw_path.stat().st_size
    n_frames_from_raw = raw_size // frame_bytes

    n_frames_from_metadata = count_metadata_frames(metadata_path)

    return {
        "role": role,
        "raw_path": raw_path,
        "config_path": config_path,
        "metadata_path": metadata_path,
        "width": width,
        "height": height,
        "frame_bytes": frame_bytes,
        "n_frames_from_raw": n_frames_from_raw,
        "n_frames_from_metadata": n_frames_from_metadata,
    }


def read_raw_frame(fh, frame_index, width, height, frame_bytes):
    offset = frame_index * frame_bytes
    fh.seek(offset)
    buf = fh.read(frame_bytes)

    if len(buf) != frame_bytes:
        return None

    frame = np.frombuffer(buf, dtype=np.uint8).reshape((height, width))
    return frame


def crop_overlap(left, center, right, overlap_pixels):
    """
    Simple overlap handling.
    If overlap_pixels > 0, remove half the overlap from touching edges.

    Example:
        left right edge cropped by overlap/2
        center left and right edges cropped by overlap/2
        right left edge cropped by overlap/2
    """
    overlap_pixels = int(overlap_pixels)

    if overlap_pixels <= 0:
        return left, center, right

    half = overlap_pixels // 2

    if half <= 0:
        return left, center, right

    left_c = left[:, :-half] if left.shape[1] > half else left
    center_c = center[:, half:-half] if center.shape[1] > 2 * half else center
    right_c = right[:, half:] if right.shape[1] > half else right

    return left_c, center_c, right_c


def normalize_heights(frames):
    """Resize frames to the minimum height among the three before concatenation."""
    min_h = min(f.shape[0] for f in frames)
    out = []
    for f in frames:
        if f.shape[0] == min_h:
            out.append(f)
        else:
            new_w = int(round(f.shape[1] * (min_h / f.shape[0])))
            out.append(cv2.resize(f, (new_w, min_h), interpolation=cv2.INTER_AREA))
    return out


def make_stitched_frame(left, center, right, scale=0.25, overlap_pixels=0, add_labels=True, frame_index=None):
    left, center, right = crop_overlap(left, center, right, overlap_pixels)
    left, center, right = normalize_heights([left, center, right])

    stitched = np.hstack([left, center, right])

    if scale != 1.0:
        new_w = max(1, int(round(stitched.shape[1] * scale)))
        new_h = max(1, int(round(stitched.shape[0] * scale)))
        stitched = cv2.resize(stitched, (new_w, new_h), interpolation=cv2.INTER_AREA)

    stitched_bgr = cv2.cvtColor(stitched, cv2.COLOR_GRAY2BGR)

    if add_labels:
        h, w = stitched_bgr.shape[:2]

        # Approximate label x positions after concatenation.
        x_left = 30
        x_center = w // 3 + 30
        x_right = 2 * w // 3 + 30

        cv2.putText(stitched_bgr, "LEFT", (x_left, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(stitched_bgr, "CENTER", (x_center, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(stitched_bgr, "RIGHT", (x_right, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

        if frame_index is not None:
            cv2.putText(stitched_bgr, f"frame {frame_index}", (30, h - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

    return stitched_bgr


def main():
    parser = argparse.ArgumentParser(description="Make stitched AVI preview from three raw Basler camera files.")

    parser.add_argument(
        "--input_folder",
        type=str,
        required=True,
        help="Folder containing left/center/right raw files and config JSONs.",
    )

    parser.add_argument(
        "--output_name",
        type=str,
        default="stitched_preview.avi",
        help="Output AVI filename saved inside input_folder.",
    )

    parser.add_argument(
        "--fps",
        type=float,
        default=10.0,
        help="Output AVI frame rate.",
    )

    parser.add_argument(
        "--scale",
        type=float,
        default=0.25,
        help="Scale stitched video. Use 0.25 or 0.2 for manageable preview. Use 1.0 only if you really want huge output.",
    )

    parser.add_argument(
        "--start_frame",
        type=int,
        default=0,
        help="First frame index to stitch.",
    )

    parser.add_argument(
        "--max_frames",
        type=int,
        default=None,
        help="Maximum number of frames to stitch. Use for quick testing.",
    )

    parser.add_argument(
        "--overlap_pixels",
        type=int,
        default=0,
        help="Simple overlap crop in raw pixels between neighboring cameras. Use 0 for pure side-by-side.",
    )

    parser.add_argument(
        "--no_labels",
        action="store_true",
        help="Do not add LEFT/CENTER/RIGHT labels.",
    )

    args = parser.parse_args()

    input_folder = Path(args.input_folder)
    if not input_folder.exists():
        raise FileNotFoundError(f"Input folder does not exist: {input_folder}")

    print("\nReading camera files from:")
    print(f"  {input_folder}")

    left_info = get_camera_files(input_folder, "left")
    center_info = get_camera_files(input_folder, "center")
    right_info = get_camera_files(input_folder, "right")

    infos = [left_info, center_info, right_info]

    print("\nDetected camera data:")
    for info in infos:
        print(
            f"  {info['role'].upper():6s}: "
            f"{info['width']} x {info['height']} | "
            f"raw frames = {info['n_frames_from_raw']} | "
            f"metadata frames = {info['n_frames_from_metadata']} | "
            f"{info['raw_path'].name}"
        )

    min_frames = min(info["n_frames_from_raw"] for info in infos)

    if args.start_frame >= min_frames:
        raise ValueError(f"start_frame {args.start_frame} is beyond available frames {min_frames}")

    n_frames_to_process = min_frames - args.start_frame
    if args.max_frames is not None:
        n_frames_to_process = min(n_frames_to_process, int(args.max_frames))

    print("\nStitch settings:")
    print(f"  start_frame:     {args.start_frame}")
    print(f"  frames to stitch:{n_frames_to_process}")
    print(f"  output fps:      {args.fps}")
    print(f"  scale:           {args.scale}")
    print(f"  overlap_pixels:  {args.overlap_pixels}")

    output_path = input_folder / args.output_name

    left_fh = open(left_info["raw_path"], "rb")
    center_fh = open(center_info["raw_path"], "rb")
    right_fh = open(right_info["raw_path"], "rb")

    writer = None

    try:
        for k in range(n_frames_to_process):
            frame_index = args.start_frame + k

            left = read_raw_frame(
                left_fh,
                frame_index,
                left_info["width"],
                left_info["height"],
                left_info["frame_bytes"],
            )

            center = read_raw_frame(
                center_fh,
                frame_index,
                center_info["width"],
                center_info["height"],
                center_info["frame_bytes"],
            )

            right = read_raw_frame(
                right_fh,
                frame_index,
                right_info["width"],
                right_info["height"],
                right_info["frame_bytes"],
            )

            if left is None or center is None or right is None:
                print(f"Stopped early at frame {frame_index}; could not read one camera frame.")
                break

            stitched = make_stitched_frame(
                left,
                center,
                right,
                scale=args.scale,
                overlap_pixels=args.overlap_pixels,
                add_labels=not args.no_labels,
                frame_index=frame_index,
            )

            if writer is None:
                out_h, out_w = stitched.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"MJPG")
                writer = cv2.VideoWriter(str(output_path), fourcc, float(args.fps), (out_w, out_h), True)

                if not writer.isOpened():
                    raise RuntimeError("Could not open AVI writer. Try a different output folder or codec.")

                print("\nOutput video:")
                print(f"  {output_path}")
                print(f"  size: {out_w} x {out_h}")

            writer.write(stitched)

            if (k + 1) % 100 == 0 or (k + 1) == n_frames_to_process:
                print(f"  stitched {k + 1} / {n_frames_to_process} frames")

    finally:
        left_fh.close()
        center_fh.close()
        right_fh.close()

        if writer is not None:
            writer.release()

    print("\nDone.")
    print(f"Saved stitched preview AVI:\n  {output_path}")


if __name__ == "__main__":
    main()
