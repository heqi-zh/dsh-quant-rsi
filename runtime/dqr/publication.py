"""Resolve already published report dates to their immutable originating runs."""
import re
from .storage import read


def report_routes(base):
    pointer=base/'published.json'
    routes={'daily':{},'weekly':{}}
    if not pointer.exists():return routes
    published=read(pointer)
    if published.get('report_runs'):
        for kind in routes:routes[kind].update(published['report_runs'].get(kind,{}))
        return routes
    identity=published['replay_id'];folder=base/'runs'/identity
    proof=read(folder/'publication-proof.json')
    for item in proof.get('reports',[]):routes[item['kind']][item['date']]=identity
    return routes


def report_folder(base, identity):
    if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{64}',identity):raise ValueError('invalid published report ID')
    return base/'runs'/identity
