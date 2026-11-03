"""Approximate payload/FEC budget; never interprets WiFi PHY rate as usable capacity."""
import argparse
import json

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--video-mbps',type=float,default=4)
parser.add_argument('--mtu',type=int,default=1200)
parser.add_argument('--fec-data',type=int,default=8)
parser.add_argument('--fec-total',type=int,default=12)
parser.add_argument('--control-kbps',type=float,default=64)
parser.add_argument('--measured-payload-mbps',type=float)
args=parser.parse_args()
if not 0<args.video_mbps<=50 or not 256<=args.mtu<=1400 or not 1<=args.fec_data<=args.fec_total<=128 or not 0<=args.control_kbps<=1000:parser.error('Invalid budget inputs')
if args.measured_payload_mbps is not None and args.measured_payload_mbps<=0:parser.error('Measured capacity must be positive')
transport=args.video_mbps*(args.mtu+28)/(args.mtu-26)
fec=transport*args.fec_total/args.fec_data
required=fec+args.control_kbps/1000
print(json.dumps(dict(video_mbps=args.video_mbps,rtp_ipv4_udp_estimate_mbps=round(transport,3),
    fec_ratio=args.fec_total/args.fec_data,estimated_required_payload_mbps=round(required,3),
    utilization=round(required/args.measured_payload_mbps,3) if args.measured_payload_mbps else None,
    limitations='Approximation: assumes full FU-A packets, IPv4/UDP and the CameraDrone timestamp extension. Radio/MAC/security/FEC block headers, bitrate bursts and fading need extra margin. Measured payload capacity is not PHY link rate.'),indent=2))
