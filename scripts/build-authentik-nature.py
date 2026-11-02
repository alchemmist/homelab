#!/usr/bin/env python3
"""Build reviewed, metadata-free WebP derivatives from the owner's dotfiles Nature set.
Local source changes only; never modifies dotfiles or deploys anything.
Requires Pillow with WebP support. Re-run with the same Pillow/libwebp versions for byte parity.
"""
import base64
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageOps, features, __version__ as pillow_version


def build(source, output):
    folder = source / 'wallpapers/nature/images'
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'})
    if not files:
        raise ValueError('No Nature images found')
    manifest = json.loads((output / 'assets.json').read_text())
    manifest = {k: v for k, v in manifest.items() if not k.startswith('NATURE_')}
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    collection = {'repository': 'https://github.com/alchemmist/dotfiles', 'revision': revision,
                  'sourceDirectory': 'wallpapers/nature/images', 'pillowVersion': pillow_version,
                  'libwebpVersion': features.version('webp'), 'libavifVersion': features.version('avif'),
                  'rights': 'Owner-requested existing wallpaper collection; upstream photo rights are not reassigned.',
                  'photos': []}
    dest = output / 'nature'
    dest.mkdir(parents=True, exist_ok=True)
    seen = set()
    for path in files:
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        if source_hash in seen:
            raise ValueError('Duplicate source image: review selection weights')
        seen.add(source_hash)
        ident = source_hash[:12]
        with Image.open(io.BytesIO(raw)) as image:
            if getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Animated images are not allowed')
            image = ImageOps.exif_transpose(image).convert('RGB')
            record = {'id': ident, 'source': str(path.relative_to(source)), 'sourceSha256': source_hash,
                      'sourceDimensions': list(image.size)}
            for label, width, cap in [('desktop', 1920, 600000), ('mobile', 960, 220000)]:
                derivative = image.copy()
                derivative.thumbnail((width, width), Image.Resampling.LANCZOS)
                for quality in [80, 76, 72, 68]:
                    buf = io.BytesIO()
                    derivative.save(buf, format='WEBP', quality=quality, method=6)
                    content = buf.getvalue()
                    if len(content) <= cap:
                        break
                else:
                    raise ValueError('Derivative too large: ' + path.name)
                name = f'nature-{ident}-{width}.webp'
                (dest / name).write_bytes(content)
                key = 'NATURE_' + ident.upper() + '_' + label.upper()
                manifest[key] = {'path': 'nature/' + name, 'sha256': hashlib.sha256(content).hexdigest()}
                record[label] = key
                record[label + 'Dimensions'] = list(derivative.size)
                record[label + 'Bytes'] = len(content)
                record[label + 'Quality'] = quality
                # AVIF is the preferred transfer; keep the reviewed WebP fallback.
                for avif_quality in [45, 42, 38, 34]:
                    buf = io.BytesIO()
                    derivative.save(buf, format='AVIF', quality=avif_quality, speed=6)
                    avif_content = buf.getvalue()
                    if len(avif_content) <= (220000 if label == 'desktop' else 100000):
                        break
                else:
                    raise ValueError('AVIF derivative exceeds transfer budget')
                avif_name = f'nature-{ident}-{width}.avif'
                (dest / avif_name).write_bytes(avif_content)
                avif_key = key + '_AVIF'
                manifest[avif_key] = {'path': 'nature/' + avif_name, 'sha256': hashlib.sha256(avif_content).hexdigest()}
                record[label + 'Avif'] = avif_key
                record[label + 'AvifBytes'] = len(avif_content)
                record[label + 'AvifQuality'] = avif_quality
            preview=image.copy()
            preview.thumbnail((48,48),Image.Resampling.LANCZOS)
            buf=io.BytesIO();preview.save(buf,format='WEBP',quality=25,method=6)
            tiny=base64.b64encode(buf.getvalue()).decode()
            def url(key):
                item=manifest[key]
                return '/-/quiet-mono/v1/'+item['sha256'][:12]+'-'+Path(item['path']).name
            def layer(label):
                return "background-image:url('"+url(record[label])+"'),url('data:image/webp;base64,"+tiny+"')!important;"+"background-image:image-set(url('"+url(record[label+'Avif'])+"') type('image/avif'),url('"+url(record[label])+"') type('image/webp')),url('data:image/webp;base64,"+tiny+"')!important;"
            css="/* Reviewed scene "+ident+"; same-photo inline preview, no script. */\nbody::before{--qm-scene:"+ident+";"+layer('desktop')+"}\n@media(max-width:700px){body::before{"+layer('mobile')+"}}\n"
            css_name='nature-'+ident+'.css'
            (dest/css_name).write_text(css)
            css_key='NATURE_'+ident.upper()+'_CSS'
            manifest[css_key]={'path':'nature/'+css_name,'sha256':hashlib.sha256(css.encode()).hexdigest()}
            record['sceneCss']=css_key
            record['previewBytes']=len(buf.getvalue())
            record['sceneCssBytes']=len(css.encode())
            collection['photos'].append(record)
    (output / 'assets.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'nature.json').write_text(json.dumps(collection, indent=2) + '\n')
    print(json.dumps({'photos': len(collection['photos']),
                      'derivativeBytes': sum(p['desktopBytes'] + p['mobileBytes'] + p['desktopAvifBytes'] + p['mobileAvifBytes'] for p in collection['photos'])}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'deploy/authentik/quiet-mono')
    args = parser.parse_args()
    build(args.source, args.output)
