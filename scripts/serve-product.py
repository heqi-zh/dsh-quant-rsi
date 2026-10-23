"""Read-only localhost report server following the last verified publication."""
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
from dqr.storage import read
from dqr.publication import report_routes,report_folder

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base=ROOT/'data/product'
        pointer=base/'published.json'
        if not pointer.exists():pointer=base/'latest.json'
        if not pointer.exists():self.send_error(503,'Reports are being prepared');return
        info=read(pointer);identity=info['replay_id']
        if not re.fullmatch('[a-f0-9]{64}',identity):self.send_error(500);return
        folder=base/'runs'/identity;path=urlsplit(self.path).path
        if path in ('/','/index.html'):
            self.send_response(302);self.send_header('Location','/daily/'+info['latest_date']+'.html');self.send_header('Cache-Control','no-store');self.end_headers();return
        if not re.fullmatch(r'/(daily|weekly)/\d{4}-\d{2}-\d{2}\.(html|md)',path):self.send_error(404);return
        if (base/'published.json').exists():
            kind,filename=path.lstrip('/').split('/')
            origin=report_routes(base)[kind].get(filename.rsplit('.',1)[0])
            if origin is None:self.send_error(404,'Report date is unavailable');return
            folder=report_folder(base,origin)
        target=folder/path.lstrip('/')
        if not target.is_file():self.send_error(404,'Report date is unavailable');return
        data=target.read_bytes();self.send_response(200);self.send_header('Content-Type',('text/html' if target.suffix=='.html' else 'text/plain')+'; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8768);args=p.parse_args()
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
