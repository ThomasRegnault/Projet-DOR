#!/usr/bin/env python

import yaml
import subprocess
import random
import time
import threading
import re
import uuid
import string
import math
import csv
from concurrent.futures import ThreadPoolExecutor

# -----------------------
# CONFIG
# -----------------------

MESSAGE_TIMEOUT = 10  # seconds

# -----------------------
# GLOBAL STATE
# -----------------------

pending = {}
lock = threading.Lock()

csv_file = None
csv_writer = None
csv_lock = threading.Lock()

# -----------------------
# CSV
# -----------------------

def init_csv(path):
    global csv_file, csv_writer

    csv_file = open(path, "w", newline="")
    csv_writer = csv.writer(csv_file)

    csv_writer.writerow([
        "timestamp",
        "phase",
        "container",
        "type",
        "latency_ms",
        "throughput_kbps",
        "size_bytes"
    ])


def log_csv(row):
    with csv_lock:
        csv_writer.writerow(row)
        csv_file.flush()

# -----------------------
# DOCKER
# -----------------------

def get_container_ports():
    result = subprocess.check_output(
        ["docker", "ps", "--format", "{{.Names}} {{.Ports}}"]
    ).decode().splitlines()

    mapping = {}

    for line in result:
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue

        name, ports = parts

        if name == "server":
            continue

        if "->" in ports:
            host_port = ports.split("->")[0].split(":")[-1]
            mapping[name] = int(host_port)

    return mapping


def wait_for_containers():
    while True:
        mapping = get_container_ports()
        if mapping:
            print(f"Found containers: {list(mapping.keys())}")
            return mapping
        time.sleep(1)

# -----------------------
# TMUX
# -----------------------

def send_tmux_command(container, command):
    subprocess.run([
        "docker", "exec", container,
        "tmux", "send-keys", "-t", "myapp",
        command, "C-m"
    ])

# -----------------------
# NODE CHECK
# -----------------------

def is_container_alive(name):
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True
    )
    return "true" in result.stdout.lower()

# -----------------------
# LOGS
# -----------------------

def follow_logs(container, callback):
    proc = subprocess.Popen(
        ["docker", "logs", "-f", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    for line in proc.stdout:
        callback(container, line.strip())


def log_callback(container, line):
    if not is_container_alive(container):
        print(f"NODE DEAD: {container}")

    if "MSG:" not in line:
        return

    match = re.search(r"MSG:(.*?):(.*?):(.*)", line)
    if not match:
        return

    payload = match.group(3)

    if "|" not in payload:
        return

    msg_id, _ = payload.split("|", 1)

    with lock:
        entry = pending.get(msg_id)

    if not entry:
        return

    now = time.time()

    latency_s = now - entry["time"]
    latency_ms = latency_s * 1000

    size_bytes = entry["size"]

    throughput_kbps = (
        (size_bytes * 8) / latency_s / 1000
        if latency_s > 0 else 0
    )

    print(
        f"{container} -> {latency_ms:.2f} ms | {throughput_kbps:.2f} kbps | {size_bytes} B"
    )

    log_csv([
        now,
        entry["phase"],
        container,
        "MSG",
        latency_ms,
        throughput_kbps,
        size_bytes
    ])

    with lock:
        del pending[msg_id]

# -----------------------
# TIMEOUT WATCHER
# -----------------------

def timeout_watcher():
    while True:
        now = time.time()
        to_remove = []

        with lock:
            for msg_id, entry in pending.items():
                if now - entry["time"] > MESSAGE_TIMEOUT:

                    print(
                        f"TIMEOUT | msg={msg_id} | "
                        f"phase={entry['phase']} | "
                        f"container={entry.get('container','?')}"
                    )

                    log_csv([
                        now,
                        entry["phase"],
                        entry.get("container", "unknown"),
                        "TIMEOUT",
                        0,
                        0,
                        entry["size"]
                    ])

                    to_remove.append(msg_id)

            for msg_id in to_remove:
                del pending[msg_id]

        time.sleep(1)

# -----------------------
# DATA
# -----------------------

def generate_data(data_conf):
    if data_conf.get("value") == "random":
        length_bits = data_conf.get("length", 128)
        length_chars = math.ceil(length_bits / 8)

        charset = string.ascii_letters + string.digits

        return ''.join(random.choice(charset) for _ in range(length_chars))

    elif data_conf.get("value") == "uuid":
        return str(uuid.uuid4())

    return data_conf.get("value", "")

# -----------------------
# HELPERS
# -----------------------

def build_command(template, context):
    cmd = template
    for k, v in context.items():
        cmd = cmd.replace(f"%{k}%", str(v))
    return cmd


def parse_delay(delay_str):
    a, b = map(int, delay_str.split("~"))
    return random.uniform(a, b)


def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# -----------------------
# EXECUTION
# -----------------------

def execute_phase(container_ports, containers, phase_name, cmd_conf, send_func):

    repeat = cmd_conf.get("repeat", 1)
    parallel = cmd_conf.get("parallel", 1)

    tasks = list(range(repeat))
    waves = list(chunked(tasks, parallel))

    for wave in waves:

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = []

            for _ in wave:

                from_c = random.choice(containers)
                to_c = random.choice([c for c in containers if c != from_c])

                msg_id = str(uuid.uuid4())

                data = ""
                if "data" in cmd_conf:
                    data = generate_data(cmd_conf["data"])

                payload = f"{msg_id}|{data}"

                context = {
                    "host": "host.docker.internal",
                    "port": container_ports[to_c],
                    "data": payload
                }

                command = build_command(cmd_conf["command"], context)

                with lock:
                    pending[msg_id] = {
                        "time": time.time(),
                        "size": len(data.encode()),
                        "phase": phase_name,
                        "container": from_c
                    }

                futures.append(
                    executor.submit(send_func, from_c, command)
                )

            for f in futures:
                f.result()

# -----------------------
# QUIT (progressif)
# -----------------------

def run_quit_progressive(containers, cmd_conf, send_func):

    remaining = [c for c in containers if c != "server"]

    def task():
        nonlocal remaining

        with lock:
            if not remaining:
                return
            c = random.choice(remaining)
            remaining.remove(c)

        print(f"QUIT -> {c}")

        send_func(c, "QUIT:")

        time.sleep(1)

        subprocess.run(["docker", "kill", c])

    with ThreadPoolExecutor(max_workers=cmd_conf.get("parallel", 1)) as executor:
        for _ in range(cmd_conf.get("repeat", 1)):
            executor.submit(task)
            time.sleep(0.5)

# -----------------------
# MAIN
# -----------------------

def run_commands(config):

    init_csv(config["commands"].get("outFilePath", "out.csv"))

    container_ports = wait_for_containers()
    containers = list(container_ports.keys())

    # logs
    for c in containers:
        threading.Thread(
            target=follow_logs,
            args=(c, log_callback),
            daemon=True
        ).start()

    # timeout watcher
    threading.Thread(
        target=timeout_watcher,
        daemon=True
    ).start()

    send_func = send_tmux_command

    for phase_name, cmd_conf in config["commands"].items():

        if phase_name == "outFilePath":
            continue

        print(f"\n Phase: {phase_name}")

        if "QUIT" in cmd_conf["command"]:
            run_quit_progressive(containers, cmd_conf, send_func)
        else:
            execute_phase(
                container_ports,
                containers,
                phase_name,
                cmd_conf,
                send_func
            )

# -----------------------
# ENTRY
# -----------------------

def main():
    with open("config.yml") as f:
        config = yaml.safe_load(f)

    run_commands(config)


if __name__ == "__main__":
    main()