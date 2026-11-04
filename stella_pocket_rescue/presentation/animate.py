"""Дописывает в презентацию анимации: переход «Трансформация» (Morph) на каждом слайде и появление
элементов по очереди сразу после перехода. Порядок появления берется из anim.json, который пишет build.js.

Запуск: python presentation/animate.py
Объекты с именем на «!!», которые были на предыдущем слайде, не получают своего появления:
их плавно переносит сам переход «Трансформация».
"""
import json
import pathlib
import re
import shutil
import tempfile
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
DECK = HERE / "Stella_Pocket_Rescue.pptx"

MORPH_MS = 1200
FIRST_DELAY = 250   # мс после перехода до первого появления
STAGGER = 380       # мс между шагами
DUR = {"fade": 500, "rise": 700, "zoom": 500, "wipe": 450}

TRANSITION = (
    '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
    '<mc:Choice xmlns:p159="http://schemas.microsoft.com/office/powerpoint/2015/09/main" Requires="p159">'
    f'<p:transition xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" spd="slow" p14:dur="{MORPH_MS}">'
    '<p159:morph option="byObject"/></p:transition></mc:Choice>'
    '<mc:Fallback><p:transition spd="slow"><p:fade/></p:transition></mc:Fallback></mc:AlternateContent>'
)


class Ids:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


def tgt(spid):
    return f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'


def show(ids, spid):
    return (f'<p:set><p:cBhvr><p:cTn id="{ids()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
            f'{tgt(spid)}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
            '<p:to><p:strVal val="visible"/></p:to></p:set>')


def fade(ids, spid, dur, flt="fade"):
    return (f'<p:animEffect transition="in" filter="{flt}"><p:cBhvr><p:cTn id="{ids()}" dur="{dur}"/>{tgt(spid)}</p:cBhvr></p:animEffect>')


def anim(ids, spid, dur, attr, v0, v1):
    return (f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{ids()}" dur="{dur}" fill="hold"/>{tgt(spid)}'
            f'<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst>'
            f'<p:tav tm="0"><p:val><p:strVal val="{v0}"/></p:val></p:tav>'
            f'<p:tav tm="100000"><p:val><p:strVal val="{v1}"/></p:val></p:tav></p:tavLst></p:anim>')


def effect(ids, spid, kind, delay, first):
    """Один эффект появления в формате PowerPoint (те же presetID, что выбирает сам PowerPoint)."""
    dur = DUR[kind]
    preset = {"fade": (10, 0), "rise": (42, 0), "zoom": (53, 16), "wipe": (22, 8)}[kind]
    node = "afterEffect" if first else "withEffect"
    head = (f'<p:par><p:cTn id="{ids()}" presetID="{preset[0]}" presetClass="entr" presetSubtype="{preset[1]}" fill="hold" '
            f'grpId="0" nodeType="{node}"><p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>')
    body = show(ids, spid)
    if kind == "fade":
        body += fade(ids, spid, dur)
    elif kind == "rise":
        body += fade(ids, spid, dur)
        body += anim(ids, spid, dur, "ppt_x", "#ppt_x", "#ppt_x")
        body += anim(ids, spid, dur, "ppt_y", "#ppt_y+.06", "#ppt_y")
    elif kind == "zoom":
        body += anim(ids, spid, dur, "ppt_w", "0", "#ppt_w")
        body += anim(ids, spid, dur, "ppt_h", "0", "#ppt_h")
        body += fade(ids, spid, dur)
    elif kind == "wipe":
        body += fade(ids, spid, dur, "wipe(left)")
    return head + body + "</p:childTnLst></p:cTn></p:par>"


def timing(entries, shapes):
    """entries: [(spid, kind, delay)] в порядке появления."""
    ids = Ids()
    root, seq, click, inner = ids(), ids(), ids(), ids()
    effects = "".join(effect(ids, spid, kind, delay, i == 0) for i, (spid, kind, delay) in enumerate(entries))
    bld = "".join(f'<p:bldP spid="{spid}" grpId="0" animBg="1"/>' for spid in dict.fromkeys(s for s, _, _ in entries) if shapes[spid] == "sp")
    return (
        f'<p:timing><p:tnLst><p:par><p:cTn id="{root}" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        f'<p:seq concurrent="1" nextAc="seek"><p:cTn id="{seq}" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        f'<p:par><p:cTn id="{click}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
        f'<p:cond evt="onBegin" delay="0"><p:tn val="{seq}"/></p:cond></p:stCondLst><p:childTnLst>'
        f'<p:par><p:cTn id="{inner}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f'{effects}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
        '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
        '</p:childTnLst></p:cTn></p:par></p:tnLst>'
        + (f'<p:bldLst>{bld}</p:bldLst>' if bld else '') + '</p:timing>'
    )


SHAPE_RE = re.compile(r'<p:(sp|pic|cxnSp)>\s*<p:nv\w+Pr><p:cNvPr id="(\d+)" name="([^"]*)"')


def main():
    plan = json.loads((HERE / "anim.json").read_text(encoding="utf-8"))
    src = zipfile.ZipFile(DECK)
    tmp = pathlib.Path(tempfile.mkstemp(suffix=".pptx")[1])
    # слайды обрабатываю строго по номеру: «!!»-объекты сверяются с предыдущим слайдом
    slides = {}
    for item in src.infolist():
        m = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", item.filename)
        if m:
            slides[int(m.group(1))] = src.read(item.filename).decode("utf-8")
    done, prev_names, total = {}, set(), 0
    for k in sorted(slides):
        xml = slides[k]
        assert "<p:transition" not in xml and "<p:timing" not in xml, f"слайд {k} уже с анимацией"
        by_name, kinds = {}, {}
        for typ, spid, name in SHAPE_RE.findall(xml):
            by_name[name] = spid
            kinds[spid] = typ
        entries, t = [], FIRST_DELAY
        for stp in plan[k - 1]:
            added = False
            for name, kind in stp:
                if name.startswith("!!") and name in prev_names:
                    continue  # его переносит «Трансформация»
                assert name in by_name, f"слайд {k}: нет фигуры {name}"
                entries.append((by_name[name], kind, t))
                added = True
            if added:
                t += STAGGER
        extra = TRANSITION + (timing(entries, kinds) if entries else "")
        assert xml.count("</p:clrMapOvr>") == 1
        xml = xml.replace("</p:clrMapOvr>", "</p:clrMapOvr>" + extra)
        done[f"ppt/slides/slide{k}.xml"] = xml.encode("utf-8")
        prev_names = {n for n in by_name if n.startswith("!!")}
        total += len(entries)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            out.writestr(item, done.get(item.filename) or src.read(item.filename))
    src.close()
    shutil.move(tmp, DECK)
    print(f"анимации: {total} появлений, переход «Трансформация» на {len(plan)} слайдах")


if __name__ == "__main__":
    main()
