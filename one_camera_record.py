#!/usr/bin/env python3
import argparse, sys
from thermotaxis_camera_common import list_cameras, create_experiment_dir, record_one_camera_to_folder


def main():
    p = argparse.ArgumentParser(description='One-camera Basler recorder for thermotaxis rig.')
    p.add_argument('--list', action='store_true')
    p.add_argument('--output', default='./thermotaxis_one_camera_output')
    p.add_argument('--duration', type=float, default=30.0)
    p.add_argument('--fps', type=float, default=14.0)
    p.add_argument('--exposure', type=float, default=9997.0)
    p.add_argument('--serial', default=None)
    p.add_argument('--camera_index', type=int, default=0)
    p.add_argument('--role', default='cam0')
    p.add_argument('--width', type=int, default=None)
    p.add_argument('--height', type=int, default=None)
    p.add_argument('--offset_x', type=int, default=None)
    p.add_argument('--offset_y', type=int, default=None)
    p.add_argument('--queue_size', type=int, default=32)
    p.add_argument('--queue_timeout', type=float, default=2.0)
    p.add_argument('--camera_buffer_count', type=int, default=64)
    p.add_argument('--retrieve_timeout_ms', type=int, default=5000)
    p.add_argument('--preview_scale', type=float, default=0.25)
    p.add_argument('--preview_every', type=int, default=10, help='Use 0 to disable preview.')
    args = p.parse_args()
    if args.list:
        list_cameras(); return 0
    exp = create_experiment_dir(args.output, 'one_camera')
    print(f'\nExperiment folder:\n  {exp}')
    return record_one_camera_to_folder(
        role=args.role, serial=args.serial, index=args.camera_index, output_dir=exp,
        duration=args.duration, fps=args.fps, exposure=args.exposure, width=args.width, height=args.height,
        offset_x=args.offset_x, offset_y=args.offset_y, queue_size=args.queue_size,
        queue_timeout=args.queue_timeout, buffers=args.camera_buffer_count,
        preview_scale=args.preview_scale, preview_every=args.preview_every,
        retrieve_timeout_ms=args.retrieve_timeout_ms, external_start_event=None)

if __name__ == '__main__':
    sys.exit(main())
