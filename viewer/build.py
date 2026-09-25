"""Build private viewer pages or the masked public distribution from data/*.json."""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from design import main as build_design
from page_data import pack_design


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', action='store_true', help='Write masked dist/ only')
    args = parser.parse_args()
    vc = json.loads((ROOT / 'data/vault-city.json').read_text(encoding='utf-8'))
    lay = json.loads((ROOT / 'data/layout.json').read_text(encoding='utf-8'))
    nodes = vc['nodes']
    index = lambda values: list(dict.fromkeys(values))
    districts = sorted(index(n['district'] for n in nodes),
                       key=lambda d: -sum(n['district'] == d for n in nodes))
    blocks = {d: index(n['subdistrict'] for n in nodes if n['district'] == d) for d in districts}
    def sub(n):
        return 'block %d' % (blocks[n['district']].index(n['subdistrict']) + 1) if args.public else n['subdistrict']
    subs = index(sub(n) for n in nodes)
    types = index(n['type'] for n in nodes)
    statuses = index(n['status'] for n in nodes)
    packed = []
    for n in nodes:
        p = lay['pos'][str(n['id'])]
        packed.append([n['id'], districts.index(n['district']), subs.index(sub(n)),
                       n['created'], n['updated'], types.index(n['type']), statuses.index(n['status']),
                       n['retrieval_count'], n['inbound'], n['outbound'], round(p[0], 2), round(p[1], 2)])
    plateaus = {d: {k: round(v, 2) if isinstance(v, float) else v
                    for k, v in info.items() if k != 'streets'} for d, info in lay['districts'].items()}
    data = {'design': pack_design(build_design()), 'week0': vc['week0'], 'weeks': vc['weeks'],
            'districts': districts, 'subs': subs, 'types': types, 'statuses': statuses,
            'nodes': packed, 'edges': vc['edges'], 'plateaus': plateaus,
            'bounds': [round(b, 1) for b in lay['bounds']],
            'streets': [[round(r, 2), w] for r, w in lay['districts']['episodic'].get('streets', [])]}
    blob = json.dumps(data, separators=(',', ':'))
    page = (HERE / 'template.html').read_text(encoding='utf-8').replace('__DATA__', blob)
    for token, name in [('__CITY_LIFE__', 'city-life.js'), ('__RIDE_CAMERA__', 'ride.js'), ('__CITY_AUDIO__', 'city-audio.js'), ('__BEAT__', 'beat.js'), ('__RAVE_LIGHT__', 'rave-light.js'), ('__CROWD__', 'crowd.js'), ('__SOCIETY__', 'society.js'), ('__NATURE__', 'nature.js'), ('__PAGE_DATA__', 'page-data.js'), ('__ROADS__', 'roads.js'), ('__HUD__', 'hud.js'), ('__EXPLORE__', 'explore.js')]:
        page = page.replace(token, (HERE / name).read_text(encoding='utf-8'))
    # Each room is a plain Strudel file, pasteable into strudel.cc and back.
    rooms = {path.stem: path.read_text(encoding='utf-8') for path in sorted((HERE / 'rooms').glob('*.strudel'))}
    page = page.replace('__CITY_ROOMS__', json.dumps(rooms, ensure_ascii=False).replace('</', '<\\/'))
    head, body = page.split('<style>', 1)
    doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
           + head + '</head>\n<body>\n<style>' + body + '\n</body>\n</html>\n')
    if args.public:
        from PIL import Image, ImageOps
        out = ROOT / 'dist'
        out.mkdir(exist_ok=True)
        (out / 'index.html').write_text(doc, encoding='utf-8')
        (out / '.nojekyll').write_text('', encoding='utf-8')
        with Image.open(ROOT / 'final.png') as source:
            cover = ImageOps.fit(source.convert('RGB'), (1200, 630), method=Image.Resampling.LANCZOS)
            for quality in range(88, 29, -5):
                cover.save(out / 'og.jpg', quality=quality, optimize=True, progressive=True)
                if (out / 'og.jpg').stat().st_size < 200_000:
                    break
        assert (out / 'og.jpg').stat().st_size < 200_000, 'Cover exceeds 200 KB'
        print(f"dist/og.jpg: 1200x630, {(out / 'og.jpg').stat().st_size} bytes")
    else:
        out = HERE
        (out / 'artifact.html').write_text(page, encoding='utf-8')
        (out / 'index.html').write_text(doc, encoding='utf-8')
    print(f"{out.name}/index.html: {(out / 'index.html').stat().st_size} bytes, {len(packed)} nodes, {len(data['edges'])} edges")


if __name__ == '__main__':
    main()
