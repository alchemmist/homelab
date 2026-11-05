import datetime
import hashlib
import http.client
import importlib.util
import io
import threading
import unittest
from email.message import Message
from pathlib import Path

spec = importlib.util.spec_from_file_location('gateway', Path(__file__).resolve().parents[1] / 'services/rustfs_gateway/gateway.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
BASE = '/spi/v1/' + 'a'*64 + '/' + 'b'*64 + '/'

class Tests(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(g.valid_key(BASE+'manifest.json'), (BASE+'manifest.json')[1:])
        self.assertTrue(g.valid_key(BASE+'E001-test.json'))
        for tail in ['../manifest.json','%2e%2e/a','E001-a%2fb','E001-a?x=1','E001-a#x','E001-a\\b','E001-a..b','E001-é','manifest.json/']:
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                g.valid_key(BASE+tail)

    def test_sign_vector(self):
        # Determinism and request binding; independent OpenSSL canonical vector below.
        headers = g.sign('GET','http://rustfs:9000/spi-evidence/a','AKID','secret',datetime.datetime(2026,1,2,3,4,5))
        self.assertEqual(headers['x-amz-date'], '20260102T030405Z')
        self.assertEqual(headers['x-amz-content-sha256'], hashlib.sha256(b'').hexdigest())
        self.assertIn('Credential=AKID/20260102/us-east-1/s3/aws4_request', headers['Authorization'])
        self.assertNotEqual(headers['Authorization'], g.sign('GET','http://rustfs:9000/spi-evidence/b','AKID','secret',datetime.datetime(2026,1,2,3,4,5))['Authorization'])
        for url in ['http://rustfs:9000/a?x=1','http://user@rustfs/a','http://rustfs/a#frag']:
            with self.assertRaises(ValueError): g.sign('GET',url,'a','b')

    def test_bounded(self):
        class Response(io.BytesIO):
            status = 200
            headers = Message()
        r = Response(b'abc'); r.headers['Content-Length']='3'
        self.assertEqual(g.bounded(r),b'abc')
        for length, body in [('2', b'abc'), ('4',b'abc'), (str(g.MAX_BYTES+1),b''), ('-1',b''), ('',b'')]:
            r = Response(body); r.headers=Message(); r.headers['Content-Length']=length
            with self.assertRaises(ValueError): g.bounded(r)

    def test_http_auth_and_exact_bytes(self):
        class Reader:
            calls=[]
            def authorized(self,cookie): return cookie == 'valid=1'
            def read(self,key): self.calls.append(key); return b'{"x":1}\n'
        reader=Reader()
        server=g.http.server.HTTPServer(('127.0.0.1',0),g.Handler); server.reader=reader
        worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
        try:
            def request(path, headers={}, method='GET'):
                conn=http.client.HTTPConnection(*server.server_address,timeout=2)
                conn.request(method,path,headers=headers); response=conn.getresponse(); data=response.read(); result=(response.status,dict(response.getheaders()),data); conn.close(); return result
            self.assertEqual(request('/bad', {'X-authentik-username':'owner'})[0],401)
            self.assertEqual(request(BASE+'manifest.json')[0],401)
            self.assertEqual(reader.calls,[])
            self.assertEqual(request('/bad',{'Cookie':'valid=1'})[0],404)
            status,headers,data=request(BASE+'manifest.json',{'Cookie':'valid=1'})
            self.assertEqual(status,200); self.assertEqual(data,b'{"x":1}\n')
            self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
            self.assertEqual(headers['Content-Disposition'],'attachment; filename="manifest.json"')
            self.assertEqual(request(BASE+'manifest.json',{'Cookie':'valid=1'},'PUT')[0],405)
        finally:
            server.shutdown(); server.server_close(); worker.join()

class Integrity(unittest.TestCase):
    def test_reader_checks_manifest_and_file(self):
        import json
        file=b'{"safe":true}'
        doc={'format':'socrat-evidence-v2','event_key':'a'*64,'artifacts':[{'id':'E001','name':'safe.json','stored_chars':len(file),'sha256':hashlib.sha256(file).hexdigest()}]}
        manifest=json.dumps(doc).encode('ascii'); digest=hashlib.sha256(manifest).hexdigest()
        prefix='spi/v1/'+'a'*64+'/'+digest
        reader=object.__new__(g.Reader)
        objects={prefix+'/manifest.json':manifest,prefix+'/E001-safe.json':file}
        reader.object=lambda key:objects[key]
        self.assertEqual(reader.read(prefix+'/E001-safe.json'),file)
        self.assertEqual(reader.read(prefix+'/manifest.json'),manifest)
        objects[prefix+'/E001-safe.json']=b'changed'
        with self.assertRaises(ValueError): reader.read(prefix+'/E001-safe.json')
        with self.assertRaises(ValueError): reader.read(prefix+'/E002-other.json')
        objects[prefix+'/manifest.json']=b'{}'
        with self.assertRaises(ValueError): reader.read(prefix+'/manifest.json')

    def test_redirect_denied(self):
        with self.assertRaises(ValueError): g.NoRedirect().redirect_request(None,None,302,'',{},'http://evil/')

    def test_trusted_auth_response(self):
        import os
        from unittest.mock import patch
        class Response:
            status=204
            headers={'X-authentik-groups':'homelab-owner|other'}
            def __enter__(self): return self
            def __exit__(self,*args): pass
        class HTTP:
            def open(self,req,timeout):
                self.request=req;return response
        response=Response(); http=HTTP()
        with patch.dict(os.environ, {'AUTH_URL':g.ORIGIN+'/outpost.goauthentik.io/auth/nginx','S3_ACCESS_KEY':'reader','S3_SECRET_KEY':'private'}):
            reader=g.Reader(); reader.http=http
        self.assertTrue(reader.authorized('session=valid'))
        self.assertEqual(http.request.get_header('X-original-url'),g.ORIGIN+'/')
        response.headers={'X-authentik-groups':'homelab-observer'}
        self.assertFalse(reader.authorized('session=valid'))
        self.assertFalse(reader.authorized(''))
        self.assertFalse(reader.authorized('a\r\nX-authentik-groups: homelab-owner'))

    def test_signing_against_openssl_canonical_vector(self):
        import subprocess
        def sha(data): return hashlib.sha256(data).hexdigest()
        def hmac_openssl(key,data):
            return subprocess.check_output(['openssl','dgst','-sha256','-mac','HMAC','-macopt','hexkey:'+key.hex(),'-binary'],input=data)
        stamp='20260102T030405Z';scope='20260102/us-east-1/s3/aws4_request'
        canonical=('GET\n/spi-evidence/%C3%A9%20a\n\nhost:rustfs:9000\nx-amz-content-sha256:'+sha(b'')+'\nx-amz-date:'+stamp+'\n\nhost;x-amz-content-sha256;x-amz-date\n'+sha(b''))
        key=b'AWS4secret'
        for part in (b'20260102',b'us-east-1',b's3',b'aws4_request'):key=hmac_openssl(key,part)
        expected=hmac_openssl(key,('AWS4-HMAC-SHA256\n'+stamp+'\n'+scope+'\n'+sha(canonical.encode())).encode()).hex()
        actual=g.sign('GET','http://rustfs:9000/spi-evidence/é a','AKID','secret',datetime.datetime(2026,1,2,3,4,5))
        self.assertTrue(actual['Authorization'].endswith('Signature='+expected))
