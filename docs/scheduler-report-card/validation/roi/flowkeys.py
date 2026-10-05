"""Key behaviour fields of a Flow, from local XML or from Tooling API Metadata JSON, in one comparable shape."""
import json, sys, xml.etree.ElementTree as ET
NS = '{http://soap.sforce.com/2006/04/metadata}'

def _val(v):
    if v is None: return None
    for k in ('stringValue', 'booleanValue', 'numberValue', 'dateTimeValue', 'elementReference'):
        if v.get(k) is not None: return v[k]
    return None

def from_json(md):
    st = md.get('start') or {}
    out = {'status': md.get('status'), 'processType': md.get('processType'),
           'object': st.get('object'), 'triggerType': st.get('triggerType'), 'recordTriggerType': st.get('recordTriggerType'),
           'requireChanged': st.get('doesRequireRecordChangedToMeetCriteria'), 'filterLogic': st.get('filterLogic'),
           'filters': sorted((f['field'], f['operator'], str(_val(f.get('value')))) for f in st.get('filters') or []),
           'scheduledPaths': sorted((p.get('name'), p.get('offsetNumber'), p.get('offsetUnit'), p.get('timeSource'), p.get('recordField'))
                                    for p in st.get('scheduledPaths') or []),
           'decisions': {}}
    for d in md.get('decisions') or []:
        out['decisions'][d['name']] = [(r.get('name'), r.get('conditionLogic'),
            [(c.get('leftValueReference'), c.get('operator'), str(_val(c.get('rightValue')))) for c in r.get('conditions') or []])
            for r in d.get('rules') or []]
    out['actions'] = sorted((a.get('name'), a.get('actionName'),
        tuple(sorted((p['name'], str(_val(p.get('value')))) for p in a.get('inputParameters') or [])))
        for a in md.get('actionCalls') or [])
    return out

def _x2d(e):
    """XML element -> dict/str like the Tooling JSON (lists for repeated tags)."""
    kids = list(e)
    if not kids:
        t = e.text
        if t in ('true', 'false'): return t == 'true'
        try: return float(t) if t and t.replace('.', '', 1).lstrip('-').isdigit() and e.tag.endswith(('numberValue', 'offsetNumber')) else t
        except ValueError: return t
    d = {}
    for k in kids:
        tag = k.tag.replace(NS, '')
        d.setdefault(tag, []).append(_x2d(k))
    LIST = {'filters', 'scheduledPaths', 'decisions', 'rules', 'conditions', 'actionCalls', 'inputParameters'}
    return {k: (v if k in LIST else v[0]) for k, v in d.items()}

def from_xml(path):
    return from_json(_x2d(ET.parse(path).getroot()))

if __name__ == '__main__':
    print(json.dumps(from_xml(sys.argv[1]), indent=1, default=str))
