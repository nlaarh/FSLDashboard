import sys, os, json
os.chdir('/Users/alaaroubi/Library/CloudStorage/OneDrive-AAAWesternandCentralNewYork/AAA/Dev/FSL/FSL/apidev/FSLAPP')
sys.path.insert(0,'backend')
import sf_client
from sf_client import sf_query_all, sf_query, sf_rest_get
SP=os.environ.get('RC_SCRATCH','/tmp/rc')  
T='0HhPb00000007s3KAA'
def save(n,o): json.dump(o,open(f'{SP}/{n}.json','w'),default=str)
def load(n): return json.load(open(f'{SP}/{n}.json'))
def desc(obj, pat=None):
    d=sf_rest_get(f'/services/data/v65.0/sobjects/{obj}/describe')
    out=[]
    for f in d['fields']:
        if pat is None or any(p.lower() in f['name'].lower() for p in pat):
            out.append((f['name'],f['type'],f.get('calculated'),f.get('referenceTo')))
    return out
