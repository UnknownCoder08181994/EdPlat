import os
import socket
import subprocess
import time
import pytest


def _port_open(port, host='127.0.0.1'):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


@pytest.fixture(scope='session')
def live_server():
    port = 5099
    env = {**os.environ, 'PORT': str(port), 'FLASK_DEBUG': '1'}
    proc = subprocess.Popen(
        ['python', 'app.py'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(30):
        if _port_open(port):
            break
        time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError('Flask server did not start')

    yield f'http://127.0.0.1:{port}'

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture()
def page(live_server, browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    yield pg, live_server
    pg.close()
    ctx.close()
