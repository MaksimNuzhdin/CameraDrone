"""Bounded asynchronous H.264 recording using GStreamer on the Ubuntu host."""
import queue
import shutil
import subprocess
import threading


class HostRecorder:
    def __init__(self, path, width, height, fps, bitrate):
        if not shutil.which('gst-launch-1.0'):
            raise RuntimeError('GStreamer is required for local H.264 recording')
        self.path = path
        self.queue = queue.Queue(maxsize=4)
        self.dropped = 0
        self.frames = 0
        self.error = None
        self.closed = False
        self.log = path.with_suffix('.encoder.log').open('wb')
        command = ['gst-launch-1.0','-q','fdsrc','fd=0','!',
                   'rawvideoparse',f'width={width}',f'height={height}','format=bgr',f'framerate={fps}/1','!',
                   'videoconvert','!','video/x-raw,format=I420','!','x264enc','tune=zerolatency','speed-preset=ultrafast',
                   f'bitrate={int(bitrate/1000)}',f'key-int-max={fps}','!',
                   'h264parse','!','mp4mux','faststart=true','!', 'filesink',f'location={path}']
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log)
        self.thread = threading.Thread(target=self._write,daemon=True,name='local-encoder')
        self.thread.start()

    def submit(self, frame):
        if self.error:
            raise RuntimeError(self.error)
        try:
            self.queue.put_nowait(frame.copy())
        except queue.Full:
            self.dropped += 1

    def _write(self):
        try:
            while True:
                frame = self.queue.get()
                if frame is None:
                    break
                self.process.stdin.write(frame.tobytes())
                self.frames += 1
        except (OSError, ValueError) as exc:
            self.error = 'Local encoder failed: '+str(exc)
        finally:
            try:
                self.process.stdin.close()
            except OSError:
                pass

    def stop(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.queue.put(None,timeout=3)
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('Local encoder did not finish')
            self.process.wait(timeout=10)
            if self.process.returncode != 0:
                raise RuntimeError('Local encoder exited with an error; see the encoder log')
            if self.error:
                raise RuntimeError(self.error)
        except Exception:
            self.process.kill()
            self.process.wait(timeout=3)
            raise
        finally:
            self.log.close()
