#!/usr/bin/env python3
"""Build self-hosted ASCII profile cards and typing GIFs; no external image service."""
import argparse
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'
W, H = 1240, 880
X, Y, STEP = 422, 110, 21
THEMES = {
    'dark': dict(bg='#0d1117', panel='#161b22', border='#30363d', text='#c9d1d9',
                 muted='#8b949e', accent='#ffa657', value='#a5d6ff', green='#7ee787'),
    'light': dict(bg='#ffffff', panel='#f6f8fa', border='#d0d7de', text='#24292f',
                  muted='#57606a', accent='#953800', value='#0550ae', green='#116329'),
}


def api(path):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'ascii-profile-readme'}
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    with urlopen(Request('https://api.github.com/' + path, headers=headers), timeout=30) as response:
        return json.load(response)


def stats_for(config, snapshot=None):
    if snapshot:
        return json.loads(Path(snapshot).read_text())
    user = api(f'users/{config["username"]}')
    repos, page = [], 1
    while True:
        batch = api(f'users/{config["username"]}/repos?per_page=100&page={page}')
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    # Public repositories owned by this user, including forks, matching public_repos.
    return {'repos': user['public_repos'], 'followers': user['followers'],
            'stars': sum(repo['stargazers_count'] for repo in repos),
            'joined': user['created_at'][:4],
            'updated': datetime.now(timezone.utc).strftime('%Y-%m-%d')}


def font_path():
    if os.environ.get('PROFILE_FONT'):
        return os.environ['PROFILE_FONT']
    bundled = ASSETS / 'mono.ttf'
    if bundled.exists():
        return str(bundled)
    try:
        return subprocess.check_output(['fc-match', '-f', '%{file}', 'monospace'], text=True)
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit('Set PROFILE_FONT to a monospace .ttf font path.')


