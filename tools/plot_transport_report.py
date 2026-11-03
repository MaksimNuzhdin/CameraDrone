"""Plot only whitelisted aggregate RTP soak metrics; never includes camera pixels."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('report',type=Path)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();report=json.loads(args.report.read_text());samples=report['samples']
if len(samples)<2:parser.error('At least two samples are required')
minutes=[s['elapsed_s']/60 for s in samples]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(2,2,figsize=(8.5,5.8),sharex=True,layout='constrained')
plots=[('Capture rate','capture_fps','frames / second','#3a714b'),
       ('Pi temperature','temperature_c','degrees C','#a46a22'),
       ('Frame age inside Pi','frame_age_ms','milliseconds','#386d91'),
       ('Cumulative RTP sender rate',None,'Mbit / second','#79639d')]
for ax,(title,key,unit,color) in zip(axes.flat,plots):
    values=[s[key] if key else s['transport']['payload_mbit_s'] for s in samples]
    ax.plot(minutes,values,color=color,linewidth=1.4)
    ax.set_title(title,loc='left',fontweight='bold');ax.set_ylabel(unit);ax.grid(alpha=.18)
    if key=='capture_fps':ax.set_ylim(0,max(35,max(values)+2));ax.axhline(24,color='#b15a4b',linestyle='--',linewidth=.7,label='24 FPS acceptance floor');ax.legend(loc='lower left',frameon=False,fontsize=9)
    if key=='frame_age_ms':ax.set_ylim(bottom=0)
    if key is None:ax.set_ylim(bottom=0)
for ax in axes[-1]:ax.set_xlabel('Elapsed minutes')
fig.suptitle('CameraDrone — Pi 5 / Ethernet / 720p30 / four AI modes',fontsize=14,fontweight='bold')
args.output.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(args.output,dpi=170,facecolor='white');plt.close(fig)
print('Aggregate plot:',args.output)
