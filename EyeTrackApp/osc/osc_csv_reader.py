import csv
import time
import os
from datetime import datetime
from eye import EyeId
from threading import Lock
from typing import Optional

# This is a test
# Don't known if i need to worry about race conditions here? Probably not? Not a super robust implementation
# Old method was global, kind of weird needed to be fleshed out more
class CSVLogger:
    def __init__(self, eye_id: EyeId): 
        self.eye_id = eye_id
        self.start_time_ms = None # Old: time.time() 
        self.csv_file = None
        self.is_recording = False
        self._lock = Lock()

    def start_recording(self):
        with self._lock:
            if self.is_recording: 
                return

            # reset time each new recording session, reuse old implementation from branch and see
            self.start_time_ms = int(round(time.time() * 1000)) # or time.time() 

            # Reuse previous implementation of log_eye_data
            formatted_timestamp = datetime.now().strftime("%Y-%m-%d_%I-%M-%S")

            folder = "csv_files"
            session_folder = os.path.join(folder, f"session{formatted_timestamp}")

            if not os.path.exists(session_folder): 
                print(f"\033[92m[INFO] Session folder created: {os.getcwd()}\033[0m")
                os.makedirs(folder, exist_ok=True)
            else:
                print(f"\033[93m[WARN] Session folder already exists: {session_folder}\033[0m")

            filename = f"{formatted_timestamp}_{self.eye_id}_eye_data.csv"   
            self.csv_file = os.path.join(folder, filename)

            try: 
                with open(self.csv_file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['timestamp_ms', 'eye_id', 'x', 'y', 'pupil_dilation', 'eye_blink'])
                self.is_recording = True
                print(f"\033[92m[INFO] Started recording {self.eye_id.name} to {filename}\033[0m")
            except Exception as e:
                print(f"\033[91m[ERROR] Failed to start CSV recording: {e}\033[0m")
            

    def stop_recording(self): 
        if self.is_recording:
            self.is_recording = False
            print(f"\033[92m[INFO] Stopped recording {self.eye_id}\033[0m")

    def log_eye_data(self, sender):
        if not self.is_recording:
            return
        
        #elapsed_time_ms = int((time.time() - self.start_time) * 1000)
        elapsed_time_ms = int(round(time.time() * 1000)) - self.start_time_ms

        if self.eye_id == EyeId.LEFT:
            x, y, pupil_dialation, eye_blink = sender.l_eye_x, sender.left_y, sender.l_dilation, sender.l_eye_blink
        elif self.eye_id == EyeId.RIGHT:
            x, y, pupil_dialation, eye_blink = sender.r_eye_x, sender.right_y, sender.r_dilation, sender.r_eye_blink
        elif self.eye_id == EyeId.BOTH: # Going off of the old implementation, just dividing the values by 2 to average them out
            x = (sender.l_eye_x + sender.r_eye_x) / 2
            y = (sender.left_y + sender.right_y) / 2
            pupil_dialation = (sender.l_dilation + sender.r_dilation) / 2
            eye_blink = (sender.l_eye_blink + sender.r_eye_blink) / 2
        else:
            return

        try:
            with self._lock:
                with open(self.csv_file, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([elapsed_time_ms, str(self.eye_id), x, y, pupil_dialation, eye_blink])
        except Exception as e:
            print(f"\033[91m[ERROR] CSV write failed: {e}\033[0m")