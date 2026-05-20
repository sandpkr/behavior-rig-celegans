#!/usr/bin/env python3
import csv, json, os, queue, threading, time, traceback
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from pypylon import pylon


def list_cameras():
    tl = pylon.TlFactory.GetInstance(); devices = tl.EnumerateDevices()
    if not devices:
        print('No Basler cameras detected.'); return []
    print('\nDetected Basler cameras:')
    out = []
    for i, d in enumerate(devices):
        info = {'index': i, 'model': d.GetModelName(), 'serial': d.GetSerialNumber(), 'class': d.GetDeviceClass()}
        out.append(info)
        print(f"  [{i}] Model: {info['model']} | Serial: {info['serial']} | Class: {info['class']}")
    print('')
    return out


def choose_camera(serial=None, index=0):
    tl = pylon.TlFactory.GetInstance(); devices = tl.EnumerateDevices()
    if not devices: raise RuntimeError('No Basler cameras detected.')
    if serial:
        for d in devices:
            if d.GetSerialNumber() == str(serial):
                return pylon.InstantCamera(tl.CreateDevice(d)), d
        raise RuntimeError(f"No camera found with serial {serial}. Available: {[d.GetSerialNumber() for d in devices]}")
    if index >= len(devices): raise RuntimeError(f'Camera index {index} requested, only {len(devices)} detected.')
    d = devices[index]
    return pylon.InstantCamera(tl.CreateDevice(d)), d


def safe_set(node, value, name, required=False):
    try:
        node.SetValue(value); print(f'Set {name} = {value}'); return True
    except Exception as e:
        msg = f'Could not set {name}: {e}'
        if required: raise RuntimeError(msg)
        print(msg); return False


def safe_get(node):
    try: return node.GetValue()
    except Exception: return None


def jsonable(x):
    if isinstance(x, (np.integer, np.floating)): return x.item()
    try: json.dumps(x); return x
    except Exception: return str(x)


def grab_value(grab, methods, attrs):
    for m in methods:
        try:
            fn = getattr(grab, m)
            if callable(fn): return fn()
        except Exception: pass
    for a in attrs:
        try: return getattr(grab, a)
        except Exception: pass
    return None


def create_experiment_dir(output, prefix):
    p = Path(output) / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def configure_camera(cam, fps, exposure, width=None, height=None, offset_x=None, offset_y=None, buffers=64):
    cam.Open()
    try:
        cam.MaxNumBuffer = int(buffers)
        print(f'Set MaxNumBuffer = {buffers}')
    except Exception:
        try: cam.MaxNumBuffer.SetValue(int(buffers))
        except Exception as e: print(f'Could not set MaxNumBuffer: {e}')

    safe_set(cam.PixelFormat, 'Mono8', 'PixelFormat', required=True)
    if safe_get(cam.PixelFormat) != 'Mono8':
        raise RuntimeError('This recorder expects Mono8 pixel format.')

    # ROI: set offsets to zero before changing width/height, then set requested offsets.
    if offset_x is not None: safe_set(cam.OffsetX, 0, 'OffsetX preliminary')
    if offset_y is not None: safe_set(cam.OffsetY, 0, 'OffsetY preliminary')
    if width is not None: safe_set(cam.Width, int(width), 'Width')
    if height is not None: safe_set(cam.Height, int(height), 'Height')
    if offset_x is not None: safe_set(cam.OffsetX, int(offset_x), 'OffsetX')
    if offset_y is not None: safe_set(cam.OffsetY, int(offset_y), 'OffsetY')

    safe_set(cam.ExposureTime, float(exposure), 'ExposureTime')
    try: cam.AcquisitionFrameRateEnable.SetValue(True)
    except Exception as e: print(f'Could not enable AcquisitionFrameRate: {e}')
    try: cam.AcquisitionFrameRate.SetValue(float(fps)); print(f'Set AcquisitionFrameRate = {fps}')
    except Exception as e: print(f'Could not set AcquisitionFrameRate: {e}')

    return {
        'width': int(cam.Width.GetValue()), 'height': int(cam.Height.GetValue()),
        'offset_x': safe_get(cam.OffsetX), 'offset_y': safe_get(cam.OffsetY),
        'pixel_format': safe_get(cam.PixelFormat), 'exposure_us': safe_get(cam.ExposureTime),
        'fps': safe_get(cam.AcquisitionFrameRate)
    }


