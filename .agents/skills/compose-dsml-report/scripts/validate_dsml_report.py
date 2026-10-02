#!/usr/bin/env python3
"""Validate DS/ML report evidence, plan, source, and revision history."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from typing import Any

CLAIM_STATUSES={"Verified","Inferred","Unknown","Recommendation"}
LEVELS={"Low","Medium","High"}
PROFILES={"quick","standard","publication"}
DETAIL_LEVELS={"compact","normal","deep"}
SECTION_ROLES={"executive-summary","context","data","model","features","evaluation","findings","actions","conclusion","appendix","other"}
REVIEW_SURFACES={"architecture","content","content-depth","visual","final-consistency"}
COVERAGE_STATUSES={"sufficient","weak","unavailable"}
AVAILABILITY={"available","unavailable","not_applicable"}
CORE_DEPTH_DIMENSIONS={
    "mechanism","empirical_support_status","evidence_interpretation","implication",
}
CONDITIONAL_DEPTH_DIMENSIONS={
    "assumptions","applicability","failure_modes","interactions",
    "claim_type_separation","omitted_state_reasoning",
}
DEPTH_DEFECT_DETECTORS={"descriptive_only","inventory_without_interpretation"}
DEPTH_REVIEW_DIMENSIONS=(
    CORE_DEPTH_DIMENSIONS|CONDITIONAL_DEPTH_DIMENSIONS|DEPTH_DEFECT_DETECTORS
)
SEMANTIC_PATTERNS={
    "mechanism":re.compile(r"\b(because|mechanism|relies on|allows?|enables?|exposes?|captures?|feeds?|so that|by using|by pooling)\b",re.I),
    "applicability":re.compile(r"\b(when|if|under|condition|regime|assum|requires?|depends? on)\b",re.I),
    "failure":re.compile(r"\b(fail|limitation|risk|break|mislead|sensitive|unstable|drift|leak|redundan|overfit|noise|stale)\w*",re.I),
    "evidence":re.compile(r"\b(evidence|observed|measured|experiment|ablation|importance|artifact|validated|unvalidated|unknown|not established|not measured|no .* available)\b",re.I),
    "implication":re.compile(r"\b(implication|therefore|means|confidence|next step|decision|establish|supports?|weakens?|so what)\b",re.I),
}
BANNED_HEADINGS={"additional findings","additional high-confidence findings","more issues found","further findings"}
PROVENANCE_HEADINGS={"evidence inventory","evidence classification","provenance","repository provenance","methodology and provenance"}
HEADING_RE=re.compile(r"^(#{1,6})\s+(.+?)\s*$")
STATE_REVISION_RE=re.compile(r"<!--\s*dsml-report-state-revision:\s*([^\s]+)\s*-->")
PLAN_REVISION_RE=re.compile(r"<!--\s*dsml-report-plan-revision:\s*([^\s]+)\s*-->")

def canonical_heading(value:str)->str:
    value=re.sub(r"\s+\{[^}]+\}\s*$","",value)
    value=value.replace("\u2014","-").replace("\u2013","-")
    value=re.sub(r"[*_]","",value)
    return re.sub(r"\s+"," ",value.strip().lower())

def headings(markdown:str)->list[tuple[int,str,int]]:
    result=[]; fenced=False
    for number,line in enumerate(markdown.splitlines(),1):
        if line.lstrip().startswith(("~~~","\x60\x60\x60")):
            fenced=not fenced; continue
        if not fenced:
            match=HEADING_RE.match(line)
            if match: result.append((len(match.group(1)),canonical_heading(match.group(2)),number))
    return result

def nonempty(value:Any)->bool:
    return bool(value.strip()) if isinstance(value,str) else value is not None and value!=[] and value!={}

def require_fields(item:Any,fields:tuple[str,...],label:str,errors:list[str])->None:
    if not isinstance(item,dict): errors.append(f"{label} must be an object"); return
    for field in fields:
        if field not in item or not nonempty(item[field]): errors.append(f"{label}.{field} is required")

def normalize_findings(state:dict[str,Any])->list[dict[str,Any]]:
    if isinstance(state.get("findings"),list):
        return [item for item in state["findings"] if isinstance(item,dict)]
    return [{
        "id":item.get("id"),"topic":item.get("class"),"title":item.get("title"),
        "claim_status":"Verified","evidence":item.get("evidence"),
        "consequence":item.get("consequence"),"recommended_action":item.get("first_action"),
        "confidence":item.get("confidence"),
    } for item in state.get("issues",[]) if isinstance(item,dict)]

def evidence_items(state:dict[str,Any])->list[dict[str,Any]]:
    """Return all addressable evidence while preserving legacy state."""
    return normalize_findings(state)+[
        item for key in ("opportunities","evidence_surfaces")
        for item in state.get(key,[]) if isinstance(item,dict)
    ]

def semantic_dimensions(text:str)->set[str]:
    return {name for name,pattern in SEMANTIC_PATTERNS.items() if pattern.search(text)}

def reasoning_state_warnings(project_map:dict[str,Any])->list[str]:
    warnings=[]
    for index,item in enumerate(project_map.get("feature_groups",[]) if isinstance(project_map.get("feature_groups",[]),list) else []):
        if not isinstance(item,dict): continue
        dimensions={
            "mechanism":nonempty(item.get("expected_signal")),
            "applicability":nonempty(item.get("inference_availability")) or nonempty(item.get("applicability_conditions")),
            "failure":nonempty(item.get("risks")) or nonempty(item.get("open_questions")),
            "interaction":nonempty(item.get("interactions")),
            "evidence":nonempty(item.get("empirical_evidence")),
        }
        if sum(dimensions.values())<3:
            missing=[name for name,present in dimensions.items() if not present]
            warnings.append(f"project_map.feature_groups[{index}] is likely descriptive-only; missing analytical dimensions: {missing}")
    for index,item in enumerate(project_map.get("model_components",[]) if isinstance(project_map.get("model_components",[]),list) else []):
        if not isinstance(item,dict): continue
        dimensions={
            "rationale":nonempty(item.get("design_rationale")) or nonempty(item.get("training_logic")),
            "applicability":nonempty(item.get("applicability_conditions")) or nonempty(item.get("strengths")),
            "failure":nonempty(item.get("limitations")),
            "interaction":nonempty(item.get("interaction_with_other_components")),
            "evidence":nonempty(item.get("empirical_behavior")) or nonempty(item.get("evidence_refs")),
        }
        if sum(dimensions.values())<3:
            missing=[name for name,present in dimensions.items() if not present]
            warnings.append(f"project_map.model_components[{index}] is likely descriptive-only; missing analytical dimensions: {missing}")
    return warnings

def requested_focus_ids(plan:dict[str,Any])->list[str]:
    return [
        str(item.get("id")) if isinstance(item,dict) else str(item)
        for item in plan.get("focus",[]) if nonempty(item)
    ]

def validate_state(state:Any)->tuple[list[str],list[str]]:
    errors=[]; warnings=[]
    if not isinstance(state,dict): return ["analysis state must be a JSON object"],warnings
    if state.get("schema_version") not in {"0.1","0.2","0.3"}: errors.append("schema_version must be 0.1, 0.2, or 0.3")
    if not nonempty(state.get("state_revision")): errors.append("state_revision is required")
    if not isinstance(state.get("project_map"),dict) or not state["project_map"]: errors.append("project_map must be a non-empty object")
    elif state.get("schema_version")=="0.3": warnings.extend(reasoning_state_warnings(state["project_map"]))
    findings=normalize_findings(state)
    if state.get("schema_version")=="0.2" and not isinstance(state.get("findings"),list): errors.append("findings must be an array")
    if not isinstance(state.get("opportunities"),list): errors.append("opportunities must be an array")
    seen=set()
    for index,item in enumerate(findings):
        label=f"findings[{index}]"
        require_fields(item,("id","topic","title","claim_status","evidence","consequence","recommended_action","confidence"),label,errors)
        item_id=item.get("id")
        if isinstance(item_id,str):
            if item_id in seen: errors.append(f"duplicate evidence id: {item_id}")
            seen.add(item_id)
        if item.get("claim_status") not in CLAIM_STATUSES: errors.append(f"{label}.claim_status is invalid")
        if item.get("confidence") not in LEVELS: errors.append(f"{label}.confidence must be Low, Medium, or High")
    for index,item in enumerate(state.get("opportunities",[])):
        label=f"opportunities[{index}]"
        fields=("id","group","title","evidence","next_step","decision_enabled","effort","confidence") if state.get("schema_version")=="0.1" else ("id","topic","title","basis","next_step","decision_enabled","effort","confidence")
        require_fields(item,fields,label,errors)
        if not isinstance(item,dict): continue
        item_id=item.get("id")
        if isinstance(item_id,str):
            if item_id in seen: errors.append(f"duplicate evidence id: {item_id}")
            seen.add(item_id)
        if item.get("effort") not in LEVELS or item.get("confidence") not in LEVELS: errors.append(f"{label} effort/confidence must be Low, Medium, or High")
    for index,item in enumerate(state.get("evidence_surfaces",[])):
        label=f"evidence_surfaces[{index}]"
        require_fields(item,("id","focus","kind","source","availability","inspected","significance"),label,errors)
        if not isinstance(item,dict): continue
        item_id=item.get("id")
        if isinstance(item_id,str):
            if item_id in seen: errors.append(f"duplicate evidence id: {item_id}")
            seen.add(item_id)
        if item.get("availability") not in AVAILABILITY: errors.append(f"{label}.availability is invalid")
        if not isinstance(item.get("inspected"),bool): errors.append(f"{label}.inspected must be boolean")
        if item.get("significance") not in {"low","medium","high"}: errors.append(f"{label}.significance must be low, medium, or high")
    focus_coverage=state.get("focus_coverage",[])
    if state.get("schema_version")=="0.3" and not isinstance(focus_coverage,list): errors.append("focus_coverage must be an array")
    for index,item in enumerate(focus_coverage if isinstance(focus_coverage,list) else []):
        label=f"focus_coverage[{index}]"
        require_fields(item,("focus","status","questions"),label,errors)
        if not isinstance(item,dict): continue
        for field in ("implementation_inspected","evidence_ids","interpretations","uninspected_relevant_surfaces"):
            if field not in item: errors.append(f"{label}.{field} is required")
        if item.get("status") not in COVERAGE_STATUSES: errors.append(f"{label}.status is invalid")
        for field in ("questions","evidence_ids","interpretations","uninspected_relevant_surfaces"):
            if not isinstance(item.get(field),list): errors.append(f"{label}.{field} must be an array")
        if not isinstance(item.get("implementation_inspected"),bool): errors.append(f"{label}.implementation_inspected must be boolean")
        if item.get("status")=="weak" and item.get("uninspected_relevant_surfaces"):
            errors.append(f"{label} is weak because relevant evidence remains uninspected; continue analysis before composition")
        if item.get("status")=="unavailable" and not nonempty(item.get("evidence_gap")):
            errors.append(f"{label}.evidence_gap is required when coverage is unavailable")
        if item.get("status")=="sufficient":
            if not item.get("implementation_inspected"): errors.append(f"{label} cannot be sufficient before inspecting the relevant implementation")
            if not item.get("interpretations"): errors.append(f"{label} needs at least one interpretation beyond description")
    known_evidence={str(item.get("id")) for item in evidence_items(state)}
    for index,item in enumerate(focus_coverage if isinstance(focus_coverage,list) else []):
        if isinstance(item,dict):
            unknown=sorted({str(value) for value in item.get("evidence_ids",[])}-known_evidence)
            if unknown: errors.append(f"focus_coverage[{index}] references unknown evidence ids: {unknown}")
    gate=state.get("synthesis_gate")
    if not isinstance(gate,dict): errors.append("synthesis_gate must be an object")
    else:
        if gate.get("status")!="ready": errors.append("synthesis_gate.status must be ready before planning")
        fields=["project_map_consolidated","opportunities_consolidated","material_unknowns_reviewed",("issues_consolidated" if state.get("schema_version")=="0.1" else "findings_consolidated")]
        for field in fields:
            if gate.get(field) is not True: errors.append(f"synthesis_gate.{field} must be true")
        if state.get("schema_version")=="0.3":
            for field in ("focus_coverage_reviewed","existing_evidence_mined"):
                if gate.get(field) is not True: errors.append(f"synthesis_gate.{field} must be true")
    return errors,warnings

def validate_plan(plan:Any,state:dict[str,Any])->tuple[list[str],list[str]]:
    errors=[]; warnings=[]
    if not isinstance(plan,dict): return ["report plan must be a JSON object"],warnings
    require_fields(plan,("schema_version","plan_revision","status","purpose","audience","focus","target_length","detail","profile","requested_iterations","sections"),"plan",errors)
    if plan.get("schema_version") not in {"0.1","0.2"}: errors.append("plan.schema_version must be 0.1 or 0.2")
    if plan.get("status")!="reviewed": errors.append("plan.status must be reviewed before composition")
    if plan.get("profile") not in PROFILES: errors.append("plan.profile must be quick, standard, or publication")
    if plan.get("detail") not in DETAIL_LEVELS: errors.append("plan.detail must be compact, normal, or deep")
    iterations=plan.get("requested_iterations")
    if not isinstance(iterations,int) or isinstance(iterations,bool) or iterations<1: errors.append("plan.requested_iterations must be a positive integer")
    for field in ("focus","visuals","appendix_material","duplication_risks"):
        if not isinstance(plan.get(field),list): errors.append(f"plan.{field} must be an array")
    sections=plan.get("sections")
    if not isinstance(sections,list) or not sections: errors.append("plan.sections must be a non-empty array"); return errors,warnings
    section_ids=set(); titles=set(); roles=[]
    evidence_ids={str(item.get("id")) for item in evidence_items(state)}
    for index,section in enumerate(sections):
        label=f"plan.sections[{index}]"; require_fields(section,("id","title","role","purpose"),label,errors)
        if not isinstance(section,dict): continue
        section_id=str(section.get("id","")); title=canonical_heading(str(section.get("title",""))); role=section.get("role")
        if section_id in section_ids: errors.append(f"duplicate plan section id: {section_id}")
        section_ids.add(section_id)
        if title in titles: errors.append(f"duplicate plan section title: {title}")
        titles.add(title); roles.append(str(role))
        if role not in SECTION_ROLES: errors.append(f"{label}.role is invalid")
        planned=section.get("evidence_ids",[])
        if not isinstance(planned,list): errors.append(f"{label}.evidence_ids must be an array")
        else:
            unknown=sorted({str(value) for value in planned}-evidence_ids)
            if unknown: errors.append(f"{label} references unknown evidence ids: {unknown}")
    if plan.get("substantial",True) and roles.count("executive-summary")!=1: errors.append("substantial reports require one executive-summary section")
    if plan.get("requires_action_section") is True and not {"actions","conclusion"}.intersection(roles): errors.append("plan requires a coherent action or conclusion section")
    if roles.count("appendix")>1: errors.append("plan may contain at most one appendix")
    if "appendix" in roles and roles[-1]!="appendix": errors.append("appendix must be the final planned section")
    if plan.get("schema_version")=="0.2":
        if not nonempty(plan.get("analytical_depth")): errors.append("plan.analytical_depth is required and is independent of target_length")
        coverage=plan.get("focus_coverage")
        if not isinstance(coverage,list): errors.append("plan.focus_coverage must be an array")
        else:
            focus_ids=requested_focus_ids(plan); covered=[]; mapped_evidence=set()
            for index,item in enumerate(coverage):
                label=f"plan.focus_coverage[{index}]"
                require_fields(item,("focus","status"),label,errors)
                if not isinstance(item,dict): continue
                for field in ("section_ids","evidence_ids","answered_questions","analytical_claims"):
                    if field not in item: errors.append(f"{label}.{field} is required")
                covered.append(str(item.get("focus")))
                if item.get("status") not in COVERAGE_STATUSES: errors.append(f"{label}.status is invalid")
                for field in ("section_ids","evidence_ids","answered_questions","analytical_claims"):
                    if not isinstance(item.get(field),list): errors.append(f"{label}.{field} must be an array")
                unknown_sections=sorted({str(value) for value in item.get("section_ids",[])}-section_ids)
                if unknown_sections: errors.append(f"{label} references unknown section ids: {unknown_sections}")
                unknown_evidence=sorted({str(value) for value in item.get("evidence_ids",[])}-evidence_ids)
                if unknown_evidence: errors.append(f"{label} references unknown evidence ids: {unknown_evidence}")
                if item.get("status")=="sufficient" and (not item.get("section_ids") or not item.get("analytical_claims") or not item.get("answered_questions")):
                    warnings.append(f"{label} is marked sufficient but lacks sections, analytical claims, or answered focus questions")
                mapped_evidence.update(str(value) for value in item.get("evidence_ids",[]))
            missing=sorted(set(focus_ids)-set(covered))
            if missing: errors.append(f"plan.focus_coverage is missing requested focus areas: {missing}")
            requested=set(focus_ids)
            for item in state.get("evidence_surfaces",[]):
                if not isinstance(item,dict): continue
                if item.get("availability")=="available" and item.get("inspected") is True and item.get("significance") in {"medium","high"} and str(item.get("focus")) in requested and str(item.get("id")) not in mapped_evidence:
                    warnings.append(f"significant inspected evidence {item.get('id')} for requested focus {item.get('focus')} is not mapped into the report plan")
        opportunity_ids={str(item.get("id")) for item in state.get("opportunities",[]) if isinstance(item,dict)}
        planned_ids={str(value) for section in sections if isinstance(section,dict) for value in section.get("evidence_ids",[])}
        if opportunity_ids and not {"actions","conclusion"}.intersection(roles) and not plan.get("descriptive_only",False):
            errors.append("a normal technical report with supported opportunities requires a Research & Improvement Map/action section")
        low_effort={str(item.get("id")) for item in state.get("opportunities",[]) if isinstance(item,dict) and item.get("effort")=="Low"}
        if low_effort-planned_ids: warnings.append(f"supported low-hanging-fruit opportunities are not mapped into the plan: {sorted(low_effort-planned_ids)}")
    return errors,warnings

def section_bodies(markdown:str,found:list[tuple[int,str,int]])->dict[str,str]:
    lines=markdown.splitlines(); level_two=[(name,line) for level,name,line in found if level==2]; result={}
    for index,(name,line) in enumerate(level_two):
        end=level_two[index+1][1]-1 if index+1<len(level_two) else len(lines)
        result[name]="\n".join(lines[line:end])
    return result

def phrase_sections(phrase:str,bodies:dict[str,str])->list[str]:
    normalized=re.sub(r"\s+"," ",phrase.strip().lower())
    if len(normalized.split())<6: return []
    return [title for title,body in bodies.items() if normalized in re.sub(r"\s+"," ",body.lower())]

def validate_report(state:dict[str,Any],plan:dict[str,Any],markdown:str)->tuple[list[str],list[str]]:
    errors=[]; warnings=[]; found=headings(markdown)
    if len([name for level,name,_ in found if level==1])!=1: errors.append("report must have exactly one level-one title")
    level_two=[(name,line) for level,name,line in found if level==2]
    planned=[canonical_heading(str(section.get("title",""))) for section in plan.get("sections",[]) if isinstance(section,dict)]
    actual=[name for name,_ in level_two]
    if actual!=planned: errors.append(f"level-two headings must match the reviewed report plan in order; planned={planned}, actual={actual}")
    roles={canonical_heading(str(section.get("title",""))):section.get("role") for section in plan.get("sections",[]) if isinstance(section,dict)}
    appendix_line=next((line for name,line in level_two if roles.get(name)=="appendix"),None)
    for _,name,line in found:
        if name in BANNED_HEADINGS: errors.append(f"chronological findings heading is forbidden at line {line}: {name}")
        if name in PROVENANCE_HEADINGS and (appendix_line is None or line<appendix_line): errors.append(f"provenance section interrupts the main narrative at line {line}")
    state_revision=STATE_REVISION_RE.search(markdown)
    if state_revision is None: errors.append("report is missing dsml-report-state-revision marker")
    elif str(state.get("state_revision"))!=state_revision.group(1): errors.append("report state revision marker does not match analysis state")
    plan_revision=PLAN_REVISION_RE.search(markdown)
    if plan_revision is None: errors.append("report is missing dsml-report-plan-revision marker")
    elif str(plan.get("plan_revision"))!=plan_revision.group(1): errors.append("report plan revision marker does not match report plan")
    lower=markdown.lower()
    if "see pdf for this section" in lower or "see the pdf for this section" in lower: errors.append("semantic source defers substantive content to the PDF")
    if "try more algorithms" in lower: errors.append("generic algorithm brainstorming is not project-specific")
    if "why:" in lower and "decision enabled:" in lower and lower.count("effort:")>2: warnings.append("repetitive framework labels may obscure the narrative")
    bodies=section_bodies(markdown,found)
    for title,body in bodies.items():
        if len(re.findall(r"\b\w+\b",body))<12: errors.append(f"planned section is effectively empty: {title}")
    if plan.get("schema_version")=="0.2":
        section_titles={str(section.get("id")):canonical_heading(str(section.get("title",""))) for section in plan.get("sections",[]) if isinstance(section,dict)}
        for coverage in plan.get("focus_coverage",[]):
            if not isinstance(coverage,dict) or coverage.get("status")!="sufficient": continue
            focus=str(coverage.get("focus")); mapped=[section_titles.get(str(value)) for value in coverage.get("section_ids",[])]
            mapped=[value for value in mapped if value in bodies]
            combined="\n".join(bodies[value] for value in mapped)
            words=len(re.findall(r"\b\w+\b",combined))
            if words<80:
                warnings.append(f"requested focus {focus} appears shallow ({words} words across mapped sections); verify evidence, interpretation, and answered focus questions")
            missing_mentions=[str(value) for value in coverage.get("evidence_ids",[]) if str(value).lower() not in combined.lower()]
            if missing_mentions:
                warnings.append(f"requested focus {focus} does not visibly reference planned evidence ids: {missing_mentions}")
            if plan.get("profile") in {"standard","publication"}:
                present=semantic_dimensions(combined)
                required={"mechanism","evidence","implication"}
                normalized_focus=focus.lower().replace("-","_").replace(" ","_")
                if normalized_focus in {"features","model","models","model_design","evaluation","current_issues","issues"}:
                    required.update({"applicability","failure"})
                missing=sorted(required-present)
                if missing:
                    warnings.append(f"requested focus {focus} lacks visible analytical dimensions {missing}; revise descriptive-only coverage or record a specific acceptance reason")
                table_rows=sum(1 for line in combined.splitlines() if line.strip().startswith("|") and not re.match(r"^\s*\|?\s*:?-+",line))
                analytical_bullets=sum(1 for line in combined.splitlines() if re.match(r"^\s*[-*+]\s+",line) and semantic_dimensions(line))
                if table_rows>=4 and analytical_bullets<2 and len(present)<4:
                    warnings.append(f"requested focus {focus} appears dominated by an inventory table without enough analytical interpretation")
    for finding in normalize_findings(state):
        for field in ("evidence","consequence","recommended_action"):
            value=finding.get(field)
            if isinstance(value,str):
                locations=phrase_sections(value,bodies)
                if len(locations)>1: errors.append(f"finding {finding.get('id')} repeats its {field} across major sections: {locations}")
    summaries=[title for title,role in roles.items() if role=="executive-summary"]
    if summaries:
        words=len(re.findall(r"\b\w+\b",bodies.get(summaries[0],"")))
        if words<40: warnings.append("executive summary appears too short to be useful")
        if words>650: warnings.append("executive summary may be too long for a compact opening")
    return errors,warnings

def validate_review_log(plan:dict[str,Any],review:Any|None)->tuple[list[str],list[str]]:
    errors=[]; warnings=[]; requested=plan.get("requested_iterations",1)
    if requested==1 and review is None: return errors,warnings
    if not isinstance(review,dict): return ["review log is required when requested_iterations is greater than 1"],warnings
    require_fields(review,("schema_version","plan_revision","versions","final_consistency"),"review_log",errors)
    if review.get("schema_version") not in {"0.1","0.2","0.3"}: errors.append("review_log.schema_version must be 0.1, 0.2, or 0.3")
    if str(review.get("plan_revision"))!=str(plan.get("plan_revision")): errors.append("review log plan_revision does not match the report plan")
    versions=review.get("versions")
    if not isinstance(versions,list) or len(versions)!=requested: errors.append(f"review log must contain exactly {requested} report versions"); return errors,warnings
    for index,version in enumerate(versions,1):
        label=f"review_log.versions[{index-1}]"; require_fields(version,("version","source_revision"),label,errors)
        if not isinstance(version,dict): continue
        if version.get("version")!=index: errors.append(f"{label}.version must be {index}")
        if index==1: continue
        require_fields(version,("review_surfaces","revision_scope","verification"),label,errors)
        surfaces=version.get("review_surfaces")
        if not isinstance(surfaces,list) or not set(surfaces).issubset(REVIEW_SURFACES): errors.append(f"{label}.review_surfaces contains invalid values")
        if not {"architecture","content"}.intersection(set(surfaces or [])): errors.append(f"{label} must critique architecture or content")
        if version.get("revision_scope") not in {"targeted","restructure","none"}: errors.append(f"{label}.revision_scope is invalid")
        defects=version.get("defects")
        if not isinstance(defects,list): errors.append(f"{label}.defects must be an array"); continue
        changed=version.get("changed_sections")
        if not isinstance(changed,list): errors.append(f"{label}.changed_sections must be an array")
        if defects and not changed and version.get("revision_scope")!="none": errors.append(f"{label} has defects but no changed sections")
        if index==2:
            if "content-depth" not in set(surfaces or []): errors.append(f"{label} must include the mandatory content-depth review surface")
            depth=version.get("depth_review")
            if not isinstance(depth,dict): errors.append(f"{label}.depth_review is required for iteration 2")
            else:
                require_fields(depth,("focus_reviews",),f"{label}.depth_review",errors)
                reviews=depth.get("focus_reviews")
                if not isinstance(reviews,list): errors.append(f"{label}.depth_review.focus_reviews must be an array")
                else:
                    reviewed={str(item.get("focus")) for item in reviews if isinstance(item,dict)}
                    missing=sorted(set(requested_focus_ids(plan))-reviewed)
                    if missing: errors.append(f"{label}.depth_review is missing requested focus areas: {missing}")
                    if review.get("schema_version") in {"0.2","0.3"}:
                        for review_index,item in enumerate(reviews):
                            review_label=f"{label}.depth_review.focus_reviews[{review_index}]"
                            require_fields(item,("focus","assessment","checked_dimensions"),review_label,errors)
                            if not isinstance(item,dict): continue
                            if item.get("assessment") not in {"pass","revised","unavailable"}: errors.append(f"{review_label}.assessment is invalid")
                            checked=item.get("checked_dimensions")
                            if not isinstance(checked,list): errors.append(f"{review_label}.checked_dimensions must be an array")
                            else:
                                unknown=sorted(set(checked)-DEPTH_REVIEW_DIMENSIONS)
                                if unknown: errors.append(f"{review_label}.checked_dimensions contains invalid values: {unknown}")
                                if item.get("assessment")!="unavailable":
                                    missing_core=sorted(CORE_DEPTH_DIMENSIONS-set(checked))
                                    if missing_core: errors.append(f"{review_label}.checked_dimensions is missing core dimensions: {missing_core}")
                                relevant=item.get("relevant_conditional_dimensions",[])
                                if not isinstance(relevant,list): errors.append(f"{review_label}.relevant_conditional_dimensions must be an array")
                                else:
                                    invalid=sorted(set(relevant)-CONDITIONAL_DEPTH_DIMENSIONS)
                                    if invalid: errors.append(f"{review_label}.relevant_conditional_dimensions contains invalid values: {invalid}")
                                    unchecked=sorted(set(relevant)-set(checked))
                                    if unchecked: errors.append(f"{review_label} did not check relevant conditional dimensions: {unchecked}")
                            if not isinstance(item.get("revisions"),list): errors.append(f"{review_label}.revisions must be an array")
                for field in ("underused_evidence","missing_supported_insights"):
                    if not isinstance(depth.get(field),list): errors.append(f"{label}.depth_review.{field} must be an array")
                if review.get("schema_version")=="0.3":
                    gaps=depth.get("gaps")
                    if not isinstance(gaps,list): errors.append(f"{label}.depth_review.gaps must be an array")
                    else:
                        for gap_index,gap in enumerate(gaps):
                            gap_label=f"{label}.depth_review.gaps[{gap_index}]"
                            require_fields(gap,("section","issue","why_it_matters","repair","evidence_needed","status","resolution"),gap_label,errors)
                            if not isinstance(gap,dict): continue
                            if not isinstance(gap.get("evidence_needed"),bool): errors.append(f"{gap_label}.evidence_needed must be boolean")
                            if gap.get("status") not in {"repaired","accepted","unresolved"}: errors.append(f"{gap_label}.status is invalid")
                            if gap.get("status")=="unresolved": errors.append(f"{gap_label} must be repaired or explicitly accepted")
                            if gap.get("status")=="repaired" and isinstance(changed,list) and str(gap.get("section")) not in {str(value) for value in changed}:
                                errors.append(f"{gap_label}.section must appear in changed_sections after repair")
                            if gap.get("evidence_needed") is True:
                                lookup=gap.get("evidence_lookup")
                                require_fields(lookup,("question","source","state_updated"),f"{gap_label}.evidence_lookup",errors)
                                if isinstance(lookup,dict) and not isinstance(lookup.get("state_updated"),bool): errors.append(f"{gap_label}.evidence_lookup.state_updated must be boolean")
            scope=version.get("revision_scope")
            if scope=="none":
                if len(str(version.get("pass_reason","")).strip())<20: errors.append(f"{label}.pass_reason is required when revision_scope is none")
                if changed: errors.append(f"{label}.changed_sections must be empty when revision_scope is none")
                if isinstance(depth,dict) and depth.get("gaps"): errors.append(f"{label} cannot use revision_scope none while material gaps remain recorded")
            elif scope=="targeted" and not changed:
                errors.append(f"{label}.changed_sections is required for a targeted revision")
            elif scope=="restructure" and len(str(version.get("restructure_reason","")).strip())<20:
                errors.append(f"{label}.restructure_reason is required for an exceptional whole-report restructure")
            if scope=="targeted" and isinstance(changed,list):
                planned_sections=[str(section.get("title")) for section in plan.get("sections",[]) if isinstance(section,dict) and section.get("role")!="appendix"]
                if planned_sections and set(planned_sections).issubset(set(str(value) for value in changed)):
                    warnings.append(f"{label} changes every non-appendix section; use restructure with a concrete reason or preserve unaffected content")
        for defect_index,defect in enumerate(defects):
            defect_label=f"{label}.defects[{defect_index}]"
            require_fields(defect,("id","surface","description","affected_sections","status","resolution","verification"),defect_label,errors)
            if not isinstance(defect,dict): continue
            if defect.get("surface") not in REVIEW_SURFACES: errors.append(f"{defect_label}.surface is invalid")
            if defect.get("status") not in {"resolved","accepted"}: errors.append(f"{defect_label}.status must be resolved or accepted")
            if defect.get("status")=="accepted" and len(str(defect.get("resolution","")).strip())<20: errors.append(f"{defect_label} needs a concrete acceptance reason")
    final=review.get("final_consistency")
    if not isinstance(final,dict) or final.get("status")!="pass": errors.append("review_log.final_consistency.status must be pass")
    elif len(str(final.get("notes","")).strip())<20: errors.append("final consistency pass needs concrete notes")
    return errors,warnings

def load_json(path:Path,label:str)->Any:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise ValueError(f"{label}: {exc}") from exc

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state",required=True,type=Path); parser.add_argument("--plan",required=True,type=Path)
    parser.add_argument("--report",required=True,type=Path); parser.add_argument("--review-log",type=Path); parser.add_argument("--json",action="store_true")
    args=parser.parse_args()
    try:
        state=load_json(args.state,"state"); plan=load_json(args.plan,"plan"); report=args.report.read_text(encoding="utf-8")
        review=load_json(args.review_log,"review log") if args.review_log else None
    except (OSError,UnicodeError,ValueError) as exc: print(f"ERROR: {exc}"); return 2
    se,sw=validate_state(state); pe,pw=validate_plan(plan,state if isinstance(state,dict) else {})
    re_,rw=validate_report(state if isinstance(state,dict) else {},plan if isinstance(plan,dict) else {},report)
    ve,vw=validate_review_log(plan if isinstance(plan,dict) else {},review)
    result={"status":"fail" if se or pe or re_ or ve else "pass","errors":se+pe+re_+ve,"warnings":sw+pw+rw+vw}
    if args.json: print(json.dumps(result,indent=2,sort_keys=True))
    else:
        for value in result["errors"]: print(f"ERROR: {value}")
        for value in result["warnings"]: print(f"WARNING: {value}")
        print(f"{result['status'].upper()}: DS/ML report QA")
    return 1 if result["errors"] else 0

if __name__=="__main__": raise SystemExit(main())
