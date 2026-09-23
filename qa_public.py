"""Static publication gates. Does not export, contact a remote or deploy."""
import json
import re
import shutil
import subprocess
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent

def main():
    page = ROOT / 'dist/index.html'
    # Generic gates, so this script never has to name a private folder.
    # A dated working folder, a Windows path and a vault root would each be a leak.
    body = page.read_text(encoding='utf-8')
    dates = set(re.findall(r'\d{4}-\d{2}-\d{2}', body))
    week0 = json.loads(re.search(r'const DATA = (.*);', body).group(1))['week0']
    print(f'ISO dates in the page: {sorted(dates)}; week 0 is {week0}')
    assert dates <= {week0}, sorted(dates - {week0})
    for label, pattern in [
        ('windows path', r'[A-Za-z]:\\\\?Users'),
        ('vault root', r'TheSystem'),
        ('markdown note path', r'\d0-[a-z]+/'),
    ]:
        hits = re.findall(pattern, body)
        print(f'{label}: {len(hits)} occurrences in dist/index.html')
        assert not hits, hits[:5]
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    prohibited = [p for p in tracked if re.search(r'(^|/)\.env($|\.)|\.blend\d*$|\.mp4$', p, re.I)]
    print(f'git ls-files: {len(tracked)} tracked paths; prohibited .blend/.mp4/.env paths = {prohibited}')
    assert not prohibited
    size = page.stat().st_size
    print(f'dist/index.html: {size} bytes <= 900000 = {size <= 900_000}')
    assert size <= 900_000
    og = ROOT / 'dist/og.jpg'
    with Image.open(og) as im:
        print(f'dist/og.jpg: {im.width}x{im.height}, {og.stat().st_size} bytes')
        assert im.size == (1200, 630) and og.stat().st_size < 200_000
    assert (ROOT / 'dist/.nojekyll').is_file()
    text = page.read_text(encoding='utf-8')
    data = json.loads(re.search(r'const DATA = (.*);', text).group(1))
    assert len(data['nodes']) == 1246
    assert all(re.fullmatch(r'block [1-9][0-9]*', s) for s in data['subs'])
    assert '\u2014' not in text
    assert '<title>Vault City</title>' in text
    assert 'b.title = d' not in text and '</b>${d}' not in text
    assert not re.search(r'\.(mp3|wav|ogg|flac)(?:[\s\'"?]|$)', text)
    print('Public mask, 1246 nodes, metadata, no em dashes, no audio assets: PASS')

if __name__ == '__main__':
    main()