def portrait(config, photo_path=None):
    if not photo_path:
        saved = json.loads((ASSETS / 'portrait-source.json').read_text())
        (ASSETS / 'portrait.txt').write_text('\n'.join(saved['rows']) + '\n')
        return saved['rows'], saved['tones']
    with Image.open(photo_path) as photo:
        width, height = photo.size
        box = tuple(round(v * (width if i % 2 == 0 else height))
                    for i, v in enumerate(config['portrait_crop']))
        grey = ImageOps.autocontrast(photo.crop(box).convert('L'), cutoff=1)
        grey = grey.resize((70, 66), Image.Resampling.LANCZOS)
        mask = Image.new('L', photo.size, 255)
        if config.get('portrait_outline'):
            mask = Image.new('L', photo.size, 0)
            ImageDraw.Draw(mask).polygon([(round(x*width), round(y*height))
                for x, y in config['portrait_outline']], fill=255)
        mask = mask.crop(box).resize((70, 66), Image.Resampling.LANCZOS)
    ramp = ' .,:;irsXA253hMHGS#9B&@'
    rows, tones = [], []
    for y in range(66):
        row, shade = '', []
        for x in range(70):
            value = int(255 * (grey.getpixel((x, y)) / 255) ** 0.7)
            inside = mask.getpixel((x, y)) > 150
            row += ramp[value * (len(ramp)-1) // 255] if inside else ' '
            shade.append(value if inside else 0)
        rows.append(row); tones.append(shade)
    (ASSETS / 'portrait.txt').write_text('\n'.join(rows) + '\n')
    (ASSETS / 'portrait-source.json').write_text(json.dumps({'rows': rows, 'tones': tones}))
    return rows, tones


def portrait_color(theme, value):
    def rgb(color):
        return tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
    bg, fg = rgb(theme['bg']), rgb(theme['value'])
    opacity = 0.22 + 0.78 * (value / 255)
    return '#'+''.join(f'{round(b+(f-b)*opacity):02x}' for b, f in zip(bg, fg))


def lines(config, stats):
    rows = []
    def heading(title):
        rows.append(('heading', title, ''))
    def field(label, value):
        rows.append(('field', label, str(value)))
    def gap():
        rows.append(('gap', '', ''))
    heading(config['username'] + '@github')
    rows.append(('rule', '-' * 76, ''))
    for label, key in [('Name', 'name'), ('Role', 'role'), ('Location', 'location'),
                       ('Experience', 'experience'), ('Work', 'work')]:
        field(label, config[key])
    gap(); heading('Tech stack')
    for label, key in [('Languages', 'languages'), ('Frontend', 'frontend'), ('State', 'state'),
                       ('Styling', 'styling'), ('Backend', 'backend'), ('Realtime', 'realtime'),
                       ('Data', 'databases'), ('DevOps', 'tools')]:
        field(label, config[key])
    gap(); heading('Selected builds')
    field('Naltaky', 'WebRTC video, screen sharing & chat')
    field('Shaheen', 'Next.js 16 + Supabase / 96% less RSC traffic')
    gap(); heading('Contact')
    for label, key in [('Email', 'email'), ('Portfolio', 'portfolio'), ('LinkedIn', 'linkedin'),
                       ('Spoken', 'spoken')]:
        field(label, config[key])
    gap(); heading('GitHub / public stats')
    field('Repos', f"{stats['repos']}    Stars: {stats['stars']}    Followers: {stats['followers']}")
    field('Joined', f"{stats['joined']}    Updated: {stats['updated']} UTC")
    gap(); rows.append(('prompt', '$ ', 'npm run create-something-great'))
    return rows


def content(row):
    kind, label, value = row
    if kind == 'field':
        return label + ': ' + '.' * max(2, 14 - len(label)) + ' ' + value
    return label + value


def chunks(row, theme):
    kind, label, value = row
    if kind == 'field':
        return [(label + ': ', theme['accent']),
                ('.' * max(2, 14 - len(label)) + ' ', theme['muted']),
                (value, theme['value'])]
    if kind == 'prompt':
        return [(label, theme['green']), (value, theme['text'])]
    return [(label, theme['green'] if kind == 'heading' else theme['muted'])]


def svg_card(theme, ascii_rows, tones, rows):
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
           '<title id="title">AbdElrahman Gbr — ASCII developer profile</title>',
           '<desc id="desc">ASCII portrait with frontend development skills, contact details and public GitHub statistics.</desc>',
           f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="16" fill="{theme["bg"]}" stroke="{theme["border"]}"/>',
           f'<path d="M17 1H{W-17}Q{W-1} 1 {W-1} 17V55H1V17Q1 1 17 1" fill="{theme["panel"]}"/>']
    for i, color in enumerate(['#ff5f57', '#febc2e', '#28c840']):
        out.append(f'<circle cx="{28+i*23}" cy="28" r="6" fill="{color}"/>')
    out.append(f'<g font-family="monospace" font-size="15" fill="{theme["text"]}">')
    out.append('<text x="112" y="34">abdelrahman@github: ~ / whoami</text>')
    for i, row in enumerate(ascii_rows):
        for j, char in enumerate(row):
            if char != ' ':
                color = portrait_color(theme, tones[i][j])
                out.append(f'<text x="{30+j*4.8:.1f}" y="{115+i*8.5:.1f}" font-size="8" fill="{color}">{escape(char)}</text>')
    out.append(f'<text x="30" y="704" font-size="13" fill="{theme["muted"]}">./AbdElrahmanGbr</text>')
    for i, row in enumerate(rows):
        x = X
        for text, color in chunks(row, theme):
            if text:
                out.append(f'<text xml:space="preserve" x="{x}" y="{Y+i*STEP+15}" textLength="{len(text)*9}" lengthAdjust="spacingAndGlyphs" fill="{color}">{escape(text)}</text>')
                x += len(text) * 9
    out.append('</g></svg>')
    return '\n'.join(out)


