"""Bounded UDP relay for repeatable packet loss/blackout tests. No NIC changes."""
import argparse
import ipaddress
import json
import random
import socket
import time
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bind',default='127.0.0.1');parser.add_argument('--in-port',type=int,default=5601)
parser.add_argument('--destination',default='127.0.0.1');parser.add_argument('--out-port',type=int,default=5602)
parser.add_argument('--seconds',type=float,default=25);parser.add_argument('--loss',type=float,default=0)
parser.add_argument('--blackout-start',type=float,default=8);parser.add_argument('--blackout-seconds',type=float,default=2)
parser.add_argument('--seed',type=int,default=42);parser.add_argument('--output',type=Path)
args=parser.parse_args()
for address in [args.bind,args.destination]:ipaddress.IPv4Address(address)
if not (1024<=args.in_port<=65535 and 1024<=args.out_port<=65535 and 1<=args.seconds<=3600 and 0<=args.loss<=.5 and args.blackout_start>=0 and args.blackout_seconds>=0):parser.error('Invalid relay limits')
randomizer=random.Random(args.seed);counts=dict(received=0,forwarded=0,blackout_dropped=0,random_dropped=0,send_dropped=0)
with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as source,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as destination:
    source.bind((args.bind,args.in_port));source.settimeout(.1);destination.setblocking(False);started=time.monotonic()
    while time.monotonic()-started<args.seconds:
        try:data,_=source.recvfrom(65535)
        except socket.timeout:continue
        counts['received']+=1;elapsed=time.monotonic()-started
        if args.blackout_start<=elapsed<args.blackout_start+args.blackout_seconds:counts['blackout_dropped']+=1
        elif randomizer.random()<args.loss:counts['random_dropped']+=1
        else:
            try:destination.sendto(data,(args.destination,args.out_port));counts['forwarded']+=1
            except OSError:counts['send_dropped']+=1
report=dict(counts,seconds=round(time.monotonic()-started,3),configured_loss=args.loss,blackout_start_s=args.blackout_start,blackout_duration_s=args.blackout_seconds,seed=args.seed)
if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
