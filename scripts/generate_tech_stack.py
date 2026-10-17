"""Render the profile's static tech stack with locally embedded Devicon logos."""
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
GROUPS = [
    ('Languages I Know', [
        ('TypeScript', 'typescript'), ('JavaScript', 'javascript'),
        ('Python', 'python'), ('Java', 'java'), ('C#', 'csharp'), ('Dart', 'dart'),
    ]),
    ('Web, Data & Tools', [
        ('HTML5', 'html5'), ('CSS3', 'css3'), ('PostgreSQL', 'postgresql'),
        ('Docker', 'docker'), ('Git', 'git'), ('GitHub', 'github'),
    ]),
]


def render():
    width, cols = 1200, 6
    height = 340
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             '<title id="title">Languages &amp; Tech Stack</title>',
             '<desc id="desc">Languages: TypeScript, JavaScript, Python, Java, C#, Dart. Web, data and tools: HTML5, CSS3, PostgreSQL, Docker, Git, GitHub.</desc>',
             '<defs><linearGradient id="tile" x2="1" y2="1"><stop stop-color="#1A173B"/><stop offset="1" stop-color="#14162F"/></linearGradient></defs>',
             '<style>text{font-family:Segoe UI,Arial,sans-serif}</style>',
             f'<rect width="{width}" height="{height}" rx="20" fill="#030B22"/>']

    def text(x, y, value, size, color='#F8FAFC', anchor='start', weight=400):
        return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{escape(value)}</text>'

    parts += [text(width / 2, 31, '✦ MY DEVELOPER TOOLKIT ✦', 13, '#B794F4', 'middle'),
              text(width / 2, 69, 'Languages & Tech Stack', 30, anchor='middle', weight=650)]
    tile_width = (width - 48 - (cols - 1) * 12) / cols
    for group_index, (heading, technologies) in enumerate(GROUPS):
        top = 82 + group_index * 114
        for i, (label, slug) in enumerate(technologies):
            x, y = 24 + (i % cols) * (tile_width + 12), top + 18 + (i // cols) * 114
            parts.append(f'<rect x="{x}" y="{y}" width="{tile_width}" height="102" rx="14" fill="url(#tile)" stroke="#2A2358"/>')
            logo = ET.parse(ROOT / 'assets' / 'tech-logos' / f'{slug}.svg').getroot()
            logo.set('x', str(x + (tile_width - 40) / 2))
            logo.set('y', str(y + 15))
            logo.set('width', '40')
            logo.set('height', '40')
            if slug == 'github':
                for node in logo.iter():
                    if node.tag.endswith('path'):
                        node.set('fill', '#F8FAFC')
            parts.append(ET.tostring(logo, encoding='unicode'))
            parts.append(text(x + tile_width / 2, y + 81, label, 16, anchor='middle', weight=600))
    parts.append('</svg>')
    result = '\n'.join(parts) + '\n'
    ET.fromstring(result)
    return result


if __name__ == '__main__':
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    (ROOT / 'assets' / 'tech-stack.svg').write_text(render(), encoding='utf-8', newline='\n')
