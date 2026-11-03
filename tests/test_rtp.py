"""RTP wire contract: FU-A reconstruction, marker/timestamp/sequence and safety."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'camera_app'))
from rtp import Packetizer,validate_transport

class RtpWireTests(unittest.TestCase):
    def test_fragment_reassembly_and_wire_fields(self):
        sps=b'\x67ABC';idr=b'\x65'+b'XYZ'*2000
        packets=list(Packetizer(256,65535,123,100).packets(b'\0\0\0\1'+sps+b'\0\0\1'+idr,1_000_000,999))
        self.assertGreater(len(packets),20)
        self.assertTrue(all(len(p)<=256 for p in packets))
        for i,p in enumerate(packets):
            version,payload,seq,timestamp,ssrc,extension,words,sent=struct.unpack('!BBHIIHHQ',p[:24])
            self.assertEqual((version,payload&127,timestamp,ssrc,extension,words,sent),(0x90,96,90100,123,0xCD01,2,999))
            self.assertEqual(seq,(65535+i)&65535)
            self.assertEqual(bool(payload&128),i==len(packets)-1)
        self.assertEqual(packets[0][24:],sps)
        fragments=[p[24:] for p in packets[1:]]
        self.assertTrue(fragments[0][1]&128);self.assertTrue(fragments[-1][1]&64)
        self.assertTrue(all(f[0]&31==28 for f in fragments))
        reconstructed=bytes(((fragments[0][0]&0xe0)|(fragments[0][1]&31),))+b''.join(f[2:] for f in fragments)
        self.assertEqual(reconstructed,idr)
    def test_invalid_annex_b(self):
        with self.assertRaises(ValueError):list(Packetizer().packets(b'not H264',0,1))
    def test_transport_validation(self):
        self.assertEqual(validate_transport({'host':'10.0.0.7'})['port'],5600)
        for value in [None,{}, {'host':'8.8.8.8'},{'host':'240.0.0.1'},{'host':'0.0.0.1'},{'host':'192.0.2.1'},{'host':True},{'host':'10.0.0.255'},{'host':'0.0.0.0'},{'host':'224.0.0.1'}, {'host':'169.254.1.2'},{'host':'camera.local'},{'host':'10.0.0.7','port':True},{'host':'10.0.0.7','mtu':1401}]:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_transport(value)

if __name__=='__main__':unittest.main()
