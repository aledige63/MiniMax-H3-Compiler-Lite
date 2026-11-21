import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request


class ServiceRestartTests(unittest.TestCase):
    def test_busy_port_and_archive_are_rejected_and_service_can_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, "-X", "utf8", "-m", "scripts.serve", "--data-dir", directory]
            with socket.socket() as occupied:
                occupied.bind(("127.0.0.1", 0))
                occupied.listen()
                port = occupied.getsockname()[1]
                busy = subprocess.run([*command, "--port", str(port)], capture_output=True,
                                      encoding='utf-8', timeout=10)
                self.assertEqual(busy.returncode, 1)
                self.assertIn("non disponibile", busy.stderr)

            windows = sys.platform == 'win32'
            for attempt in range(2):
                if attempt and windows:
                    # After forced termination Winsock may retain the old port.
                    # Reopen the same archive on another port to verify lock release.
                    with socket.socket() as free:
                        free.bind(("127.0.0.1", 0))
                        port = free.getsockname()[1]
                process = subprocess.Popen([*command, "--port", str(port)], stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 10
                    while True:
                        if process.poll() is not None:
                            self.fail(process.stdout.read().decode())
                        try:
                            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=.5) as page:
                                self.assertEqual(page.status, 200)
                                self.assertIn(b"<!doctype html", page.read().lower())
                            break
                        except (urllib.error.URLError, TimeoutError):
                            if time.monotonic() >= deadline:
                                self.fail("Il servizio non risponde dopo l'avvio")
                            time.sleep(.02)
                    other_port = 8769 if port != 8769 else 8770
                    duplicate = subprocess.run([*command, "--port", str(other_port)], capture_output=True,
                                               encoding='utf-8', timeout=10)
                    self.assertEqual(duplicate.returncode, 1)
                    self.assertIn('usa già questo archivio', duplicate.stderr)
                finally:
                    process.terminate()
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                expected = (0, 1) if windows else (0, -signal.SIGTERM)
                self.assertIn(process.returncode, expected)


if __name__ == "__main__":
    unittest.main()
