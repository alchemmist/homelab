"""Encode ONLY sanitized, uniformly sized loopback screenshot pixels, never arbitrary uploaded video."""
import base64, io, os, subprocess, tempfile
from pathlib import Path
from PIL import Image

def encode(frames, binary="/encoder/ffmpeg"):
    if not isinstance(frames,list) or not 12<=len(frames)<=180:raise ValueError("Need 12..180 real consecutive frames at 6fps")
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp)/"repro.mp4";
        p=None;
        shape=None
        try:
            for b in frames:
                if not isinstance(b,str) or len(b)>180000:raise ValueError("Oversized frame")
                with Image.open(io.BytesIO(base64.b64decode(b,validate=True)),formats=["JPEG"]) as im:
                    w,h=im.size
                    if not (160<=w<=1280 and 120<=h<=800 and w%2==h%2==0):raise ValueError("Bad viewport")
                    if shape is None:
                        shape=im.size;
                        p=subprocess.Popen([binary,"-nostdin","-loglevel","error","-f","rawvideo","-pixel_format","rgb24","-video_size",f"{w}x{h}","-framerate","6","-i","pipe:0","-an","-map_metadata","-1","-threads","2","-c:v","libx264","-preset","ultrafast","-crf","24","-pix_fmt","yuv420p","-movflags","+faststart",str(out)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    if im.size!=shape:raise ValueError("Viewport changed")
                    p.stdin.write(im.convert("RGB").tobytes())
            p.stdin.close()
            if p.wait(timeout=40)!=0 or not 128<out.stat().st_size<=6000000:raise ValueError("Encoder failure/oversize")
            return out.read_bytes()
        finally:
            if p and p.poll() is None:
                p.kill();
                p.wait()
