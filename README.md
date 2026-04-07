# Co-Pilot for Lawyers

An AI tool that reads multiple legal documents to extract specific data, check for rule deviations, and answer questions — all with exact source references.

## The Problem

Lawyers spend a large part of their time reading documents: contracts, court decisions, regulatory texts. Extracting information, assessing risk, and drafting based on precedents is slow and hard to scale.

## What It Does

**Extraction** — Define what you want to know (notice periods, governing law, liability caps…). The system reads all documents and fills a structured table — one row per document, one column per field — with a link to the exact source passage. Missing information is explicitly flagged.

**Rule Review** — Define a playbook ("our standard position is X"). The system checks every document against your rules, flags deviations, and links to the relevant clause. Think: a linter for contracts.

**Q&A** — Ask a question across all documents ("in which contracts can the landlord terminate without cause?"). The system retrieves relevant passages, synthesizes an answer, and cites its sources precisely.

## Core Challenges

- **Source grounding** — Not just "see document X" but "paragraph 3.2(a), page 7: '[…] 30 days' written notice […]'"
- **Handling absence** — Distinguishing *"notice period is 30 days"* from *"not specified"* from *"uncertain"*
- **Rule-based review** — Translating informal rules into consistent checks across documents with different styles and terminology
- **Multi-document consistency** — Running the same extraction across 50 documents and producing a clean, comparable table

## Status

Early stage — problem definition and system design in progress. Tech stack TBD.
