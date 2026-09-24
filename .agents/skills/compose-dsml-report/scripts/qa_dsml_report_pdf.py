#!/usr/bin/env python3
"""Render PDF pages, record visual defects, and verify their repair."""
from __future__ import annotations
import argparse, json, re, shutil, subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BBOX_RE=re.compile(r"%%HiResBoundingBox:\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)")
WORD_RE=re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
A4_WIDTH=595.28
A4_HEIGHT=841.89
DEFECT_CATEGORIES={
    "whitespace","page-break","stranded-content","table-wrapping","chart-size",
    "caption","hierarchy","density","clipping","overflow","zoom","other",
}
SEVERITIES={"minor","material"}

def assess_page_boxes(boxes:list[tuple[float,float,float,float]])->list[dict]:
    pages=[]
    for index,(x0,y0,x1,y1) in enumerate(boxes,1):
        width=max(0.0,x1-x0); height=max(0.0,y1-y0)
        occupied=max(0.0,min(1.0,height/A4_HEIGHT)); is_blank=width<=0.5 or height<=0.5
        warnings=[]
        if is_blank: warnings.append("blank_page")
        else:
            if index>1 and occupied<0.48: warnings.append("sparse_page")
            if occupied>0.94: warnings.append("dense_page")
            if x0<8 or y0<8 or x1>A4_WIDTH-8 or y1>A4_HEIGHT-8: warnings.append("content_near_page_edge")
        pages.append({"page":index,"bbox_points":[x0,y0,x1,y1],"occupied_vertical_ratio":round(occupied,3),"is_blank":is_blank,"warnings":warnings})
    return pages

def assess_text_density(texts:list[str])->list[dict[str,Any]]:
    result=[]
    for index,text in enumerate(texts,1):
        words=len(WORD_RE.findall(text)); lines=sum(bool(line.strip()) for line in text.splitlines())
        warnings=[]
        if words<75: warnings.append("very_low_information_density")
        elif words<180 or lines<10: warnings.append("low_information_density")
        result.append({"page":index,"word_count":words,"nonblank_text_lines":lines,"warnings":warnings})
    return result

def semantic_tokens(text:str,markdown:bool=False)->list[str]:
    if markdown:
        text=re.sub(r"<!--.*?-->"," ",text,flags=re.S)
        text=re.sub(r"^\s*\|?\s*:?-{3,}.*$"," ",text,flags=re.M)
        text=re.sub(r"[`#*_>|]"," ",text)
    return [token.lower() for token in WORD_RE.findall(text) if len(token)>1]

def assess_source_consistency(markdown:str,pdf_text:str)->dict[str,Any]:
    source=Counter(semantic_tokens(markdown,markdown=True)); rendered=Counter(semantic_tokens(pdf_text))
    overlap=sum((source & rendered).values()); source_total=sum(source.values()); rendered_total=sum(rendered.values())
    source_recall=overlap/source_total if source_total else 1.0
    extra_ratio=max(0.0,(rendered_total-overlap)/rendered_total) if rendered_total else 1.0
    warnings=[]
    if source_recall<0.88 or extra_ratio>0.25: warnings.append("source_pdf_semantic_mismatch")
    return {"source_token_count":source_total,"pdf_token_count":rendered_total,"source_token_recall":round(source_recall,3),"pdf_extra_token_ratio":round(extra_ratio,3),"warnings":warnings}

