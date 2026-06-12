# Group 88 Feedback Resolution

This document records how Group 88 incorporated peer feedback for the Legal Co-Pilot project, or why a suggestion was not implemented for the final submission.

## Context

Our project is a document-grounded legal AI assistant that supports three workflows:
- structured extraction from legal documents
- rule-based review against predefined checks
- cross-document Q&A with source citations

This feedback log distinguishes between:
- `Poster update`: change the presentation/poster content or layout
- `Repo/code update`: change project documentation or implementation support material
- `Already covered`: keep the feature, but make it more explicit
- `Not implemented`: do not add it now, with justification

## Theme Summary

| Theme | Decision | Action |
|---|---|---|
| Evaluation and measurable results | Implement | Add explicit evaluation section to poster and document the evaluation workflow in the repo |
| Clear end-to-end workflow | Implement | Add one concrete user flow to the poster |
| Legal scope, risk, and limitations | Implement | Add conservative scope and risk framing to poster and repo docs |
| Architecture readability and poster layout | Implement | Simplify visual flow and reduce dense text |
| Modularity / extensibility | Already covered | Make provider-agnostic and corpus-based design more explicit |
| Larger / harder document testing | Implement | Point to existing hard-test assets and use them as evaluation evidence |
| MCP support | Not implemented | Keep as future work; not required for validating the current system |
| Online learning / feedback loop | Not implemented | Useful, but outside the scope of a grounded legal copilot proof of concept |

## Grouped Feedback Decisions

### 1. Evaluation and measurable results

| Feedback | Decision | Action | Justification | Evidence |
|---|---|---|---|---|
| Add more evaluation results and show how success is measured | Poster update + Repo/code update | Add a compact poster evaluation block and a reproducible evaluation procedure in the repo | This was the most common gap in the feedback and is not yet explicit enough in the current poster | `test_docs/docs/expected_results.md`, `test_docs/docs/pdf_eval_scorecard.md`, `test_docs/scripts/api_smoketest.sh`, `test_docs/scripts/pdf_hard_run.sh` |
| Show testing, accuracy, and limitations more clearly | Poster update + Repo/code update | Add metrics categories, grading rubric, and limitations summary | The project already has test assets, but they are scattered and informal | `test_docs/docs/pdf_eval_scorecard.md` |
| A score for outputs could help improvement | Implement partially | Use the existing scorecard approach for evaluation, not online output scoring inside the product | A manual grading rubric is enough for the course deliverable; a product-level scoring loop would be a separate feature | `test_docs/docs/pdf_eval_scorecard.md` |

### 2. Workflow clarity

| Feedback | Decision | Action | Justification | Evidence |
|---|---|---|---|---|
| Connect the architecture to one complete workflow | Poster update | Add one simple flow: upload contracts -> extract fields -> detect one rule deviation -> ask a cited question | This makes the system legible in a few seconds without changing the implementation | Poster text already lists the three modes, but not one stitched example |
| Make the architecture and workflow easier to read | Poster update | Reduce text density, keep one pipeline view, enlarge key labels | The current poster contains the right content but too many parallel explanations | `Legal_Co_Pilot_Poster_draft.pdf` |

### 3. Legal scope, risk, and trust

| Feedback | Decision | Action | Justification | Evidence |
|---|---|---|---|---|
| Explain legal scope more clearly, especially jurisdiction | Poster update + Repo/code update | State the current scope conservatively as Austria-focused / configurable by corpus and rule inputs | The repo already supports jurisdiction metadata, but not a validated multi-jurisdiction legal engine | [ingestion.py](/home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot/ingestion.py:402), [README.md](/home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot/README.md:164) |
| Explain how hallucinations, wrong citations, and missed clauses are handled | Poster update + Repo/code update | Add a dedicated limitations/risk section with mitigation measures | This is important for legal trustworthiness and should be explicit, not implied | Poster “What Didn’t Work”, `qa.py`, `review.py`, `extraction.py` |
| Mention privacy / security concerns | Poster update | Frame local Ollama and on-premises operation as an architectural option, not a guarantee | The provider-agnostic design supports local operation, but the system does not yet implement a full enterprise privacy model | [llm_client.py](/home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot/llm_client.py:23) |

### 4. Modularity and extensibility

| Feedback | Decision | Action | Justification | Evidence |
|---|---|---|---|---|
| Maybe emphasize the modular approach | Already covered, make more explicit | Highlight the separation into ingestion, extraction, review, and Q&A plus provider-agnostic LLM support | This is already present in the architecture and code | [main.py](/home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot/main.py:15), [README.md](/home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot/README.md:8) |
| Could have MCP support for other agents/systems | Not implemented | Mention as future work only | MCP integration would broaden system interoperability, but it is not needed to validate the current RAG-based legal copilot | No MCP layer exists in the current app |

### 5. Testing on larger and more difficult documents

| Feedback | Decision | Action | Justification | Evidence |
|---|---|---|---|---|
| Maybe a larger quantity of larger documents would be a better challenge | Implement partially | Reference the hard-test setup and explain that larger-PDF evaluation is part of the next validation step | The repo already contains a rubric and harder batch scripts; what is missing is surfacing this clearly | `test_docs/scripts/pdf_hard_run.sh`, `test_docs/docs/pdf_eval_scorecard.md` |
| Improve handling of unstructured parts, tables, or block charts | Not implemented for final scope | Keep as future work under layout-aware parsing | This is a real limitation of the current chunking/parsing pipeline and should be stated honestly rather than overclaimed | Poster “What Didn’t Work”, [ingestion.py](/home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot/ingestion.py:154) |

## Unique Feedback Items

| Feedback | Decision | Action | Justification |
|---|---|---|---|
| Add custom-prompt-driven extraction categories with suggestions | Not implemented | Keep as future UX enhancement | Current extraction already accepts arbitrary user-defined fields; automatic category suggestion is useful but not required for the final deliverable |
| Add a product feedback loop so the agent learns what was good/bad | Not implemented | Keep as future work | For a legal assistant, changing behavior from live user feedback introduces traceability and validation concerns; first priority is grounded, auditable behavior |
| Improve rule inference from natural language | Not implemented for final scope | Keep as future work and mention current brittleness explicitly | This is already acknowledged in the poster and is a genuine model/pipeline challenge |

## Poster Update Checklist

Recommended poster revisions:
- add one `Evaluation` panel with extraction, review, citation, and Q&A quality criteria
- add one `Example Workflow` strip from upload to cited answer
- add one `Scope and Risk` box with jurisdiction, limitations, and mitigation
- simplify the architecture panel to one end-to-end flow
- increase readability by enlarging small text and reducing empty space between sections

## Repo / Code Review Notes

These are repo-level issues discovered during review and should be fixed because they weaken the credibility of the presentation:

1. [RUNBOOK.md](/home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot/RUNBOOK.md:31) contains a malformed URL: `http:///127.0.0.1:8000/...`.
2. [README.md](/home/konsti/Documents/Uni/Master/sem2/Applied-Gen-AI/Lawyer_Co-Pilot/README.md:11) describes a `backend/` and `frontend/` layout that does not match the actual flat repo structure.
3. Evaluation assets exist, but there was no single doc connecting the smoke test, hard test, expected outputs, and scorecard.

## Final Decision Summary

Implemented now:
- clearer evaluation story
- clearer workflow explanation
- clearer scope / limitations framing
- repo documentation cleanup that supports those claims

Deferred with justification:
- MCP integration
- learning feedback loop
- multi-jurisdiction validation engine
- layout-aware parsing redesign
- stronger rule inference from natural language
