"""Pre-render lossless screen sizes. Square center crops omit off-screen pixels on phones."""
import io
import json
from PIL import Image, ImageOps

WIDTHS = (480, 768, 1280, 1920, 2560)

def key(i, tag):
    return f'responsive/{i}/{tag}.webp'

def generate(store, i, raw):
    with Image.open(io.BytesIO(raw)) as image:
        original = ImageOps.exif_transpose(image).convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
        profile = image.info.get('icc_profile', b'')
    manifest = []
    for square in (False, True):
        if square and original.width <= original.height:
            continue
        base = ImageOps.fit(original, (original.height, original.height)) if square else original
        widths = [w for w in WIDTHS if w < base.width]
        if square:
            widths.append(base.width)
        for w in widths:
            h = max(1, round(w * base.height / base.width)); tag = ('s' if square else 'w') + str(w)
            result = base.resize((w, h), Image.Resampling.LANCZOS); buf = io.BytesIO()
            result.save(buf, 'WEBP', lossless=True, exact=True, method=3, icc_profile=profile)
            store.put(key(i, tag), buf.getvalue(), 'image/webp'); manifest.append([tag,w,h])
    store.put(f'responsive/{i}/index.json', json.dumps(manifest).encode(), 'application/json')

def variants(store, i):
    try: return json.loads(store.get(f'responsive/{i}/index.json'))
    except Exception: return []

def rules(i, manifest):
    out=[]
    for tag,w,h in reversed(manifest):
        if tag.startswith('s'): continue
        out.append(rule(i,tag,w,h,''))
    for tag,w,h in reversed(manifest):
        if tag.startswith('s'):
            out.append(rule(i,tag,w,h,'(orientation: portrait) and ', native=(tag==manifest[-1][0])))
    return ''.join(out)

def rule(i,tag,w,h,prefix,native=False):
    query = '(orientation: portrait)' if native else ','.join(f'{prefix}(max-resolution:{d}dppx) and (max-width:{w/d:g}px) and (max-height:{h/d:g}px)' for d in (1,1.5,2,3,4))
    return f'@media {query}{{body::before{{--wp-photo:url("/wallpapers/media/{i}-{tag}.webp")}}}}\n'
