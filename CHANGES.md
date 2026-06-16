# CHANGES.md

This document provides an overview of the main reviewer feedback during the presentation in the poster session and describes the resulting improvements and made design decisions.

## Feedback Summary

The overall feedback seemed very positive and encouraging. Reviewers especially appreciated:

- The clear legal use case and practical relevance.
- The focus on trustworthy answers through source citations.
- The RAG-based architecture and the ability to work only on provided legal documents.
- The clear presentation of legal workflows and UI components.
- The emphasis on increasing reliability of the system.

## Main Improvement Suggestions
The following sections address the most frequently recurring improvement suggestions raised by reviewers during the poster session.

### Evaluation, Metrics & Testing
Reviewers encouraged additional testing with larger document collections and more exhaustive legal scenarios multiply.
Additionally several reviewers suggested adding more quantitative evaluation results, such as:
- Extraction accuracy
- Citation correctness
- Retrieval quality
- Question-answering performance
- Comparison against manual legal review

**Changes made:**  
A structured evaluation framework was designed to systematically assess the performance of the system in document understanding and question-answering tasks. The evaluation dataset consists of three representative contract types, namely a SaaS Master Service Agreement, an IT Services Agreement, and a Non-Disclosure Agreement. These documents were used to define a benchmark suite covering extraction tasks, rule-based review checks, and question-answering scenarios.  
The evaluation methodology is based on a combination of different metrics that measure the degree to which system outputs are grounded in source material. These metrics include extraction quote coverage, page reference coverage, the proportion of responses supported by verifiable citations, and the average number of supporting sources per answer. All evaluation runs produce structured measurments that enable consistent comparison and reproducibility of results across different model configurations.  
To ensure robustness, the evaluation can be conducted on different model backends, including GPT-4o and Gemini 2.5 Flash Lite. Both models demonstrated comparable performance across all metrics, indicating stable behavior of the system independent of the underlying language model.  
In addition to the baseline evaluation, a secondary, more extensive setup was introduced to assess system performance under increased complexity. This extended evaluation includes more challenging extraction and review scenarios designed to test the limits of document grounding and retrieval consistency.  
Overall, the evaluation framework focuses on reproducibility, reliable citations, and strong grounding as the main ways to measure system quality in a document-based legal assistant.

### Workflow & Architecture Clarity
Multiple reviewers recommended presenting the workflow in an easy and quick overview to help new users getting started with the system. A concise end-to-end example including the upload of documents, the extraction of legal keywords, as well as a showcase of the rule review and the question answering feature was suggested.

**Improved system walkthrough and accessibility documentation:**  
To address the feedback regarding workflow clarity and system presentation, a comprehensive end-to-end demonstration was created. This includes a full setup walkthrough from configuring a virtual environment, to installing all dependencies required, up to finally running the server. In addition, an exhaustive demonstration of all system functionalities is provided, covering the complete pipeline from document upload, extraction, rule-based review, and question answering. The video is further supported with on-screen text fade-ins and AI-generated voice narration to improve accessibility and ensure clarity of explanation for all users.

### Legal Scope & Risk Handling
Feedback suggested clarifying:
- Supported jurisdictions
- Adaptability to different legal systems
- Handling of hallucinations
- Citation reliability
- Missing clauses and legal risks
- Privacy and security considerations

**Clarification:**  
We deliberately did not address jurisdiction-specific legal correctness, legal risk assessment, or clause validity. As we are computer science students and no lawyers we simply lack the required domain expertise to implement and validate such functionality within a reasonable amount of time. Instead, the system is explicitly designed as a document-grounded legal assistant. Its purpose is to retrieve, analyze, and summarize information contained in user-provided documents while providing grounding source citations. Consequently, the system does not claim to provide legal advice, legal interpretation, or compliance guarantees. These limitation and the intended scope of the project are also documented in the README under the section *Scope and Limitations*.  
Furthermore, the system does not cache, store, or persist any user-provided input regarding prompts made by the user. Uploaded documents however, as well as user prompts are exposed to a LLM model API defined by the system backend. The system is designed to minimize the risk of unintended information leakage and does not communicate with any additional services than the LLM model.

### Feature Suggestions
Ideas of reviewers for future features included:
- Output confidence/scoring mechanisms
- More flexible extraction via user-defined prompts
- Improved handling of unstructured document sections, tables, and diagrams
- Enhanced rule inference from natural language
- Potential integration with external systems (e.g., MCP support)

**Implemented Capabilities and Deferred Enhancements:**  
Some of the suggested features were already supported by the system. The extraction workflow allows users to define arbitrary extraction fields at runtime, which are passed directly to the LLM pipeline without requiring a predefined schema. Likewise, rule reviews are based on natural-language rules entered by the user, enabling quick document checks without specific rule definitions.  
Other suggestions, such as confidence scores for answers, improved handling of complex tables and diagrams, and integration with external systems (MCP), were not implemented due to time constraints. These features would have exeeded the scope of the project but represent interesting opportunities for future development.

### Poster & Presentation
Some reviewers suggested:
- Larger text and improved readability
- Reduced visual complexity
- Better use of whitespace and layout balance

**Changes made:**  
- Increased text size to improve readability from a distance.
- Reduced and condensed text content to lower visual complexity.
- Reformulated key design decisions to communicate project goals and architectural choices more clearly.
- Added an explicit list of evaluation metrics to improve transparency of the evaluation methodology.
- Introduced a visual user workflow illustrating the complete process from document upload to extraction, rule review, and question answering.
- Improved whitespace usage and overall layout balance to create a cleaner and more structured poster design.