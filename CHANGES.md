# CHANGES.md

## Feedback Summary

Overall feedback was very positive. Reviewers appreciated:

- The clear legal use case and practical relevance.
- The focus on trustworthy answers through source citations and auditability.
- The modular RAG-based architecture and the ability to work only on provided legal documents.
- The clear presentation of legal workflows and UI components.
- The emphasis on reducing hallucinations and increasing reliability.

## Main Improvement Suggestions
The following sections address the most frequently recurring feedback points raised by reviewers during presentation.

### Evaluation, Metrics & Testing
Reviewers encouraged additional testing with larger document collections and more challenging legal scenarios.
Additionally several reviewers suggested adding more quantitative evaluation results, such as:
- Extraction accuracy
- Citation correctness
- Retrieval quality
- Question-answering performance
- Comparison against manual legal review

**Changes made:**  
A structured evaluation framework was designed to systematically assess the performance of the system in document understanding and question-answering tasks. The evaluation dataset consists of three representative contract types, namely a SaaS Master Service Agreement, an IT Services Agreement, and a Non-Disclosure Agreement. These documents were used to define a controlled benchmark covering extraction tasks, rule-based review checks, and question-answering scenarios.  
The evaluation methodology is based on a combination of quantitative coverage metrics that measure the degree to which system outputs are grounded in source material. These metrics include extraction quote coverage, page reference coverage, the proportion of responses supported by verifiable citations, and the average number of supporting sources per answer. All evaluation runs produce structured artifacts that enable consistent comparison and reproducibility of results across different model configurations.  
To ensure robustness, the evaluation was conducted across multiple model backends, including GPT-4o and Gemini 2.5 Flash Lite. Both models demonstrated comparable performance across all metrics, indicating stable behavior of the system independent of the underlying language model.  
In addition to the baseline evaluation, a secondary stress-testing setup was introduced to assess system performance under increased complexity. This extended evaluation includes more challenging extraction and review scenarios designed to test the limits of document grounding and retrieval consistency.  
Overall, the evaluation framework emphasizes reproducibility, citation reliability, and grounding fidelity as the primary criteria for assessing system quality in a document-centric legal assistant setting.

### Workflow & Architecture Clarity
Multiple reviewers recommended presenting the workflow more clearly and simplifying complex diagrams. A concise end-to-end example (upload → extraction → rule review → question answering) was suggested.

**Improved system walkthrough and accessibility documentation:**  
To address feedback regarding workflow clarity and the complexity of system presentation, a comprehensive end-to-end demonstration was created. This includes a full setup walkthrough from environment configuration and dependency installation to server execution. In addition, an exhaustive demonstration of all system functionalities is provided, covering the complete pipeline from document upload through extraction, rule-based review, and question answering. The video is further enhanced with on-screen text overlays and synchronized voice narration to improve accessibility and ensure clarity of explanation for all users.

### Legal Scope & Risk Handling
Feedback suggested clarifying:
- Supported jurisdictions
- Adaptability to different legal systems
- Handling of hallucinations
- Citation reliability
- Missing clauses and legal risks
- Privacy and security considerations

**Clarification:**  
We deliberately did not address jurisdiction-specific legal correctness, legal risk assessment, or clause validity. As the project was developed by computer science students rather than legal practitioners, implementing and validating such functionality would require domain expertise well beyond the intended scope of this work. Instead, the system is explicitly designed as a document-grounded legal assistant. Its purpose is to retrieve, analyze, and summarize information contained in user-provided documents while providing transparent source citations. Consequently, the system does not claim to provide legal advice, legal interpretation, or compliance guarantees. This limitation and the intended scope of the project are documented in the README under *Scope and Limitations*.  
Furthermore, the system does not cache, store, or persist any user-provided input beyond the active session. All uploaded documents and queries are processed in-memory solely for runtime analysis and response generation. Once the session ends, no user data is retained. This design minimizes data exposure and reduces the risk of unintended information leakage.

### Feature Suggestions
Additional ideas included:
- Output confidence/scoring mechanisms
- More flexible extraction via user-defined prompts
- Improved handling of unstructured document sections, tables, and diagrams
- Enhanced rule inference from natural language
- Potential integration with external systems (e.g., MCP support)

**Implemented Capabilities and Deferred Enhancements:**  
Some of the suggested features were already supported by the system. The extraction workflow allows users to define arbitrary extraction fields at runtime, which are passed directly to the LLM pipeline without requiring a predefined schema. Likewise, rule reviews are based on natural-language rules entered by the user, enabling flexible document checks without structured rule definitions.  
Other suggestions, such as confidence scores for answers, improved handling of complex tables and diagrams, and integration with external systems (MCP), were not implemented due to time constraints. These features were considered out of scope for the project but represent interesting opportunities for future development.

### Poster & Presentation
Some reviewers suggested:
- Larger text and improved readability
- Reduced visual complexity
- Better use of whitespace and layout balance

**Changes made:**  
_[Describe poster improvements here.]_