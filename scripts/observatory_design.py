"""Self-contained night-themed Observatory cards for GitHub README images."""
from html import escape
import xml.etree.ElementTree as ET

COLORS = ['#B794F4', '#60A5FA', '#EC6CB9', '#82D8CF', '#E8C58F', '#9399BD']


def render_cards(snapshot, languages, mobile=False):
    width, height = (600, 688) if mobile else (1200, 404)
    sx, sy = (24, 116) if mobile else (24, 116)
    lx, ly = (24, 400) if mobile else (624, 116)

    def text(x, y, value, size=16, color='#F8FAFC', weight=400, anchor='start'):
        return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
                f'font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>')

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             '<title id="title">GitHub Observatory</title>',
             '<desc id="desc">Public GitHub statistics and language byte distribution. Full data and counting scope are available in the README.</desc>',
             '<defs><linearGradient id="card" x2="1" y2="1"><stop stop-color="#1A173B"/><stop offset="1" stop-color="#14162F"/></linearGradient>',
             '<radialGradient id="glow"><stop stop-color="#B794F4" stop-opacity=".15"/><stop offset="1" stop-color="#B794F4" stop-opacity="0"/></radialGradient>',
             '<style>text{font-family:Segoe UI,Arial,sans-serif}</style></defs>',
             f'<rect width="{width}" height="{height}" rx="20" fill="#030B22"/>',
             f'<ellipse cx="{width/2}" cy="45" rx="290" ry="100" fill="url(#glow)"/>',
             text(width/2, 31, '\u2726 LIVE DEVELOPER ACTIVITY \u2726', 13, COLORS[0], anchor='middle'),
             text(width/2, 66, 'GitHub Observatory', 30, weight=650, anchor='middle'),
             text(width/2, 94, '@'+snapshot['username']+' / PUBLIC GITHUB SNAPSHOT', 12, '#A7B4CE', anchor='middle')]
    for x,y,title in [(sx,sy,'GitHub Statistics'),(lx,ly,'Language Explorer')]:
        parts += [f'<rect x="{x}" y="{y}" width="552" height="264" rx="16" fill="url(#card)" stroke="#2A2358"/>',
                  f'<path d="M{x+24} {y+1}h64" stroke="#B794F4" stroke-opacity=".6"/>',
                  text(x+24,y+36,title,21,weight=600)]
    metrics = snapshot['metrics']
    stats = [('commits',f"Commits / {snapshot['year']}",'Public default branches'),
             ('pull_requests','Pull requests','Authored / all time, all states'),
             ('stars','Stars received','Owned public repositories'),
             ('public_repositories','Public repos','Owned / includes forks')]
    for i,(key,label,note) in enumerate(stats):
        x,y = sx+24+(i%2)*258,sy+77+(i//2)*94
        parts += [text(x,y,label,16,'#B8C0D8'),text(x,y+37,f'{metrics[key]:,}',34,COLORS[i],650),text(x,y+58,note,12,'#A7B4CE')]
    parts.append(f'<path d="M{sx+276} {sy+62}v176" stroke="#2A2358"/>')
    x,y = lx+24,ly+68
    parts += [f'<clipPath id="bar"><rect x="{x}" y="{y}" width="504" height="16" rx="8"/></clipPath>',
              f'<rect x="{x}" y="{y}" width="504" height="16" rx="8" fill="#292542"/>']
    total = sum(percent for _,percent in languages)
    cursor=x
    for i,(name,percent) in enumerate(languages):
        color=COLORS[i%len(COLORS)]
        span=504*percent/total if total else 0
        parts.append(f'<rect x="{cursor:.5f}" y="{y}" width="{span:.5f}" height="16" fill="{color}" clip-path="url(#bar)"/>')
        cursor+=span
        tx,ty=x+(i%2)*258,y+46+(i//2)*34
        label=name if len(name)<=17 else name[:16]+'\u2026'
        share='<0.1%' if percent<.05 else f'{percent:.1f}%'
        parts += [f'<circle cx="{tx+4}" cy="{ty-5}" r="4" fill="{color}"/>',text(tx+16,ty,label,15),text(tx+235,ty,share,15,color,600,'end')]
    if not languages:
        parts.append(text(x,y+60,'No language bytes reported by GitHub.',16,'#A7B4CE'))
    forks='Forks included' if snapshot['include_forks'] else 'Forks excluded'
    parts += [text(x,ly+220,forks+' / owned public repositories',13,'#A7B4CE'),text(x,ly+244,'Share of code bytes, not time or expertise.',13,'#A7B4CE')]
    parts.append('</svg>')
    svg='\n'.join(parts)+'\n'
    ET.fromstring(svg)
    return svg
