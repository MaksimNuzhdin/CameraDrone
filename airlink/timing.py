"""Clock-qualified software latency summaries; never converts clock drift to latency."""

def percentile(values,fraction):
    if not values:return None
    values=sorted(values);pos=(len(values)-1)*fraction;lower=int(pos);upper=min(len(values)-1,lower+1)
    return round(values[lower]+(values[upper]-values[lower])*(pos-lower),3)

def latency_summary(values,before,after):
    estimates=dict(p50_ms=percentile(values,.5),p95_ms=percentile(values,.95),min_ms=percentile(values,0),max_ms=percentile(values,1))
    drift=round(abs(after['offset_ns']-before['offset_ns'])/1e6,3) if before and after else None
    uncertainty=(before['offset_uncertainty_ms']+after['offset_uncertainty_ms']) if before and after else None
    reason=None
    if not before or not after or not values:reason='Missing clock calibration or timestamp samples'
    elif drift>uncertainty:reason='Clock offset changed beyond calibration uncertainty; timestamps cannot establish latency'
    elif estimates['p50_ms']<0:reason='Negative median estimate; clock calibration cannot establish latency'
    return dict(definition='Encoder output on Pi to decoded RGB frame on Ubuntu; excludes exposure/ISP/encoding/display',
        samples=len(values),valid=reason is None,invalid_reason=reason,
        **({key:None for key in estimates} if reason else estimates),
        raw_timestamp_estimates_ms=estimates if reason else None,
        clock_before=before,clock_after=after,observed_clock_offset_change_ms=drift)
