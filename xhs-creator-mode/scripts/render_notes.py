#!/usr/bin/env python3
"""Local, deterministic baseline renderer. Human visual/privacy QA is required."""
import argparse
import json
import re
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLORS = {"ink": "#181818", "muted": "#626262", "red": "#B8172B", "line": "#D9D7D3", "paper": "#FDFDFC"}
NO_START = set('，。；：！？、）》】」』〕）”’…,.!?;:)]}')
NO_END = set('（《【「『〔“‘([{')


def color(value):
    return COLORS.get(value, value)


def wrap(draw, s, font, width, stroke=0):
    """Prefer intact Latin words; allow Chinese line breaks; honor explicit newlines."""
    lines = []
    for paragraph in str(s).split('\n'):
        tokens = re.findall(r'[A-Za-z0-9_]+(?:[.\-+/][A-Za-z0-9_]+)*|\s+|.', paragraph)
        line = ''
        for token in tokens:
            if draw.textlength(token, font=font) + 2 * stroke > width:
                raise ValueError(f'Unbreakable text is too wide: {token[:50]}')
            candidate = line + token
            if line and draw.textlength(candidate.rstrip(), font=font) + 2 * stroke > width:
                # Avoid leading punctuation and orphaned opening brackets when possible.
                if token in NO_START and len(line.rstrip()) > 1:
                    old = line.rstrip()
                    tail = old[-1]
                    # Do not split the last letter from an English word.
                    if not tail.isascii():
                        lines.append(old[:-1].rstrip())
                        line = tail + token
                        continue
                if line.rstrip() and line.rstrip()[-1] in NO_END:
                    old = line.rstrip()
                    if draw.textlength(old[-1] + token, font=font) + 2 * stroke <= width:
                        lines.append(old[:-1].rstrip())
                        line = old[-1] + token.lstrip()
                        continue
                lines.append(line.rstrip())
                line = token.lstrip()
            else:
                line = candidate if line else token.lstrip()
        lines.append(line.rstrip())
    return lines


def checked_rect(raw, w, h, label):
    if not isinstance(raw, list) or len(raw) != 4 or any(type(v) is not int for v in raw):
        raise ValueError(f'{label} must contain four integer original-pixel coordinates')
    x1, y1, x2, y2 = raw
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
        raise ValueError(f'{label} outside original image: {raw}, image={w}x{h}')
    return tuple(raw)