def writer_worker(q, err_event, err, stats, raw_path, csv_path, preview_path, width, height, fps, preview_scale, preview_every, t0_perf):
    preview = None
    try:
        if preview_every and preview_every > 0 and preview_scale > 0:
            pw, ph = max(1, round(width*preview_scale)), max(1, round(height*preview_scale))
            preview = cv2.VideoWriter(str(preview_path), cv2.VideoWriter_fourcc(*'MJPG'), max(1.0, fps/preview_every), (pw, ph), True)
            if not preview.isOpened(): print('Warning: preview writer did not open.'); preview = None
        cols = ['saved_frame_index','acquisition_index','grab_succeeded','status','camera_block_id','camera_timestamp','computer_grab_time_sec','elapsed_grab_sec','computer_write_time_sec','elapsed_write_sec','queue_size_after_get','height','width','nbytes','raw_byte_offset']
        with open(raw_path, 'wb') as rf, open(csv_path, 'w', newline='') as cf:
            w = csv.DictWriter(cf, fieldnames=cols); w.writeheader(); saved = 0; prev_block = None
            while True:
                packet = q.get()
                try:
                    if packet is None: break
                    now = time.time(); elapsed_write = time.perf_counter() - t0_perf; qsize = q.qsize()
                    if not packet['grab_succeeded']:
                        row = {c:'' for c in cols}; row.update({'acquisition_index':packet.get('acquisition_index',''), 'grab_succeeded':0, 'status':'grab_failed', 'computer_write_time_sec':now, 'elapsed_write_sec':elapsed_write, 'queue_size_after_get':qsize, 'height':height, 'width':width, 'nbytes':0})
                        w.writerow(row); stats['failed_grabs'] += 1; continue
                    data = packet['data']; offset = rf.tell(); rf.write(data)
                    block = packet.get('camera_block_id')
                    try:
                        if block is not None:
                            bi = int(block)
                            if prev_block is not None and bi != prev_block + 1:
                                gap = bi - prev_block - 1
                                if gap > 0:
                                    stats['block_id_gap_count'] += gap; stats['block_id_gap_events'] += 1
                            prev_block = bi
                    except Exception: pass
                    w.writerow({'saved_frame_index':saved, 'acquisition_index':packet.get('acquisition_index',''), 'grab_succeeded':1, 'status':'written', 'camera_block_id':block, 'camera_timestamp':packet.get('camera_timestamp',''), 'computer_grab_time_sec':packet.get('computer_grab_time_sec',''), 'elapsed_grab_sec':packet.get('elapsed_grab_sec',''), 'computer_write_time_sec':now, 'elapsed_write_sec':elapsed_write, 'queue_size_after_get':qsize, 'height':height, 'width':width, 'nbytes':len(data), 'raw_byte_offset':offset})
                    if preview is not None and saved % preview_every == 0:
                        frame = np.frombuffer(data, dtype=np.uint8).reshape((height, width))
                        small = cv2.resize(frame, (max(1, round(width*preview_scale)), max(1, round(height*preview_scale))), interpolation=cv2.INTER_AREA)
                        preview.write(cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)); stats['preview_frames'] += 1
                    saved += 1; stats['written_frames'] = saved; stats['max_queue_size_seen'] = max(stats['max_queue_size_seen'], qsize)
                finally:
                    q.task_done()
    except Exception:
        err['writer'] = traceback.format_exc(); err_event.set()
    finally:
        if preview is not None: preview.release()