def raster_base(theme, ascii_rows, tones, fonts):
    image = Image.new('RGB', (W, H), theme['bg'])
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, W-2, H-2), 16, fill=theme['bg'], outline=theme['border'])
    draw.rounded_rectangle((2, 2, W-3, 55), 14, fill=theme['panel'])
    draw.rectangle((2, 30, W-3, 55), fill=theme['panel'])
    for i, color in enumerate(['#ff5f57', '#febc2e', '#28c840']):
        cx = 28+i*23
        draw.ellipse((cx-6, 22, cx+6, 34), fill=color)
    draw.text((112, 17), 'abdelrahman@github: ~ / whoami', font=fonts[15], fill=theme['text'])
    for i, row in enumerate(ascii_rows):
        for j, char in enumerate(row):
            if char != ' ':
                draw.text((30+j*4.8, 107+i*8.5), char, font=fonts[8],
                          fill=portrait_color(theme, tones[i][j]))
    draw.text((30, 690), './AbdElrahmanGbr', font=fonts[13], fill=theme['muted'])
    return image


def draw_row(image, row, index, theme, font, limit=None, cursor=False):
    draw = ImageDraw.Draw(image)
    remaining = len(content(row)) if limit is None else limit
    x, y = X, Y + index * STEP
    for text, color in chunks(row, theme):
        visible = text[:max(0, remaining)]
        draw.text((x, y), visible, font=font, fill=color)
        x += draw.textlength(visible, font=font)
        remaining -= len(text)
    if cursor:
        draw.rectangle((round(x)+2, y+3, round(x)+9, y+17), fill=theme['green'])


def gif_card(name, theme, ascii_rows, tones, rows, fonts):
    base = raster_base(theme, ascii_rows, tones, fonts)
    final = base.copy()
    for i, row in enumerate(rows):
        draw_row(final, row, i, theme, fonts[15])
    final.save(ASSETS / f'profile-{name}.png')
    # Start complete so GitHub's still-image previews show all the information.
    frames, durations = [final.copy()], [2500]
    frames.append(base.copy()); durations.append(250)
    for i, row in enumerate(rows):
        text = content(row)
        if not text:
            continue
        for count in range(0, len(text), 9):
            frame = base.copy()
            draw_row(frame, row, i, theme, fonts[15], count, cursor=True)
            frames.append(frame); durations.append(55)
        draw_row(base, row, i, theme, fonts[15])
    for _ in range(3):
        for cursor in (True, False):
            frame = base.copy()
            draw_row(frame, rows[-1], len(rows)-1, theme, fonts[15], cursor=cursor)
            frames.append(frame); durations.append(500)
    frames.append(final); durations.append(7000)
    # One shared palette keeps characters steady and delta frames compact.
    palette = Image.new('P', (1, 1))
    colors = []
    background = tuple(int(theme['bg'][i:i+2], 16) for i in (1, 3, 5))
    for color in [*theme.values(), '#ff5f57', '#febc2e', '#28c840']:
        foreground = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
        for step in range(16):
            colors.extend(round(b+(f-b)*step/15) for b, f in zip(background, foreground))
    palette.putpalette((colors + [0]*768)[:768])
    frames = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    frames[0].save(ASSETS / f'profile-{name}.gif', save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True, disposal=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', help='Use a local statistics JSON file without network access')
    parser.add_argument('--photo', help='Rebuild the ASCII portrait from a local photo (not published)')
    args = parser.parse_args()
    config = json.loads((ROOT / 'profile.json').read_text())
    stats = stats_for(config, args.snapshot)
    ascii_rows, tones = portrait(config, args.photo)
    rows = lines(config, stats)
    fonts = {size: ImageFont.truetype(font_path(), size) for size in (8, 11, 13, 15)}
    for row in rows:
        assert fonts[15].getlength(content(row)) < W-X-25, f'Text too wide: {content(row)}'
    assert Y + len(rows)*STEP < H-25, 'Too many profile rows'
    for name, theme in THEMES.items():
        (ASSETS / f'profile-{name}.svg').write_text(svg_card(theme, ascii_rows, tones, rows))
        gif_card(name, theme, ascii_rows, tones, rows, fonts)
    (ASSETS / 'stats.json').write_text(json.dumps(stats, indent=2) + '\n')
    print('Built dark/light ASCII profile SVGs, previews and typing GIFs.')


if __name__ == '__main__':
    main()