def assess_report_density(pages:list[dict],target_min_pages:int|None=None,target_max_pages:int|None=None)->list[str]:
    """Flag page-count compliance that is achieved with materially sparse pages."""
    if target_min_pages is None or target_max_pages is None or not pages:
        return []
    page_count=len(pages)
    underused=sum(bool({"sparse_page","low_information_density","very_low_information_density"}.intersection(page.get("warnings",[]))) for page in pages)
    threshold=max(2,(page_count+3)//4)
    mean_words=sum(page.get("word_count",0) for page in pages)/page_count
    low_density={"low_information_density","very_low_information_density"}
    avoidable_sparse_tail=page_count>target_min_pages and bool(low_density.intersection(pages[-1].get("warnings",[])))
    if target_min_pages<=page_count<=target_max_pages and (underused>=threshold or avoidable_sparse_tail or mean_words<150):
        return ["underfilled_report"]
    return []

def run(command:list[str])->subprocess.CompletedProcess[str]:
    return subprocess.run(command,text=True,capture_output=True,check=False)

def prepare(pdf:Path,out:Path,target_min_pages:int|None=None,target_max_pages:int|None=None,source_markdown:Path|None=None)->int:
    gs=shutil.which("gs")
    if not gs: print("ERROR: Ghostscript is required to render pages and inspect geometry"); return 2
    out.mkdir(parents=True,exist_ok=True)
    bbox=run([gs,"-q","-dNOPAUSE","-dBATCH","-sDEVICE=bbox",str(pdf)])
    if bbox.returncode: print("ERROR: Ghostscript could not inspect the PDF"); return 2
    boxes=[tuple(map(float,m.groups())) for m in BBOX_RE.finditer(bbox.stderr)]
    if not boxes: print("ERROR: no PDF pages were detected"); return 1
    rendered=run([gs,"-q","-dNOPAUSE","-dBATCH","-sDEVICE=png16m","-r144",f"-sOutputFile={out/'page-%03d.png'}",str(pdf)])
    if rendered.returncode: print("ERROR: Ghostscript could not render every PDF page"); return 2
    images=sorted(out.glob("page-*.png"))
    if len(images)!=len(boxes): print(f"ERROR: rendered {len(images)} images for {len(boxes)} pages"); return 1
    contact=None; montage=shutil.which("montage"); magick=shutil.which("magick")
    if montage or magick:
        contact=out/"contact-sheet.png"; command=[montage] if montage else [magick,"montage"]
        command += [str(path) for path in images]
        command += ["-thumbnail","280x400","-background","white","-gravity","center","-extent","300x420","-tile","3x","-geometry","+8+8",str(contact)]
        if run(command).returncode: contact=None
    pages=assess_page_boxes(boxes)
    page_texts=[]
    for page_number in range(1,len(boxes)+1):
        extracted=run([gs,"-q","-dNOPAUSE","-dBATCH",f"-dFirstPage={page_number}",f"-dLastPage={page_number}","-sDEVICE=txtwrite","-sOutputFile=-",str(pdf)])
        page_texts.append(extracted.stdout if extracted.returncode==0 else "")
    for page,text_metrics in zip(pages,assess_text_density(page_texts)):
        page["word_count"]=text_metrics["word_count"]
        page["nonblank_text_lines"]=text_metrics["nonblank_text_lines"]
        page["warnings"].extend(text_metrics["warnings"])
    report_warnings=assess_report_density(pages,target_min_pages,target_max_pages)
    consistency=None
    if source_markdown is not None:
        consistency=assess_source_consistency(source_markdown.read_text(encoding="utf-8"),"\n".join(page_texts))
        report_warnings.extend(consistency["warnings"])
    result={
        "schema_version":"0.2","pdf":str(pdf.resolve()),"page_count":len(images),
        "page_images":[str(path.resolve()) for path in images],
        "contact_sheet":str(contact.resolve()) if contact else None,
        "automated_preflight":{
            "status":"warnings" if any(page["warnings"] for page in pages) or report_warnings else "pass",
            "pages":pages,
            "report_warnings":report_warnings,
            "source_consistency":consistency,
            "target_page_range":[target_min_pages,target_max_pages] if target_min_pages is not None and target_max_pages is not None else None,
            "scope":"Geometry preflight only; it does not establish visual quality.",
        },
        "visual_review":{
            "status":"not_performed","reviewed_pages":[],"defects":[],
            "notes":"Page images have not yet been visually inspected.",
            "required_checks":[
                "page balance and accidental whitespace","sensible page breaks",
                "stranded headings or tiny blocks","table readability and wrapping",
                "chart size and captions","visual hierarchy and density consistency",
                "useful information density when a page target is requested",
                "semantic consistency between the persisted source and PDF",
                "clipping or overflow","reasonable zoom requirement",
            ],
        },
    }
    path=out/"qa.json"; path.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(f"Prepared {len(images)} page images; visual QA remains not_performed")
    print(f"Review: {contact if contact else out}"); print(f"QA record: {path}")
    return 0

def load_defects(path:Path|None)->list[dict[str,Any]]:
    if path is None: return []
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,list): raise ValueError("defects JSON must be an array")
    return value

def validate_defects(defects:list[dict[str,Any]],page_count:int,allow_closed:bool=False)->list[str]:
    errors=[]; seen=set()
    for index,defect in enumerate(defects):
        label=f"defects[{index}]"
        if not isinstance(defect,dict): errors.append(f"{label} must be an object"); continue
        for field in ("id","category","severity","pages","description"):
            if not defect.get(field): errors.append(f"{label}.{field} is required")
        defect_id=str(defect.get("id",""))
        if defect_id in seen: errors.append(f"duplicate defect id: {defect_id}")
        seen.add(defect_id)
        if defect.get("category") not in DEFECT_CATEGORIES: errors.append(f"{label}.category is invalid")
        if defect.get("severity") not in SEVERITIES: errors.append(f"{label}.severity is invalid")
        pages=defect.get("pages")
        if not isinstance(pages,list) or not pages or any(not isinstance(page,int) or page<1 or page>page_count for page in pages): errors.append(f"{label}.pages must contain valid page numbers")
        if len(str(defect.get("description","")).strip())<12: errors.append(f"{label}.description must be specific")
        status=defect.get("status","open")
        if allow_closed:
            if status not in {"resolved","accepted"}: errors.append(f"{label}.status must be resolved or accepted")
            if len(str(defect.get("verification","")).strip())<20: errors.append(f"{label}.verification must explain the final check")
            if status=="accepted" and len(str(defect.get("reason","")).strip())<20: errors.append(f"{label}.reason must justify acceptance")
        elif status!="open":
            errors.append(f"{label}.status must be open during a failed review")
    return errors

