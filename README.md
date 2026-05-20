# behavior-rig-celegans

Thermotaxis Basler acquisition code

Files:
- one_camera_record.py: single-camera recorder. Start here.
- three_camera_record.py: three-camera recorder. One process per camera.
- thermotaxis_camera_common.py: shared camera functions.
- opto_schedule_example.json: future optogenetic LED schedule example.

Install:
python3 -m pip install pypylon numpy opencv-python pyserial

List cameras:
python3 one_camera_record.py --list

One-camera small test:
python3 one_camera_record.py --duration 10 --fps 14 --width 1920 --height 1080 --output /Users/sk3526/Desktop/basler_test

One-camera full-resolution test:
python3 one_camera_record.py --duration 30 --fps 14 --output /Users/sk3526/Desktop/basler_test

Three-camera small test:
python3 three_camera_record.py --left_serial SERIAL_LEFT --center_serial SERIAL_CENTER --right_serial SERIAL_RIGHT --duration 10 --fps 14 --width 1920 --height 1080 --output /Users/sk3526/Desktop/tri_cam_test

Three-camera full-resolution test without preview:
python3 three_camera_record.py --left_serial SERIAL_LEFT --center_serial SERIAL_CENTER --right_serial SERIAL_RIGHT --duration 30 --fps 14 --preview_every 0 --output /Users/sk3526/Desktop/tri_cam_test

With optional Arduino/Teensy serial logging:
python3 three_camera_record.py --left_serial SERIAL_LEFT --center_serial SERIAL_CENTER --right_serial SERIAL_RIGHT --duration 30 --fps 14 --preview_every 0 --serial_port "/dev/tty.usbmodem*" --serial_baud 9600 --output /Users/sk3526/Desktop/tri_cam_test

With future opto schedule:
python3 three_camera_record.py --left_serial SERIAL_LEFT --center_serial SERIAL_CENTER --right_serial SERIAL_RIGHT --duration 180 --fps 14 --preview_every 0 --serial_port "/dev/tty.usbmodem*" --event_schedule opto_schedule_example.json --output /Users/sk3526/Desktop/tri_cam_test

Important checks after recording:
- block_id_gap_count = 0
- acquired_frames == written_frames
- max_queue_size_seen well below queue_size

Notes:
- Raw files are uint8 Mono8 frames stored sequentially.
- Offline stitching/tracking should happen later, not during acquisition.
- For true camera synchronization, eventually use a shared hardware TTL trigger.
- For optogenetics, update Arduino/Teensy firmware later to accept LED RED/BLUE ON/OFF commands or use TTL outputs.