def record_one_camera_to_folder(role, serial, index, output_dir, duration, fps, exposure, width=None, height=None, offset_x=None, offset_y=None, queue_size=32, queue_timeout=2.0, buffers=64, preview_scale=0.25, preview_every=10, retrieve_timeout_ms=5000, external_start_event=None):
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    cam, dev = choose_camera(serial, index)
    print(f"\n[{role}] Using {dev.GetModelName()} serial {dev.GetSerialNumber()}")
    settings = configure_camera(cam, fps, exposure, width, height, offset_x, offset_y, buffers)
    W, H = settings['width'], settings['height']
    raw_path, csv_path = out/f'{role}_camera_raw_mono8.raw', out/f'{role}_frame_metadata.csv'
    preview_path, config_path, summary_path = out/f'{role}_preview_downsampled.avi', out/f'{role}_recording_config.json', out/f'{role}_recording_summary.json'
    config = {'role':role, 'camera_model':dev.GetModelName(), 'camera_serial':dev.GetSerialNumber(), 'duration_sec':duration, 'requested_fps':fps, 'actual_fps_node_value':jsonable(settings['fps']), 'requested_exposure_us':exposure, 'actual_exposure_us':jsonable(settings['exposure_us']), 'width':W, 'height':H, 'offset_x':jsonable(settings['offset_x']), 'offset_y':jsonable(settings['offset_y']), 'pixel_format':settings['pixel_format'], 'bytes_per_frame_mono8':W*H, 'expected_frames_approx':round(duration*fps), 'expected_raw_size_gb':W*H*round(duration*fps)/(1024**3), 'queue_size_frames':queue_size, 'grab_strategy':'GrabStrategy_OneByOne', 'preview_every':preview_every, 'raw_format_note':'uint8 Mono8 frames sequentially, frame shape = height x width'}
    config_path.write_text(json.dumps(config, indent=4))
    print(f"[{role}] {W} x {H}, approx raw size {config['expected_raw_size_gb']:.2f} GB")

    q = queue.Queue(maxsize=queue_size); err_event = threading.Event(); err = {}
    stats = {'written_frames':0, 'failed_grabs':0, 'preview_frames':0, 'max_queue_size_seen':0, 'block_id_gap_count':0, 'block_id_gap_events':0}
    start_event = external_start_event or threading.Event(); t0_holder = {}
    t0_for_writer = time.perf_counter()
    writer = threading.Thread(target=writer_worker, args=(q, err_event, err, stats, raw_path, csv_path, preview_path, W, H, fps, preview_scale, preview_every, t0_for_writer), daemon=False)
    writer.start()

    acquired = 0; failed = 0; queue_full = False
    if external_start_event is None:
        time.sleep(0.2); start_event.set()
    print(f'[{role}] Waiting for synchronized start...')
    start_event.wait(); t0_wall = time.time(); t0_perf = time.perf_counter(); t0_holder['wall'] = t0_wall
    print(f'[{role}] Recording started.')
    try:
        cam.StartGrabbing(pylon.GrabStrategy_OneByOne)
        while cam.IsGrabbing():
            if time.perf_counter() - t0_perf >= duration or err_event.is_set(): break
            grab = cam.RetrieveResult(int(retrieve_timeout_ms), pylon.TimeoutHandling_ThrowException)
            try:
                now = time.time(); elapsed = time.perf_counter() - t0_perf
                if grab.GrabSucceeded():
                    frame = grab.Array
                    if frame.dtype != np.uint8: frame = frame.astype(np.uint8)
                    packet = {'acquisition_index':acquired, 'grab_succeeded':True, 'status':'grabbed', 'camera_block_id':grab_value(grab, ['GetBlockID'], ['BlockID']), 'camera_timestamp':grab_value(grab, ['GetTimeStamp'], ['TimeStamp']), 'computer_grab_time_sec':now, 'elapsed_grab_sec':elapsed, 'data':frame.tobytes(order='C')}
                    acquired += 1
                else:
                    packet = {'acquisition_index':acquired, 'grab_succeeded':False, 'status':'grab_failed', 'camera_block_id':None, 'camera_timestamp':None, 'computer_grab_time_sec':now, 'elapsed_grab_sec':elapsed, 'data':None}
                    failed += 1
                try: q.put(packet, timeout=queue_timeout)
                except queue.Full:
                    queue_full = True; err['queue'] = 'Frame queue became full. Disk or preview cannot keep up.'; err_event.set(); break
            finally:
                grab.Release()
    except KeyboardInterrupt:
        print(f'[{role}] Stopped by user.')
    except Exception:
        err['grabber'] = traceback.format_exc(); err_event.set()
    finally:
        try:
            if cam.IsGrabbing(): cam.StopGrabbing()
        except Exception: pass
        try: q.put(None, timeout=10)
        except queue.Full:
            time.sleep(1); q.put(None)
        writer.join()
        try: cam.Close()
        except Exception: pass

    actual_duration = time.time() - t0_wall if 'wall' in t0_holder else None
    summary = {'role':role, 'actual_duration_sec':actual_duration, 'acquired_frames':acquired, 'written_frames':stats['written_frames'], 'grab_failed_count':failed + stats['failed_grabs'], 'queue_full_error':queue_full, 'measured_acquisition_fps': acquired/actual_duration if actual_duration else None, 'measured_write_fps': stats['written_frames']/actual_duration if actual_duration else None, 'preview_frames':stats['preview_frames'], 'max_queue_size_seen':stats['max_queue_size_seen'], 'block_id_gap_count':stats['block_id_gap_count'], 'block_id_gap_events':stats['block_id_gap_events'], 'errors':err}
    summary_path.write_text(json.dumps({k: jsonable(v) for k,v in summary.items()}, indent=4))
    print(f"\n[{role}] Done. Acquired={acquired}, Written={stats['written_frames']}, Block gaps={stats['block_id_gap_count']}, Max queue={stats['max_queue_size_seen']}/{queue_size}")
    if err: print(f'[{role}] Errors:', err)
    return 0 if (not err and not queue_full and stats['block_id_gap_count']==0 and acquired==stats['written_frames']) else 1