def intersects(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def prepare_image(spec, base, width, height, scale):
    path = (base / spec['path']).resolve()
    # RGB copy deliberately discards original metadata in final page export.
    with Image.open(path) as source:
        im = source.convert('RGB')
    w, h = im.size
    crop = checked_rect(spec.get('crop', [0, 0, w, h]), w, h, 'crop')
    masks = [checked_rect(v, w, h, 'mask') for v in spec.get('masks', [])]
    frames = [checked_rect(v, w, h, 'highlight') for v in spec.get('highlights', [])]
    draw = ImageDraw.Draw(im)
    for x1, y1, x2, y2 in masks:
        draw.rectangle((x1, y1, x2-1, y2-1), fill='#D6D6D6')
    cw, ch = crop[2]-crop[0], crop[3]-crop[1]
    ratio = min(width/cw, height/ch)
    if ratio <= 0:
        raise ValueError('Image display size must be positive')
    for frame in frames:
        x1, y1, x2, y2 = frame
        if not (crop[0] <= x1 < x2 <= crop[2] and crop[1] <= y1 < y2 <= crop[3]):
            raise ValueError(f'Highlight not fully inside crop: {frame}')
        if any(intersects(frame, m) for m in masks):
            raise ValueError('Highlight overlaps privacy mask; inspect the requested region')
        draw.rectangle((x1, y1, x2-1, y2-1), outline=COLORS['red'], width=max(2, round(4*scale/ratio)))
    return im.crop(crop).resize((max(1, round(cw*ratio)), max(1, round(ch*ratio))), Image.Resampling.LANCZOS)


class Page:
    def __init__(self, w, h, margin, font_path, index):
        self.w, self.h = w, h
        self.scale = w/1080
        self.m = round(margin*self.scale)
        self.inner = w-2*self.m
        self.im = Image.new('RGB', (w, h), COLORS['paper'])
        self.d = ImageDraw.Draw(self.im)
        self.font_path, self.index = font_path, index
        self.fonts = {}
        self.y = self.px(64)
        self.limit = h-self.px(106)
        self.step = 1

    def px(self, value):
        return round(value*self.scale)

    def font(self, size):
        size = max(1, self.px(size))
        if size not in self.fonts:
            self.fonts[size] = ImageFont.truetype(self.font_path, size, index=self.index)
        return self.fonts[size]

    def ensure(self, bottom):
        if bottom > self.limit:
            raise ValueError(f'Content overflow: bottom={bottom}, allowed={self.limit}. Split page or adjust content.')

    def paragraph(self, text, size=40, fill='ink', x=None, width=None, gap=24, strong=False):
        x = self.m if x is None else x
        width = self.inner if width is None else width
        font = self.font(size)
        stroke = max(1, self.px(1)) if strong else 0
        lines = wrap(self.d, text, font, width, stroke)
        ascent, descent = font.getmetrics()
        advance = max(round(font.size*1.43), ascent+descent)
        for line in lines:
            self.ensure(self.y+advance)
            bbox = self.d.textbbox((0, 0), line, font=font, stroke_width=stroke)
            self.d.text((x, self.y-bbox[1]), line, font=font, fill=color(fill), stroke_width=stroke, stroke_fill=color(fill))
            self.y += advance
        self.y += self.px(gap)

    def line(self):
        self.ensure(self.y+self.px(2))
        self.d.line((self.m,self.y,self.w-self.m,self.y), fill=COLORS['line'], width=max(1,self.px(2)))
        self.y += self.px(28)

    def cover(self, spec):
        raw = spec['title']
        lines = raw if isinstance(raw, list) else raw.split('\n')
        size = spec.get('title_size', 90)
        font = self.font(size)
        while max(self.d.textlength(line, font=font) for line in lines) > self.inner-self.px(40):
            size -= 2
            if size < 36:
                raise ValueError('Cover title too long. Revise or split into lines.')
            font = self.font(size)
        line_h = round(font.size*1.6)
        y0 = self.h//2 - round(len(lines)*line_h/2)
        for i, line in enumerate(lines):
            bbox = self.d.textbbox((0,0), line, font=font, stroke_width=1)
            self.d.text(((self.w-self.d.textlength(line,font=font))/2, y0+i*line_h-bbox[1]), line, font=font, fill=COLORS['ink'], stroke_width=1)
        if spec.get('cover_rules', True):
            for y in [y0-self.px(55), y0+len(lines)*line_h+self.px(25)]:
                self.d.line((self.m,y,self.w-self.m,y), fill=COLORS['red'], width=max(2,self.px(3)))
        return self.im

    def content(self, spec, base, page_no, total):
        if not spec.get('footer', True):
            self.limit = self.h-self.px(70)
        if spec.get('section'):
            self.paragraph(spec['section'], 26, 'muted', gap=24)
            y = self.y
            self.line()
            self.d.line((self.m,y,self.m+self.px(138),y), fill=COLORS['red'], width=self.px(4))
        self.paragraph(spec['title'], spec.get('title_size',68), gap=22, strong=True)
        if spec.get('lead'):
            self.paragraph(spec['lead'], 38, 'muted', gap=44)
        for b in spec.get('blocks', []):
            kind = b['type']
            if kind in ('text','heading'):
                self.paragraph(b['text'], b.get('size',45 if kind=='heading' else 40), b.get('color','ink'), gap=b.get('gap',24), strong=kind=='heading')
            elif kind == 'steps':
                self.step = b.get('start', self.step)
                offset = self.px(94)
                for text in b['items']:
                    f = self.font(36)
                    n = f'{self.step:02d}'
                    bbox = self.d.textbbox((0,0),n,font=f)
                    self.d.text((self.m,self.y-bbox[1]),n,font=f,fill=COLORS['red'],stroke_width=1,stroke_fill=COLORS['red'])
                    self.paragraph(text,b.get('size',40),x=self.m+offset,width=self.inner-offset,gap=b.get('gap',26))
                    self.step += 1
            elif kind == 'image':
                width = min(self.inner, self.px(b.get('width',936)))
                height = self.px(b.get('max_height',650))
                picture = prepare_image(b,base,width,height,self.scale)
                x = self.m+(self.inner-picture.width)//2
                self.ensure(self.y+picture.height+2)
                self.im.paste(picture,(x,self.y))
                self.d.rectangle((x-1,self.y-1,x+picture.width,self.y+picture.height),outline=COLORS['line'],width=1)
                self.y += picture.height+self.px(b.get('gap',35))
            elif kind == 'gap':
                self.y += self.px(b.get('height',32))
            elif kind == 'rule':
                self.line()
            else:
                raise ValueError(f'Unknown block type: {kind}')
        # Trailing spacing need not fit, but rendered content always must.
        if spec.get('footer', True):
            y = self.h-self.px(82)
            self.d.line((self.m,y,self.w-self.m,y), fill=COLORS['line'], width=max(1,self.px(2)))
            f = self.font(26)
            t = f'{page_no:02d} / {total:02d}'
            self.d.text((self.w-self.m-self.d.textlength(t,font=f),y+self.px(15)),t,font=f,fill=COLORS['muted'])
        return self.im


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('plan', type=Path)
    p.add_argument('--font', required=True, help='Path to a licensed local Chinese font file')
    p.add_argument('--font-index', type=int, default=0)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    spec = json.loads(args.plan.read_text(encoding='utf-8'))
    w,h = spec.get('width',1080),spec.get('height',1920)
    margin=spec.get('margin',72)
    pages=spec['pages']
    if not (isinstance(w,int) and isinstance(h,int) and 300<=w<=4320 and 300<=h<=7680 and 30<=margin<=200 and 1<=len(pages)<=60):
        p.error('Invalid canvas dimensions, margin, or page count')
    if args.out.exists() and any(args.out.iterdir()):
        p.error('Output directory must be empty; use a new directory')
    if not Path(args.font).is_file():
        p.error('Font file not found')
    rendered=[]
    for i,s in enumerate(pages,1):
        try:
            page=Page(w,h,margin,args.font,args.font_index)
            rendered.append(page.cover(s) if s.get('cover') else page.content(s,args.plan.parent,i,len(pages)))
        except (ValueError,KeyError,OSError,TypeError) as e:
            p.error(f'Page {i}: {e}')
    args.out.mkdir(parents=True,exist_ok=True)
    paths=[]
    for i,im in enumerate(rendered,1):
        path=args.out/f'{i:02d}.png'
        im.save(path,optimize=True)
        paths.append(path)
    tw=220; th=round(tw*h/w); gap=14; cols=min(4,len(paths)); rows=(len(paths)+cols-1)//cols
    sheet=Image.new('RGB',(cols*tw+(cols+1)*gap,rows*th+(rows+1)*gap),'#E8E7E4')
    for i,im in enumerate(rendered):
        sheet.paste(im.resize((tw,th),Image.Resampling.LANCZOS),(gap+(i%cols)*(tw+gap),gap+(i//cols)*(th+gap)))
    sheet.save(args.out/'overview.jpg',quality=92)
    with zipfile.ZipFile(args.out/'pages.zip','w',zipfile.ZIP_DEFLATED) as z:
        for path in paths:
            z.write(path,path.name)
    print(f'Rendered {len(paths)} pages, {w}×{h}. Open each page and overview for human QA before publishing.')


if __name__ == '__main__':
    main()
