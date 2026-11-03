"""Bounded RTP forward-gap accounting, separate from jitterbuffer events.
Later reorders are reported separately and do not subtract earlier forward gaps."""
class SequenceCounter:
    def __init__(self):
        self.sessions={};self.gaps=0;self.reordered=0;self.duplicates=0
    def observe(self,sequence,ssrc):
        previous=self.sessions.get(ssrc)
        if previous is None:
            if len(self.sessions)>=8:self.sessions.pop(next(iter(self.sessions)))
            self.sessions[ssrc]=sequence;return
        delta=(sequence-previous)&0xffff
        if delta==0:self.duplicates+=1
        elif delta<32768:
            self.gaps+=delta-1;self.sessions[ssrc]=sequence
        else:self.reordered+=1
    def status(self):
        return dict(sequence_gaps=self.gaps,reordered_packets=self.reordered,duplicate_packets=self.duplicates)
