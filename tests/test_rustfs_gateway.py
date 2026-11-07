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

    def test_public_http_preview_ranges_and_exact_bytes(self):
        class Reader:
            calls=[]
            def read(self,key): self.calls.append(key); return b'{"x":1}\n'
        reader=Reader()
        server=g.http.server.HTTPServer(('127.0.0.1',0),g.Handler); server.reader=reader
        worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
        try:
            def request(path, headers=None, method='GET'):
                conn=http.client.HTTPConnection(*server.server_address,timeout=2)
                conn.request(method,path,headers=headers or {}); response=conn.getresponse(); data=response.read(); result=(response.status,dict(response.getheaders()),data); conn.close(); return result
            self.assertEqual(request('/bad')[0],404)
            for path in ['//evil.invalid/a', BASE+'manifest.json?x=1', BASE+'%2e%2e/a']:
                self.assertEqual(request(path)[0],404)
            for headers in [{}, {'Cookie':'untrusted', 'X-authentik-username':'owner'}, {'Accept':'text/html'}]:
                status,h,data=request(BASE+'manifest.json',headers)
                self.assertEqual(status,200); self.assertEqual(data,b'{"x":1}\n')
                self.assertEqual(h['Content-Type'],'application/json; charset=utf-8')
                self.assertEqual(h['Content-Disposition'],'inline; filename="manifest.json"')
                self.assertEqual(h['X-Content-Type-Options'],'nosniff')
                self.assertIn("object-src 'self'",h['Content-Security-Policy'])
                self.assertIn("media-src 'self'",h['Content-Security-Policy'])
                self.assertNotIn('Location',h); self.assertNotIn('Set-Cookie',h)
            status,h,data=request(BASE+'manifest.json',method='HEAD')
            self.assertEqual(status,200);self.assertEqual(data,b'');self.assertEqual(h['Content-Length'],'8')
            status,h,data=request(BASE+'manifest.json',{'Range':'bytes=0-2'})
            self.assertEqual((status,data),(206,b'{"x'));self.assertEqual(h['Content-Range'],'bytes 0-2/8')
            self.assertEqual(request(BASE+'manifest.json',{'Range':'bytes=99-'})[0],416)
            for method in ['PUT','POST','DELETE','PATCH','OPTIONS']:
                self.assertEqual(request(BASE+'manifest.json',method=method)[0],405)
        finally:
            server.shutdown();server.server_close();worker.join()

    def test_preview_type_allowlist(self):
        for name,mime in [('E001-file.pdf','application/pdf'),('E001-file.png','image/png'),('E001-file.mp4','video/mp4')]:
            self.assertEqual(g.presentation(name),(mime,True))
        for name in ['E001-file.html','E001-file.svg','E001-file.js','E001-file.unknown']:
            self.assertEqual(g.presentation(name),('application/octet-stream',False))
        for value in ['bytes=0-1,3-4','bytes=-','bytes=-0','bytes=8-9','bytes=2-1','Bytes=0-1']:
            with self.assertRaises(ValueError):g.byte_range(value,8)
        self.assertEqual(g.byte_range('bytes=-2',8),(6,7))
        self.assertEqual(g.byte_range('bytes=2-',8),(2,7))


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

    def test_public_reader_needs_no_idp_or_cookie(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {'S3_ACCESS_KEY':'reader','S3_SECRET_KEY':'fixture'},clear=True):
            reader=g.Reader()
        self.assertFalse(hasattr(reader,'auth'))
        self.assertFalse(hasattr(reader,'authorized'))

    def test_v3_binary_artifact_integrity(self):
        import json
        body=b'\x89PNG\r\n\x1a\n\xff\x00'
        doc={'format':'socrat-evidence-v3','event_key':'a'*64,'artifacts':[{'id':'E001','name':'image.png','stored_bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}]}
        manifest=json.dumps(doc).encode('ascii');digest=hashlib.sha256(manifest).hexdigest()
        prefix='spi/v1/'+'a'*64+'/'+digest
        reader=object.__new__(g.Reader);objects={prefix+'/manifest.json':manifest,prefix+'/E001-image.png':body};reader.object=lambda key:objects[key]
        self.assertEqual(reader.read(prefix+'/E001-image.png'),body)
        objects[prefix+'/E001-image.png']=b'corrupt'
        with self.assertRaises(ValueError):reader.read(prefix+'/E001-image.png')

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
