from pynput import keyboard
import os
import json
import time
import threading

base_dir = os.path.dirname(os.path.abspath(__file__))  
root_dir = os.path.abspath(os.path.join(base_dir, ".."))  
socket_path = os.path.join(root_dir, "runtime", "channel.socket")

# State for numeric input
number_buffer = ""
last_input_time = 0
buffer_timeout = 2  # seconds

# Lock to make buffer thread-safe
buffer_lock = threading.Lock()

def send_command(command_dict):
    try:
        with open(socket_path, "w") as sock:
            json.dump(command_dict, sock)
            sock.flush()
            os.fsync(sock.fileno())
        print(f"Sent command: {command_dict}")
    except Exception as e:
        print(f"Failed to send command: {e}")

def reset_number_buffer():
    global number_buffer
    with buffer_lock:
        number_buffer = ""

def buffer_timeout_checker():
    global last_input_time
    while True:
        time.sleep(0.1)
        with buffer_lock:
            if number_buffer and (time.time() - last_input_time > buffer_timeout):
                print("Buffer timeout, clearing input.")
                reset_number_buffer()

# Start the buffer timeout watcher
threading.Thread(target=buffer_timeout_checker, daemon=True).start()

def on_press(key):
    global number_buffer, last_input_time

    print(f"Key pressed: {key}")

    try:
        if hasattr(key, 'char') and key.char is not None:
            if key.char.isdigit():
                with buffer_lock:
                    number_buffer += key.char
                    last_input_time = time.time()
                    print(f"Buffer: {number_buffer}")
                    if len(number_buffer) >= 2:
                        send_command({"command": "direct", "channel": int(number_buffer)})
                        reset_number_buffer()
        else:
            if key == keyboard.Key.up:
                send_command({"command": "up", "channel": -1})
            elif key == keyboard.Key.down:
                send_command({"command": "down", "channel": -1})
            elif key == keyboard.Key.volume_up:
                send_command({"command": "volume_up"})
            elif key == keyboard.Key.volume_down:
                send_command({"command": "volume_down"})
            elif key == keyboard.Key.enter and number_buffer:
                send_command({"command": "direct", "channel": int(number_buffer)})
                reset_number_buffer()
            elif key == keyboard.Key.esc:
                print("Exiting...")
                return False

    except Exception as e:
        print(f"Error handling key: {e}")

with keyboard.Listener(on_press=on_press) as listener:
    listener.join()
