"""One Picamera2 encoded output with independent RTP and recording consumers."""
import threading
from picamera2.outputs import Output
from rtp import RtpSender


class CameraOutputs(Output):
    def __init__(self):
        super().__init__();self.needs_pacing=True
        self.lock=threading.RLock();self.rtp=None;self.file=None;self.file_wait_keyframe=True

    def add_rtp(self,options):
        sender=RtpSender(options)
        with self.lock:
            if self.rtp:
                sender.close();raise ValueError('RTP is already active')
            self.rtp=sender
        return sender

    def remove_rtp(self):
        with self.lock:sender=self.rtp;self.rtp=None
        if sender:sender.close()

    def add_file(self,output):
        output.start()
        with self.lock:self.file=output;self.file_wait_keyframe=True

    def remove_file(self):
        with self.lock:output=self.file;self.file=None
        if output:output.stop()

    def outputframe(self,frame,keyframe=True,timestamp=None,packet=None,audio=False):
        if audio:return
        with self.lock:
            if self.rtp:self.rtp.outputframe(frame,keyframe,timestamp)
            if self.file:
                if self.file_wait_keyframe:
                    if not keyframe:return
                    self.file_wait_keyframe=False
                self.file.outputframe(frame,keyframe,timestamp,packet,audio)

    def stop(self):
        try:self.remove_file()
        finally:
            self.remove_rtp();super().stop()
