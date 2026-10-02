from __future__ import annotations
import importlib.util, json, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VALIDATOR_PATH=ROOT/".agents/skills/compose-dsml-report/scripts/validate_dsml_report.py"
PDF_QA_PATH=ROOT/".agents/skills/compose-dsml-report/scripts/qa_dsml_report_pdf.py"

def load(path:Path,name:str):
    spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec)
    assert spec.loader is not None; spec.loader.exec_module(module); return module

validator=load(VALIDATOR_PATH,"validate_dsml_report")
pdf_qa=load(PDF_QA_PATH,"qa_dsml_report_pdf")

class ReportCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((ROOT/"evals/cases/report-composition-cases.json").read_text(encoding="utf-8"))["cases"]

    def state(self,revision="1"):
        return {
            "schema_version":"0.2","state_revision":revision,
            "project_map":{"objective":"Predict synthetic demand","problem_type":"forecasting"},
            "findings":[{
                "id":"EVAL-01","topic":"evaluation","title":"Selection horizon is too short",
                "claim_status":"Verified",
                "evidence":"Validation scores cover four weeks while production decisions require twelve weeks.",
                "consequence":"Reported accuracy cannot establish performance across the operational horizon.",
                "recommended_action":"Evaluate cohort error over the complete twelve week decision horizon.",
                "confidence":"High",
            }],
            "opportunities":[{
                "id":"MODEL-01","topic":"modeling","title":"Test seasonal feature contribution",
                "basis":"Seasonal features are present but no ablation isolates their value.",
                "next_step":"Run one family-level ablation on the frozen split.",
                "decision_enabled":"Retain or simplify seasonal feature families.",
                "dependency":"EVAL-01","effort":"Low","confidence":"Medium",
            }],
            "synthesis_gate":{
                "status":"ready","project_map_consolidated":True,
                "findings_consolidated":True,"opportunities_consolidated":True,
                "material_unknowns_reviewed":True,
            },
        }

    def plan(self,sections,iterations=1,revision="1",focus=None):
        return {
            "schema_version":"0.1","plan_revision":revision,"status":"reviewed",
            "purpose":"Technical assessment","audience":"Experienced DS/ML practitioners",
            "focus":focus or ["evaluation"],"target_length":"5-7 pages","detail":"normal",
            "profile":"standard","requested_iterations":iterations,"substantial":True,
            "requires_action_section":True,"sections":sections,
            "visuals":[],"appendix_material":["Detailed provenance"],
            "duplication_risks":["EVAL-01 could be repeated in summary and actions"],
        }

    def depth_state(self):
        state=self.state(); state["schema_version"]="0.3"
        state["project_map"].update({
            "feature_groups":[{"name":"seasonality","examples":["week_of_year"],"empirical_evidence":["FEAT-IMP-01"]}],
            "model_components":[{"name":"lightgbm","role":"candidate","empirical_behavior":["EVAL-01"]}],
            "evaluation":{"split_structure":"rolling origin","metrics":["WAPE"],"stability_evidence":["EVAL-FOLD-01"]},
        })
        state["evidence_surfaces"]=[
            {"id":"FEAT-IMP-01","focus":"features","kind":"feature_importance","source":"artifacts/importance.csv","availability":"available","inspected":True,"significance":"high","summary":"Seasonal lag dominates gain importance."},
            {"id":"EVAL-FOLD-01","focus":"evaluation","kind":"per_fold_metrics","source":"eval/folds.csv","availability":"available","inspected":True,"significance":"high","summary":"Error varies materially by fold."},
            {"id":"MODEL-RUNTIME-01","focus":"model_design","kind":"runtime","source":"runtime/models.csv","availability":"available","inspected":True,"significance":"medium","summary":"One candidate is slower with few wins."},
        ]
        state["focus_coverage"]=[{
            "focus":"features","status":"sufficient","questions":["Which groups dominate and are they inference-safe?"],
            "implementation_inspected":True,"evidence_ids":["FEAT-IMP-01"],
            "interpretations":["Dominant seasonal gain supports an ablation but is not causal evidence."],
            "uninspected_relevant_surfaces":[],
        }]
        state["synthesis_gate"].update({"focus_coverage_reviewed":True,"existing_evidence_mined":True})
        return state

    def depth_plan(self,state=None,iterations=2):
        state=state or self.depth_state(); sections=self.sections("model")
        for section in sections:
            if section["id"]=="features": section["evidence_ids"].append("FEAT-IMP-01")
        plan=self.plan(sections,iterations=iterations,focus=["features"])
        plan.update({
            "schema_version":"0.2","analytical_depth":"substantial",
            "focus_coverage":[{
                "focus":"features","status":"sufficient","section_ids":["features"],
                "evidence_ids":["FEAT-IMP-01"],
                "answered_questions":["Which feature groups dominate?"],
                "analytical_claims":["Seasonal gain dominance warrants a frozen-split family ablation."],
            }],
        })
        return plan

    @staticmethod
    def sections(kind):
        summary={"id":"summary","title":"Executive Summary","role":"executive-summary","purpose":"Decision-useful synthesis","evidence_ids":[]}
        appendix={"id":"appendix","title":"Appendix","role":"appendix","purpose":"Supporting provenance","evidence_ids":[]}
        actions={"id":"actions","title":"Recommended Investigation Plan","role":"actions","purpose":"Evidence-linked next actions","evidence_ids":["MODEL-01"]}
        if kind=="model":
            middle=[
                {"id":"system","title":"System Overview","role":"context","purpose":"Orient the reader","evidence_ids":[]},
                {"id":"model","title":"Model Design","role":"model","purpose":"Explain the model architecture","evidence_ids":[]},
                {"id":"features","title":"Feature Engineering","role":"features","purpose":"Assess feature design","evidence_ids":["MODEL-01"]},
                {"id":"issues","title":"Critical Issues","role":"findings","purpose":"Explain material risks once","evidence_ids":["EVAL-01"]},
            ]
        else:
            middle=[
                {"id":"evaluation","title":"Evaluation Architecture","role":"evaluation","purpose":"Lead with evaluation correctness","evidence_ids":["EVAL-01"]},
                {"id":"performance","title":"Current Performance and Limits","role":"findings","purpose":"Interpret performance","evidence_ids":[]},
            ]
        return [summary,*middle,actions,appendix]

    def report(self,state,plan,duplicate=False):
        bodies={
            "Executive Summary":"This assessment centers the requested technical question and identifies the evidence that changes the decision. The current validation horizon is incomplete, so headline accuracy is not yet operational evidence. Model changes should wait until evaluation covers the real decision horizon and uncertainty is visible.",
            "System Overview":"Synthetic weekly observations become lagged and seasonal features, then feed a forecasting model used for twelve week planning. Training, selection, batch inference, and the planning consumer form one traceable path with explicit time boundaries.",
            "Model Design":"The current estimator combines autoregressive structure with regularized nonlinear interactions. Its role, training boundary, selection rule, and inference behavior are described here without reproducing implementation details that do not change the assessment.",
            "Feature Engineering":"Features group into recent demand, calendar seasonality, and stable entity attributes. FEAT-IMP-01 shows that seasonal lag dominates gain importance, which is predictive attribution rather than causal evidence. Its dominance is plausible but increases sensitivity to point-in-time construction. The lag is available at inference only when the recursive forecast state uses observations no later than the origin; that boundary needs a code-level check. Recent-demand and rolling features may be redundant because they summarize overlapping windows, while stable attributes offer lower-cost segmentation signal. Seasonal contribution remains unisolated because no family-level ablation exists; one frozen-split ablation can decide whether that complexity should remain without confusing gain importance with incremental value.",
            "Critical Issues":"Validation scores cover four weeks while production decisions require twelve weeks. This makes the reported accuracy insufficient evidence across the operational horizon. The canonical finding is EVAL-01; confidence is high because the configured windows are explicit.",
            "Evaluation Architecture":"The split is time ordered, but the selection window spans only four weeks. EVAL-01 is the canonical evaluation finding: Validation scores cover four weeks while production decisions require twelve weeks. The mismatch is directly evidenced by configuration and stored aggregates.",
            "Current Performance and Limits":"Observed aggregate error is useful for short-horizon model selection but cannot be extrapolated to the planning horizon. Segment stability, long-horizon degradation, and uncertainty remain unmeasured, so performance is interpreted within those limits.",
            "Recommended Investigation Plan":"First extend evaluation to the complete operational horizon, then run the seasonal family ablation on the frozen split. This sequence connects each action to an unresolved decision and avoids generic model exploration.",
            "Appendix":"Supporting configuration paths, aggregate metric provenance, commands, environment versions, and exhaustive feature names belong here so the main narrative remains concise and decision focused.",
        }
        if duplicate:
            bodies["Recommended Investigation Plan"]+=" Validation scores cover four weeks while production decisions require twelve weeks."
        lines=["# Synthetic Forecasting Assessment","",f"<!-- dsml-report-state-revision: {state['state_revision']} -->",f"<!-- dsml-report-plan-revision: {plan['plan_revision']} -->",""]
        for section in plan["sections"]:
            lines += [f"## {section['title']}","",bodies[section["title"]],""]
        return "\n".join(lines)

    def review_log(self,iterations):
        versions=[{"version":1,"source_revision":"draft-1"}]
        for version in range(2,iterations+1):
            versions.append({
                "version":version,"source_revision":f"draft-{version}",
                "review_surfaces":["architecture","content","content-depth"] if version==2 else ["content"],
                "defects":[{
                    "id":f"R-{version}","surface":"architecture",
                    "description":"Evaluation evidence was positioned after lower-priority implementation detail.",
                    "affected_sections":["Evaluation Architecture"],"status":"resolved",
                    "resolution":"Moved evaluation architecture before performance interpretation.",
                    "verification":"Confirmed the revised section order matches the reviewed plan.",
                }] if version==2 else [],
                "revision_scope":"targeted" if version==2 else "none",
                "changed_sections":["Evaluation Architecture"] if version==2 else [],
                "verification":"Rechecked the named review surfaces against the revised source.",
            })
            if version>2:
                versions[-1]["pass_reason"]="The prior targeted revision remains adequate after the requested follow-up review."
            if version==2:
                versions[-1]["depth_review"]={
                    "focus_reviews":[{"focus":"evaluation","missing_supported_insight":"Fold variation was underinterpreted."}],
                    "underused_evidence":["EVAL-01"],
                    "missing_supported_insights":["Operational-horizon consequence"],
                }
        return {
            "schema_version":"0.1","plan_revision":"1","versions":versions,
            "final_consistency":{"status":"pass","notes":"Numbers, headings, evidence identifiers, and cross-references are consistent."},
        }

    def test_cases_cover_requested_failure_modes(self):
        self.assertEqual(
            {"model-feature-focus","evaluation-focus","iteration-semantics","visual-defect-repair","duplicate-finding","sparse-table-layout","late-evidence-targeting","feature-evidence-depth","model-runtime-depth","evaluation-stability-depth","page-budget-depth","research-map-retention","standard-explanatory-depth","claim-type-separation","iteration-two-semantic-depth","source-truth-consistency","low-information-density"},
            {case["id"] for case in self.cases},
        )

    def test_standard_focus_warns_on_inventory_without_reasoning(self):
        state=self.depth_state(); plan=self.depth_plan(state,iterations=1)
        shallow=self.report(state,plan).replace(
            "Features group into recent demand, calendar seasonality, and stable entity attributes. FEAT-IMP-01 shows that seasonal lag dominates gain importance, which is predictive attribution rather than causal evidence. Its dominance is plausible but increases sensitivity to point-in-time construction. The lag is available at inference only when the recursive forecast state uses observations no later than the origin; that boundary needs a code-level check. Recent-demand and rolling features may be redundant because they summarize overlapping windows, while stable attributes offer lower-cost segmentation signal. Seasonal contribution remains unisolated because no family-level ablation exists; one frozen-split ablation can decide whether that complexity should remain without confusing gain importance with incremental value.",
            "| Family | Fields |\n| --- | --- |\n| Recent | lag 1 |\n| Seasonal | lag 52 |\n| Rolling | mean 4 |\n| Static | category |\n\nFEAT-IMP-01 is listed in the artifact index."
        )
        warnings=validator.validate_report(state,plan,shallow)[1]
        self.assertTrue(any("lacks visible analytical dimensions" in warning for warning in warnings))
        self.assertTrue(any("inventory table" in warning for warning in warnings))

    def test_reasoning_state_warns_when_components_are_inventory_only(self):
        state=self.depth_state()
        state["project_map"]["feature_groups"]=[{"name":"lags","examples":["lag_1","lag_52"]}]
        warnings=validator.validate_state(state)[1]
        self.assertTrue(any("feature_groups[0]" in warning and "descriptive-only" in warning for warning in warnings))

    def surgical_review(self,scope="targeted",evidence_needed=False):
        review=self.review_log(2); review["schema_version"]="0.3"
        version=review["versions"][1]
        version["revision_scope"]=scope
        version["defects"]=[] if scope=="none" else version["defects"]
        version["changed_sections"]=[] if scope=="none" else ["Feature Engineering"]
        if scope=="none":
            version["pass_reason"]="V1 already covers the material reasoning and evidence limits for the requested focus."
            version["depth_review"]["underused_evidence"]=[]
            version["depth_review"]["missing_supported_insights"]=[]
        focus_review=version["depth_review"]["focus_reviews"][0]
        focus_review.update({
            "focus":"features","assessment":"pass" if scope=="none" else "revised",
            "checked_dimensions":sorted(validator.CORE_DEPTH_DIMENSIONS|{"applicability","failure_modes"}),
            "relevant_conditional_dimensions":["applicability","failure_modes"],
            "revisions":[] if scope=="none" else ["Added expected signal and failure conditions."],
        })
        gap={
            "section":"Feature Engineering",
            "issue":"Expected signal is unexplained.",
            "why_it_matters":"The reader cannot assess when the feature should work.",
            "repair":"Add rationale and likely failure conditions.",
            "evidence_needed":evidence_needed,
            "status":"repaired",
            "resolution":"Patched only Feature Engineering with the missing reasoning.",
        }
        if evidence_needed:
            gap["evidence_lookup"]={
                "question":"Does the seasonal feature improve frozen-split error?",
                "source":"artifacts/seasonal_ablation.csv",
                "state_updated":True,
            }
        version["depth_review"]["gaps"]=[] if scope=="none" else [gap]
        return review

    def test_review_log_uses_core_and_relevant_conditional_dimensions(self):
        plan=self.depth_plan(iterations=2); review=self.surgical_review()
        self.assertEqual([],validator.validate_review_log(plan,review)[0])
        compatible=json.loads(json.dumps(review)); compatible["schema_version"]="0.2"
        compatible["versions"][1]["depth_review"].pop("gaps")
        self.assertEqual([],validator.validate_review_log(plan,compatible)[0])
        focus_review=review["versions"][1]["depth_review"]["focus_reviews"][0]
        self.assertNotIn("interactions",focus_review["checked_dimensions"])
        focus_review["checked_dimensions"].remove("mechanism")
        self.assertTrue(any("missing core dimensions" in error for error in validator.validate_review_log(plan,review)[0]))

    def test_iteration_two_patches_only_the_section_with_a_material_gap(self):
        plan=self.depth_plan(iterations=2); review=self.surgical_review()
        errors,_=validator.validate_review_log(plan,review)
        self.assertEqual([],errors)
        self.assertEqual(["Feature Engineering"],review["versions"][1]["changed_sections"])
        self.assertEqual(1,len(review["versions"][1]["depth_review"]["gaps"]))

    def test_iteration_two_allows_no_change_with_pass_reason(self):
        plan=self.depth_plan(iterations=2); review=self.surgical_review(scope="none")
        self.assertEqual([],validator.validate_review_log(plan,review)[0])
        del review["versions"][1]["pass_reason"]
        self.assertTrue(any("pass_reason" in error for error in validator.validate_review_log(plan,review)[0]))

    def test_missing_empirical_evidence_requires_a_narrow_lookup_record(self):
        plan=self.depth_plan(iterations=2); review=self.surgical_review(evidence_needed=True)
        self.assertEqual([],validator.validate_review_log(plan,review)[0])
        del review["versions"][1]["depth_review"]["gaps"][0]["evidence_lookup"]
        self.assertTrue(any("evidence_lookup" in error for error in validator.validate_review_log(plan,review)[0]))

    def test_whole_document_targeted_rewrite_is_visible(self):
        plan=self.depth_plan(iterations=2); review=self.surgical_review()
        review["versions"][1]["changed_sections"]=[
            section["title"] for section in plan["sections"] if section["role"]!="appendix"
        ]
        warnings=validator.validate_review_log(plan,review)[1]
        self.assertTrue(any("changes every non-appendix section" in warning for warning in warnings))

    def test_iteration_two_contract_forbids_broad_rediscovery(self):
        workflow=(ROOT/".agent-system/workflows/technical-report.md").read_text(encoding="utf-8")
        self.assertIn("Do not repeat broad repository discovery",workflow)
        self.assertIn("inspect the narrowest relevant",workflow)

    def test_source_consistency_detects_wrong_or_injected_pdf_content(self):
        source="# Report\n\nThe model uses verified lag features. Evidence is limited."
        same="Report The model uses verified lag features. Evidence is limited."
        mismatch="Completely different document with injected operational claims and unrelated conclusions."
        self.assertEqual([],pdf_qa.assess_source_consistency(source,same)["warnings"])
        self.assertIn("source_pdf_semantic_mismatch",pdf_qa.assess_source_consistency(source,mismatch)["warnings"])

    def test_text_density_contributes_to_underfilled_report_detection(self):
        texts=["useful analysis "*180,"thin page "*20,"another thin page "*25,"useful analysis "*180,"useful analysis "*180,"useful analysis "*180]
        metrics=pdf_qa.assess_text_density(texts)
        pages=[{"warnings":item["warnings"],"word_count":item["word_count"]} for item in metrics]
        self.assertIn("very_low_information_density",metrics[1]["warnings"])
        self.assertEqual(["underfilled_report"],pdf_qa.assess_report_density(pages,6,8))
        tail_pages=[{"warnings":[],"word_count":350} for _ in range(6)]+[{"warnings":["low_information_density"],"word_count":160}]
        self.assertEqual(["underfilled_report"],pdf_qa.assess_report_density(tail_pages,6,8))

    def test_prompt_adaptive_architectures_pass_without_universal_headings(self):
        state=self.state()
        for kind in ("model","evaluation"):
            with self.subTest(kind=kind):
                plan=self.plan(self.sections(kind),focus=[kind])
                self.assertEqual(([],[]),validator.validate_state(state))
                self.assertEqual([],validator.validate_plan(plan,state)[0])
                self.assertEqual([],validator.validate_report(state,plan,self.report(state,plan))[0])
        model_titles=[section["title"] for section in self.sections("model")]
        eval_titles=[section["title"] for section in self.sections("evaluation")]
        self.assertIn("Feature Engineering",model_titles)
        self.assertNotIn("Operations and Governance",model_titles)
        self.assertLess(eval_titles.index("Evaluation Architecture"),eval_titles.index("Current Performance and Limits"))

    def test_unreviewed_or_mismatched_plan_blocks_composition(self):
        state=self.state(); plan=self.plan(self.sections("evaluation")); plan["status"]="draft"
        self.assertTrue(any("reviewed" in error for error in validator.validate_plan(plan,state)[0]))
        plan["status"]="reviewed"
        report=self.report(state,plan).replace("## Evaluation Architecture","## PART I - Understand the Project")
        self.assertTrue(any("match the reviewed report plan" in error for error in validator.validate_report(state,plan,report)[0]))

    def test_one_shot_and_iterative_modes_have_distinct_evidence(self):
        state=self.state(); one=self.plan(self.sections("evaluation"),iterations=1)
        self.assertEqual([],validator.validate_review_log(one,None)[0])
        iterative=self.plan(self.sections("evaluation"),iterations=3)
        self.assertTrue(any("review log is required" in error for error in validator.validate_review_log(iterative,None)[0]))
        self.assertEqual([],validator.validate_review_log(iterative,self.review_log(3))[0])
        blind=self.review_log(3); blind["versions"][1]["revision_scope"]="regenerate"
        self.assertTrue(any("revision_scope" in error for error in validator.validate_review_log(iterative,blind)[0]))

    def test_focus_gate_blocks_uninspected_relevant_evidence(self):
        state=self.depth_state(); state["focus_coverage"][0].update({"status":"weak","uninspected_relevant_surfaces":["FEAT-IMP-01"]})
        errors,_=validator.validate_state(state)
        self.assertTrue(any("continue analysis before composition" in error for error in errors))

    def test_plan_warns_when_significant_focus_evidence_is_omitted(self):
        state=self.depth_state(); plan=self.depth_plan(state)
        plan["focus_coverage"][0]["evidence_ids"]=[]
        warnings=validator.validate_plan(plan,state)[1]
        self.assertTrue(any("FEAT-IMP-01" in warning and "not mapped" in warning for warning in warnings))

    def test_requested_focus_depth_uses_evidence_and_interpretation(self):
        state=self.depth_state(); plan=self.depth_plan(state)
        self.assertEqual([],validator.validate_state(state)[0])
        self.assertEqual([],validator.validate_plan(plan,state)[0])
        warnings=validator.validate_report(state,plan,self.report(state,plan))[1]
        self.assertFalse(any("features appears shallow" in warning for warning in warnings))

    def test_iteration_two_requires_content_depth_revision(self):
        plan=self.depth_plan(iterations=2); review=self.review_log(2)
        review["versions"][1]["depth_review"]["focus_reviews"]=[{"focus":"features","missing_supported_insight":"Importance interpretation was absent."}]
        self.assertEqual([],validator.validate_review_log(plan,review)[0])
        review["versions"][1]["review_surfaces"].remove("content-depth")
        self.assertTrue(any("mandatory content-depth" in error for error in validator.validate_review_log(plan,review)[0]))

    def test_page_target_does_not_change_analytical_depth(self):
        short=self.depth_plan(iterations=1); long=json.loads(json.dumps(short))
        short["target_length"]="6-8 pages"; long["target_length"]="12-16 pages"
        self.assertEqual(short["analytical_depth"],long["analytical_depth"])
        self.assertEqual(short["focus_coverage"],long["focus_coverage"])

    def test_duplicate_finding_text_is_rejected(self):
        state=self.state(); plan=self.plan(self.sections("model"))
        errors,_=validator.validate_report(state,plan,self.report(state,plan,duplicate=True))
        self.assertTrue(any("repeats its evidence" in error for error in errors))

    def test_late_evidence_requires_state_and_plan_recomposition(self):
        state=self.state(revision="2"); plan=self.plan(self.sections("evaluation"),revision="2")
        stale=self.report(state,plan).replace("state-revision: 2","state-revision: 1")
        self.assertTrue(any("state revision" in error for error in validator.validate_report(state,plan,stale)[0]))
        catchall=self.report(state,plan).replace("## Appendix","## Additional Findings\n\nA late chronological dump with enough filler words to look substantive but remain structurally wrong.\n\n## Appendix")
        self.assertTrue(any("chronological findings" in error for error in validator.validate_report(state,plan,catchall)[0]))

    def test_pdf_defects_must_be_repaired_or_accepted(self):
        base={
            "schema_version":"0.2","pdf":"/tmp/report.pdf","page_count":2,
            "automated_preflight":{"status":"pass","pages":[{"page":1,"warnings":[]},{"page":2,"warnings":[]}]},
            "visual_review":{"status":"not_performed","reviewed_pages":[],"defects":[],"notes":"","required_checks":[]},
        }
        defect={"id":"V-01","category":"table-wrapping","severity":"material","pages":[2],"description":"The evaluation table wraps into unreadable one-word columns.","status":"open"}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); prior=root/"prior.json"; current=root/"current.json"
            prior.write_text(json.dumps(base),encoding="utf-8"); current.write_text(json.dumps(base),encoding="utf-8")
            self.assertEqual(0,pdf_qa.record(prior,"fail","Reviewed both page images; page two contains an unreadable table.",[defect]))
            self.assertEqual(0,pdf_qa.record(current,"pass","Reviewed both final page images; table width and wrapping are now readable.",[]))
            resolution={**defect,"status":"resolved","verification":"Reopened page two at normal zoom and confirmed readable row and column wrapping."}
            self.assertEqual(0,pdf_qa.verify(prior,current,[resolution],"Compared the final render with V-01 and confirmed the targeted repair."))

    def test_geometry_preflight_flags_blank_sparse_dense_and_margin_risk(self):
        pages=pdf_qa.assess_page_boxes([(50,100,540,700),(0,0,0,0),(50,100,540,300),(4,3,592,840)])
        self.assertEqual(["blank_page"],pages[1]["warnings"])
        self.assertIn("sparse_page",pages[2]["warnings"])
        self.assertIn("dense_page",pages[3]["warnings"])
        self.assertIn("content_near_page_edge",pages[3]["warnings"])
        report_pages=pdf_qa.assess_page_boxes([(50,100,540,700)]+[(50,100,540,300)]*3+[(50,100,540,700)]*3)
        self.assertEqual(["underfilled_report"],pdf_qa.assess_report_density(report_pages,6,8))

    @unittest.skipUnless(shutil.which("gs"),"Ghostscript is required")
    def test_blank_render_cannot_receive_visual_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); ps=root/"blank.ps"; pdf=root/"blank.pdf"
            ps.write_text("%!PS-Adobe-3.0\n<< /PageSize [595.28 841.89] >> setpagedevice\nshowpage\n",encoding="ascii")
            done=subprocess.run([shutil.which("gs"),"-q","-dNOPAUSE","-dBATCH","-sDEVICE=pdfwrite",f"-sOutputFile={pdf}",str(ps)],capture_output=True,text=True,check=False)
            self.assertEqual(0,done.returncode)
            self.assertEqual(0,pdf_qa.prepare(pdf,root/"qa"))
            self.assertEqual(2,pdf_qa.record(root/"qa/qa.json","pass","Inspected the page image and found no material visual defects.",[]))

if __name__=="__main__": unittest.main()