def record(path:Path,status:str,notes:str,defects:list[dict[str,Any]]|None=None)->int:
    data=json.loads(path.read_text(encoding="utf-8")); page_count=data.get("page_count",0)
    defects=defects or []
    if len(notes.strip())<30: print("ERROR: visual review requires concrete notes"); return 2
    if status=="fail" and not defects: print("ERROR: a failed review must record actionable defects"); return 2
    if status=="pass" and defects: print("ERROR: a passing review cannot contain open defects"); return 2
    errors=validate_defects(defects,page_count)
    if errors:
        for error in errors: print(f"ERROR: {error}")
        return 2
    blocking={"blank_page","content_near_page_edge"}
    warnings={warning for page in data.get("automated_preflight",{}).get("pages",[]) for warning in page.get("warnings",[])}
    warnings.update(data.get("automated_preflight",{}).get("report_warnings",[]))
    blocking.update({"underfilled_report","source_pdf_semantic_mismatch"})
    if status=="pass" and blocking.intersection(warnings):
        print("ERROR: blocking automated-preflight warnings remain"); return 2
    data["visual_review"]={
        "status":status,"reviewed_pages":list(range(1,page_count+1)),
        "defects":defects,"notes":notes.strip(),
        "reviewed_at":datetime.now(timezone.utc).isoformat(),
        "required_checks":data.get("visual_review",{}).get("required_checks",[]),
    }
    path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    print(f"Recorded visual QA status {status} for {page_count} pages and {len(defects)} defects")
    return 0

def verify(prior_path:Path,current_path:Path,resolutions:list[dict[str,Any]],notes:str)->int:
    prior=json.loads(prior_path.read_text(encoding="utf-8")); current=json.loads(current_path.read_text(encoding="utf-8"))
    prior_defects=prior.get("visual_review",{}).get("defects",[])
    if prior.get("visual_review",{}).get("status")!="fail" or not prior_defects:
        print("ERROR: prior QA must be a failed review with defects"); return 2
    if current.get("visual_review",{}).get("status")!="pass":
        print("ERROR: current QA must first pass a full page-image review"); return 2
    errors=validate_defects(resolutions,current.get("page_count",0),allow_closed=True)
    prior_ids={str(item.get("id")) for item in prior_defects if isinstance(item,dict)}
    resolution_ids={str(item.get("id")) for item in resolutions if isinstance(item,dict)}
    if prior_ids!=resolution_ids: errors.append(f"resolutions must cover exactly the prior defects: {sorted(prior_ids)}")
    if len(notes.strip())<30: errors.append("verification requires concrete final notes")
    if errors:
        for error in errors: print(f"ERROR: {error}")
        return 2
    current["visual_review"]["verified_defects"]=resolutions
    current["visual_review"]["supersedes"]=str(prior_path.resolve())
    current["visual_review"]["verification_notes"]=notes.strip()
    current["visual_review"]["verified_at"]=datetime.now(timezone.utc).isoformat()
    current_path.write_text(json.dumps(current,indent=2)+"\n",encoding="utf-8")
    print(f"Verified {len(resolutions)} prior visual defects against the final render")
    return 0

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest="command",required=True)
    prep=sub.add_parser("prepare"); prep.add_argument("pdf",type=Path); prep.add_argument("--output-dir",required=True,type=Path)
    prep.add_argument("--target-min-pages",type=int); prep.add_argument("--target-max-pages",type=int)
    prep.add_argument("--source-markdown",type=Path)
    rec=sub.add_parser("record"); rec.add_argument("qa_json",type=Path); rec.add_argument("--status",choices=("pass","fail"),required=True); rec.add_argument("--notes",required=True); rec.add_argument("--defects-json",type=Path)
    ver=sub.add_parser("verify"); ver.add_argument("prior_qa_json",type=Path); ver.add_argument("current_qa_json",type=Path); ver.add_argument("--resolutions-json",required=True,type=Path); ver.add_argument("--notes",required=True)
    args=parser.parse_args()
    try:
        if args.command=="prepare":
            if (args.target_min_pages is None)!=(args.target_max_pages is None):
                print("ERROR: provide both --target-min-pages and --target-max-pages"); return 2
            if args.target_min_pages is not None and (args.target_min_pages<1 or args.target_max_pages<args.target_min_pages):
                print("ERROR: target page range is invalid"); return 2
            return prepare(args.pdf,args.output_dir,args.target_min_pages,args.target_max_pages,args.source_markdown)
        if args.command=="record": return record(args.qa_json,args.status,args.notes,load_defects(args.defects_json))
        return verify(args.prior_qa_json,args.current_qa_json,load_defects(args.resolutions_json),args.notes)
    except (OSError,UnicodeError,json.JSONDecodeError,ValueError) as exc:
        print(f"ERROR: {exc}"); return 2

if __name__=="__main__": raise SystemExit(main())
