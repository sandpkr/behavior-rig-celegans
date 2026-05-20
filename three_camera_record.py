#!/usr/bin/env python3
import argparse, csv, glob, json, multiprocessing as mp, sys, time, traceback
from pathlib import Path
from thermotaxis_camera_common import list_cameras, create_experiment_dir, record_one_camera_to_folder


def camera_entry(role, serial, index, output_dir, args_dict, start_event, result_queue):
    try:
        code = record_one_camera_to_folder(
            role=role, serial=serial, index=index, output_dir=output_dir,
            duration=args_dict['duration'], fps=args_dict['fps'], exposure=args_dict['exposure'],
            width=args_dict['width'], height=args_dict['height'], offset_x=args_dict['offset_x'], offset_y=args_dict['offset_y'],
            queue_size=args_dict['queue_size'], queue_timeout=args_dict['queue_timeout'], buffers=args_dict['camera_buffer_count'],
            preview_scale=args_dict['preview_scale'], preview_every=args_dict['preview_every'], retrieve_timeout_ms=args_dict['retrieve_timeout_ms'],
            external_start_event=start_event)
        result_queue.put({'role': role, 'exit_code': code, 'error': None})
    except Exception:
        result_queue.put({'role': role, 'exit_code': 1, 'error': traceback.format_exc()})


def resolve_port(port):
    if port is None: return None
    matches = glob.glob(port)
    return matches[0] if matches else port


def load_schedule(path):
    if path is None: return []
    with open(path) as f: events = json.load(f)
    events = [{'time_sec': float(e['time_sec']), 'command': str(e['command'])} for e in events]
    return sorted(events, key=lambda e: e['time_sec'])


def serial_logger(serial_port, baud, output_dir, duration, start_event, stop_event, schedule_path):
    try:
        import serial
    except Exception:
        print('[serial] pyserial not installed. Run: python3 -m pip install pyserial')
        return
    port = resolve_port(serial_port); events = load_schedule(schedule_path)
    out = Path(output_dir) / 'arduino_serial_log.csv'
    print(f'[serial] Opening {port} at {baud} baud')
    try:
        ser = serial.Serial(port, int(baud), timeout=0.02)
        time.sleep(2.0)  # many Arduinos reset when serial opens
    except Exception:
        print('[serial] Could not open serial port:'); print(traceback.format_exc()); return
    print('[serial] Waiting for synchronized start...')
    start_event.wait(); t0 = time.perf_counter(); idx = 0
    with open(out, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['computer_time_sec','elapsed_sec','direction','content'])
        w.writerow([time.time(), 0, 'system', 'serial_logger_started'])
        try:
            while not stop_event.is_set():
                elapsed = time.perf_counter() - t0
                if elapsed >= duration: break
                while idx < len(events) and elapsed >= events[idx]['time_sec']:
                    cmd = events[idx]['command']
                    try:
                        ser.write((cmd + '\n').encode('utf-8'))
                        w.writerow([time.time(), elapsed, 'to_arduino', cmd])
                        print(f'[serial] sent at {elapsed:.3f}s: {cmd}')
                    except Exception as e:
                        w.writerow([time.time(), elapsed, 'send_error', f'{cmd} | {e}'])
                    idx += 1
                try:
                    line = ser.readline()
                    if line:
                        w.writerow([time.time(), elapsed, 'from_arduino', line.decode('utf-8', errors='replace').strip()])
                except Exception as e:
                    w.writerow([time.time(), elapsed, 'read_error', str(e)])
                time.sleep(0.001)
        finally:
            w.writerow([time.time(), time.perf_counter()-t0, 'system', 'serial_logger_stopped'])
            ser.close()
    print(f'[serial] Log saved to {out}')


