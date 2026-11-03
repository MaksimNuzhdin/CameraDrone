"""Bounded nonblocking RFC 6184 H264/RTP sender; no Pi dependencies.

Private RTP extension 0xCD01 contains an unsigned 64-bit Unix send timestamp
in nanoseconds. Unknown extensions can be ignored by normal RTP receivers.
This timestamp starts AFTER encoding; it is not an exposure timestamp.
"""
import ipaddress
import re
import secrets
import socket
import struct
import threading
import time

DESTINATION_NETWORKS=tuple(ipaddress.IPv4Network(cidr) for cidr in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8'))

START_CODE=re.compile(b'\x00\x00\x00\x01|\x00\x00\x01')


def validate_transport(values):
    if not isinstance(values,dict) or set(values)-{'host','port','mtu'}:
        raise ValueError('RTP accepts host, port and mtu')
    host=values.get('host')
    try:address=ipaddress.IPv4Address(host)
    except (ValueError,TypeError):raise ValueError('Use a private unicast IPv4 destination')
    if not isinstance(host,str) or not any(address in network for network in DESTINATION_NETWORKS) or int(address)&255 in (0,255):
        raise ValueError('Use a private unicast IPv4 destination')
    port=values.get('port',5600);mtu=values.get('mtu',1200)
    if isinstance(port,bool) or not isinstance(port,int) or not 1024<=port<=65535:raise ValueError('RTP port must be 1024..65535')
    if isinstance(mtu,bool) or not isinstance(mtu,int) or not 256<=mtu<=1400:raise ValueError('RTP MTU must be 256..1400')
    return dict(host=str(address),port=port,mtu=mtu)


class Packetizer:
    def __init__(self,mtu=1200,sequence=None,ssrc=None,offset=None):
        self.mtu=mtu;self.sequence=secrets.randbits(16) if sequence is None else sequence
        self.ssrc=secrets.randbits(32) if ssrc is None else ssrc
        self.offset=secrets.randbits(32) if offset is None else offset

    def packets(self,frame,timestamp_us,send_ns):
        units=[nal for nal in START_CODE.split(frame) if nal]
        if not START_CODE.match(frame) or not units:raise ValueError('Encoder must supply Annex-B H264')
        timestamp=(self.offset+(int(timestamp_us)*9)//100)&0xffffffff
        limit=self.mtu-24  # RTP fixed header + extension header + uint64 timestamp
        for index,nal in enumerate(units):
            if len(nal)<=limit:
                payloads=[nal]
            else:
                indicator=(nal[0]&0xe0)|28;kind=nal[0]&31;body=memoryview(nal)[1:];chunk=limit-2
                payloads=(bytes((indicator,kind|(0x80 if start==0 else 0)|(0x40 if start+chunk>=len(body) else 0)))+body[start:start+chunk].tobytes() for start in range(0,len(body),chunk))
            # Only the last fragment of the last NAL marks an access-unit boundary.
            sent=0;total=1 if len(nal)<=limit else (len(nal)-1+limit-3)//(limit-2)
            for payload in payloads:
                sent+=1;marker=index==len(units)-1 and sent==total
                header=struct.pack('!BBHIIHHQ',0x90,96|(0x80 if marker else 0),self.sequence,timestamp,self.ssrc,0xCD01,2,send_ns)
                self.sequence=(self.sequence+1)&0xffff
                yield header+payload


class RtpSender:
    def __init__(self,options):
        self.options=validate_transport(options);self.packetizer=Packetizer(self.options['mtu'])
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,256*1024)
        self.socket.setblocking(False)
        self.lock=threading.Lock();self.started=time.monotonic();self.wait_keyframe=True
        self.counts=dict(frames=0,keyframes=0,packets=0,bytes=0,dropped_packets=0,invalid_frames=0)
        self.error=None;self.closed=False

    def outputframe(self,frame,keyframe=True,timestamp=None,**unused):
        if self.closed:return
        if self.wait_keyframe:
            if not keyframe:return
            self.wait_keyframe=False
        stamp=time.time_ns();timestamp=timestamp if timestamp is not None else time.monotonic_ns()//1000
        with self.lock:
            self.counts['frames']+=1;self.counts['keyframes']+=int(keyframe)
            try:
                for packet in self.packetizer.packets(frame,timestamp,stamp):
                    try:
                        size=self.socket.sendto(packet,(self.options['host'],self.options['port']))
                        self.counts['packets']+=1;self.counts['bytes']+=size
                    except OSError as exc:
                        self.counts['dropped_packets']+=1;self.error=str(exc)
            except ValueError as exc:
                self.counts['invalid_frames']+=1;self.error=str(exc)

    def status(self):
        with self.lock:
            elapsed=max(.001,time.monotonic()-self.started)
            return dict(self.counts,seconds=round(elapsed,2),payload_mbit_s=round(self.counts['bytes']*8/elapsed/1e6,3),error=self.error)

    def close(self):
        with self.lock:
            self.closed=True;self.socket.close()