def main():
    p = argparse.ArgumentParser(description='Three-camera Basler recorder for thermotaxis rig.')
    p.add_argument('--list', action='store_true')
    p.add_argument('--output', default='./thermotaxis_three_camera_output')
    p.add_argument('--duration', type=float, default=30.0)
    p.add_argument('--fps', type=float, default=14.0)
    p.add_argument('--exposure', type=float, default=9997.0)
    p.add_argument('--left_serial', default=None); p.add_argument('--center_serial', default=None); p.add_argument('--right_serial', default=None)
    p.add_argument('--left_index', type=int, default=0); p.add_argument('--center_index', type=int, default=1); p.add_argument('--right_index', type=int, default=2)
    p.add_argument('--width', type=int, default=None); p.add_argument('--height', type=int, default=None)
    p.add_argument('--offset_x', type=int, default=None); p.add_argument('--offset_y', type=int, default=None)
    p.add_argument('--queue_size', type=int, default=32); p.add_argument('--queue_timeout', type=float, default=2.0)
    p.add_argument('--camera_buffer_count', type=int, default=64); p.add_argument('--retrieve_timeout_ms', type=int, default=5000)
    p.add_argument('--preview_scale', type=float, default=0.25)
    p.add_argument('--preview_every', type=int, default=0, help='Default 0 because previews add load during 3-camera acquisition.')
    p.add_argument('--serial_port', default=None, help='Optional Arduino/Teensy port, e.g. /dev/tty.usbmodem*')
    p.add_argument('--serial_baud', type=int, default=9600)
    p.add_argument('--event_schedule', default=None, help='Optional JSON schedule of serial commands for future opto LEDs.')
    args = p.parse_args()
    if args.list:
        list_cameras(); return 0
    try: mp.set_start_method('spawn')
    except RuntimeError: pass
    exp = create_experiment_dir(args.output, 'three_camera')
    print(f'\nMain experiment folder:\n  {exp}')
    args_dict = vars(args).copy()
    roles = [('left', args.left_serial, args.left_index), ('center', args.center_serial, args.center_index), ('right', args.right_serial, args.right_index)]
    master = {
        'experiment_type':'three_camera_thermotaxis', 'duration_sec':args.duration, 'fps':args.fps,
        'exposure_us':args.exposure, 'width':args.width, 'height':args.height, 'camera_roles':roles,
        'serial_logging_enabled':args.serial_port is not None, 'serial_port':args.serial_port,
        'event_schedule':args.event_schedule,
        'future_notes':['Save raw Mono8 during acquisition.', 'Do offline stitching/tracking later.', 'For true frame sync, add shared hardware TTL trigger to all cameras.', 'For optogenetics, update Arduino/Teensy firmware to accept LED RED/BLUE ON/OFF commands or use TTL outputs.']}
    (Path(exp)/'master_experiment_config.json').write_text(json.dumps(master, indent=4))
    start_event = mp.Event(); stop_event = mp.Event(); result_queue = mp.Queue(); processes = []
    for role, serial, index in roles:
        pr = mp.Process(target=camera_entry, args=(role, serial, index, str(exp), args_dict, start_event, result_queue), name=f'camera_{role}')
        pr.start(); processes.append(pr)
    if args.serial_port:
        sp = mp.Process(target=serial_logger, args=(args.serial_port, args.serial_baud, str(exp), args.duration, start_event, stop_event, args.event_schedule), name='serial_logger')
        sp.start(); processes.append(sp)
    print('\nAll processes launched. Waiting 3 seconds for camera initialization...')
    time.sleep(3.0); print('Starting all cameras now.'); start_wall = time.time(); start_event.set()
    try:
        while time.time() - start_wall < args.duration + 10:
            if not any(pr.is_alive() for pr in processes if pr.name.startswith('camera_')): break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print('\nUser requested stop.'); stop_event.set()
    finally:
        stop_event.set()
        for pr in processes: pr.join(timeout=15)
        for pr in processes:
            if pr.is_alive(): print(f'Terminating {pr.name}'); pr.terminate(); pr.join(timeout=5)
    results = []
    while not result_queue.empty(): results.append(result_queue.get())
    (Path(exp)/'process_results.json').write_text(json.dumps(results, indent=4))
    print('\nProcess results:')
    for r in results: print(r)
    print(f'\nDone. Main experiment folder:\n  {exp}')
    return 1 if any(r.get('exit_code', 1) != 0 for r in results) else 0

if __name__ == '__main__':
    sys.exit(main())
