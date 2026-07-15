# PolicyAssist — Standards Compliance Analysis

This document maps PolicyAssist (as currently built) against the UK government standards and guidance that apply to it. It is not an exhaustive legal review — it is a structured gap analysis to inform what must change before the 800-officer rollout.

**Sources researched:**
- GDS Service Standard (14 points)
- GDS Technology Code of Practice (TCoP, 13 points)
- NCSC Guidelines for Secure AI System Development
- NCSC: AI and Cyber Security — What You Need to Know
- NCSC: ChatGPT and Large Language Models — What's the Risk?
- NCSC: Prompt Injection Is Not SQL Injection
- NCSC Cloud Security Principles (14 principles)
- AI Playbook for the UK Government (CDDO/Cabinet Office, Feb 2025)
- AI Cyber Security Code of Practice (DSIT/NCSC, Jan 2025)
- Government Security Classifications Policy (GSCP) + Guidance 1.5

---

## The single biggest unresolved question

Before any other compliance work, the team needs an answer to this:

> **Is it lawful to send Border Force officer query content to Anthropic's (US-based) API?**

NCSC is explicit (from *ChatGPT and Large Language Models — What's the Risk?*):
> "The query **will** be visible to the organisation providing the LLM. Providers may incorporate them in some way into future versions of the model. Queries stored online may be hacked, leaked, or more likely accidentally made publicly accessible."

NCSC's direct advice: *"Not to include sensitive information in queries to public LLMs."*

The Border Force operational policy document is almost certainly classified at **OFFICIAL**, and may be **OFFICIAL-SENSITIVE** if it contains enforcement thresholds, detection methods, or watchlist criteria. The Government Security Classifications Policy (GSCP) requires a Security Advisor assessment to determine the classification. **Until that assessment is complete and Anthropic's data processing agreement is reviewed against it, the app should not be used with real operational queries by serving officers.**

---

## Standards gap analysis

---

### GDS Service Standard — Point 9: Create a secure service which protects users' privacy

**What it requires:**
- Perform due diligence on the security of third-party software and services
- Collect, process and store data securely and in a way that respects users' privacy
- Maintain a live assessment of security risks; assign a senior accountable person
- Follow Secure By Design principles (mandatory)
- Regularly test security controls

**PolicyAssist gaps:**
- No documented security risk assessment exists
- No named senior accountable person for security
- Anthropic has not been assessed against NCSC Cloud Security Principles
- Conversation history stored in a plain JSON file (`chat_log.json`) — no encryption at rest, no access controls, not compliant with CAF B.3 (electronic data at rest protection required for OFFICIAL data per GSCP Guidance 1.5)

---

### GDS Service Standard — Point 11: Choose the right tools and technology

**What it requires:**
- Demonstrate good decision-making about technology choices, including AI specifically
- Understand total cost of ownership and preserve ability to switch suppliers
- Consider how technology impacts user experience — *"avoid situations where your technology choices might reduce the reliability of information given to users or decisions made about them"* — this is a direct reference to AI hallucination risk in government contexts

**PolicyAssist gaps:**
- No documented technology decision record for choosing Claude/Anthropic
- No assessment of vendor lock-in risk (entire system depends on a single commercial API)
- No documented acknowledgement of or mitigation for hallucination risk — officers may act on incorrect policy answers

---

### GDS Service Standard — Point 12: Make new source code open

**What it requires:**
- Publish all new source code openly under an open licence
- Exclude only sensitive information: keys, credentials, fraud-detection algorithms, unannounced policy

**PolicyAssist gaps:**
- Code is not published
- The team must consult their Security Advisor on whether any part of the system prompt or prompt engineering logic constitutes operationally sensitive material before publishing

---

### GDS Service Standard — Point 14: Operate a reliable service

**What it requires:**
- Have a plan for downtime (including dependency outages)
- *"Monitor outcomes for users and ethical issues such as bias, not just technical faults"* — explicitly applicable to AI
- Quality assurance testing must be human-overseen, not only automated

**PolicyAssist gaps:**
- No documented plan for Anthropic API outages; the app returns an unhandled 500 with no fallback or user message
- No monitoring of response quality or accuracy — there is no mechanism to detect the model giving incorrect policy guidance
- No QA process for AI outputs

---

### GDS Technology Code of Practice — Point 6: Make things secure

**What it requires:**
- Encryption, single sign-on, two-factor authentication (2FA), fine-grained access control, usage monitoring and alerts
- *"Timely patching"*
- Ongoing assurance — not a one-time assessment

**PolicyAssist gaps:**
- No authentication at all — any user who can reach the URL can use the app and read all prior conversation history
- No 2FA
- No RBAC — all users see the same shared conversation history
- No usage monitoring or alerting
- No patching process documented

---

### GDS Technology Code of Practice — Point 7: Make privacy integral

**What it requires:**
- Privacy by design
- A Data Protection Impact Assessment (DPIA) if the service involves decisions that can have significant impact on individuals
- Support for GDPR rights: erasure, restriction of processing, data portability

**PolicyAssist gaps:**
- No DPIA has been conducted
- The conversation log contains officer query content, which may include personal data (officer identities, details about passengers or cases)
- There is no mechanism for an officer to request deletion of their conversation history
- UK GDPR Article 35 is very likely engaged: the system could influence decisions with significant impact on individuals (immigration enforcement)

---

### GDS Technology Code of Practice — Point 5: Use cloud first

**What it requires:**
- For cloud/SaaS dependencies, follow NCSC Cloud Security Principles
- Be aware of offshoring and data residency policy

**PolicyAssist gaps:**
- Anthropic's API processes queries on US infrastructure — data residency has not been assessed
- No evidence of NCSC Cloud Security Principles assessment for Anthropic as a supplier

---

### NCSC — Guidelines for Secure AI System Development

**What it requires:**
The guidelines cover four lifecycle phases. PolicyAssist is a *System Operator* deploying a third-party model. Key requirements:

- *"Do you understand your data, model and ML software supply chains and can you ask suppliers the right questions on their own security?"*
- Understand AI-specific vulnerabilities as distinct from standard cyber threats
- Establish incident management processes specific to AI
- Ongoing logging and monitoring throughout the service lifecycle

**PolicyAssist gaps:**
- No documented understanding of Anthropic's model, training data, or infrastructure security
- No AI-specific incident management plan
- No AI-specific threat model
- The `chat_log.json` is not a security log — it has no timestamps, user IDs, or integrity controls

---

### NCSC — ChatGPT and Large Language Models: What's the Risk?

**What it requires (direct NCSC advice):**
- Do not include sensitive information in queries to public LLMs
- Thoroughly understand the provider's terms of use and privacy policy before deployment
- Consider self-hosted models for sensitive work

**PolicyAssist gaps:**
- No controls prevent officers from including sensitive case details or passenger information in queries
- No evidence that Anthropic's data processing agreement has been reviewed
- No assessment of whether query data is used for Anthropic model training
- No consideration of a self-hosted alternative for sensitive use

---

### NCSC — Prompt Injection Is Not SQL Injection

**What it requires:**
- Treat prompt injection as a residual risk that cannot be fully eliminated
- Use deterministic (non-LLM) safeguards to constrain what the model can do
- Mark data sections as distinct from instruction sections in prompts
- Log full input and output for anomaly detection
- Limit the model's permissions to the minimum needed

**PolicyAssist gaps:**
- No prompt injection threat model
- No input sanitisation or guardrails on user-submitted queries
- No logging of queries and responses for security purposes (the JSON file logs for context, not security)
- OWASP rates prompt injection as the #1 vulnerability in generative AI applications — it is unaddressed

---

### NCSC Cloud Security Principles

The Anthropic API must be assessed against all 14 principles. The most critical gaps based on what is publicly known:

**Principle 1 — Data in transit protection**
- API calls must use TLS 1.2+. Anthropic's API does use HTTPS; this is likely met but must be verified and documented.
- The team must confirm Anthropic holds SOC2 Type II or equivalent (ISO 27017:2015, CSA STAR).

**Principle 2 — Asset protection and resilience**
- The `chat_log.json` file is an asset. It must be on encrypted storage. There is no evidence this is the case.

**Principle 8 — Supply chain security**
- *"Third party supply chains should support all of the security principles which the service claims to implement."*
- The team must understand Anthropic's own supply chain: data centres, compute providers (likely AWS), and subprocessors.
- This is a substantive assessment requirement — Anthropic's security posture alone is not sufficient; the full stack must be considered.

**Principle 9/10 — Secure user management / Identity and authentication**
- Currently unmet: the app has no authentication.

**Principle 13 — Audit information and alerting**
- Requires immutable, machine-readable audit logs of all data accesses, authentication events, and configuration changes.
- Logs must not be deletable during a defined retention period.
- An RBAC auditor role must be able to review logs without wider privileges.
- The `chat_log.json` file meets none of these requirements.

---

### AI Playbook for the UK Government (CDDO, Feb 2025)

**What it requires — key points for PolicyAssist:**

**Algorithmic Transparency Recording Standard (ATRS) — mandatory**
> *"Central government departments and arm's length bodies must document algorithmic tools used in decision-making."*

Border Force is part of the Home Office, a central government department. ATRS registration is not optional. The use of AI in policy query-answering must be documented and published. This has not been done.

**Human control requirement:**
> *"For applications where instant responses are required and human review is not possible in real time, such as chatbots, ensure human control at other stages. Humans must validate high-risk decisions influenced by AI."*

If a Border Force officer acts on a PolicyAssist answer to make a decision about a passenger (e.g. whether to refer to the DHO, whether to detain), that is a high-impact decision. Officers must be given clear guidance that AI answers must be verified against the manual before acting.

**High-risk use case prohibition:**
> *"AI should not be used on its own in high-risk areas which could cause harm."*

Immigration enforcement decisions about individuals are high-risk. PolicyAssist must be positioned as a reference aid, not a decision-making tool, and this must be technically enforced (e.g. prominent disclaimers, logging of reliance) — not just a note in a manual.

**Procurement requirements:**
- Anthropic must be engaged through a Crown Commercial Service framework (AI DPS or Technology Products & Associated Services 2) unless an exemption applies.
- The contract must specify requirements for data strategy, bias mitigation, and data ethics.
- There is no evidence a formal procurement process was followed for the hackathon build — this must be remediated before rollout.

**Spend assurance:**
- If total spend (development + API costs for 800 users) exceeds £1m, full GDS/CDDO assurance against the Service Standard is required.

---

### AI Cyber Security Code of Practice (DSIT/NCSC, Jan 2025)

This January 2025 code treats Border Force as a **System Operator** (deploying a third-party AI). Key requirements:

**Third-party due diligence (quoted):**
> *"System Operators shall conduct an AI security risk assessment and due diligence process assessing AI-specific risks."*
> *"System Operators shall re-run evaluations on released models that they intend on using."*

**Logging and monitoring (quoted):**
> *"System Operators shall log system and user actions to support security compliance, incident investigations, and vulnerability remediation."*
> *"Monitor the performance of their models and system over time so that they can detect sudden or gradual changes in behaviour."*

**Least-privilege API access (quoted):**
> *"Ensure that the permissions granted to the AI system on other systems are only provided as required for functionality."*

**Incident management (quoted):**
> *"Shall create, test and maintain an AI system incident management plan and an AI system recovery plan."*
> *"Develop and tailor their disaster recovery plans to account for specific attacks aimed at AI systems."*

**User communication (quoted):**
> *"Shall convey to end-users in an accessible way where and how their data will be used, accessed and stored."*
> *"Shall communicate their intention to update models to end-users in an accessible way prior to models being updated."*

**PolicyAssist gaps:** All of the above are unmet. There is no due diligence record, no structured logging, no incident plan, no user-facing data handling notice, and no process for communicating model updates to officers.

---

## Consolidated action list

Grouped by urgency:

### Must resolve before any operational use with real queries

| # | Action | Standard(s) |
|---|---|---|
| A1 | Security Advisor to classify the operational manual and assess whether OFFICIAL-SENSITIVE controls apply | GSCP |
| A2 | Review Anthropic's data processing agreement — confirm query data is not used for training; confirm data residency | NCSC LLM guidance, TCoP Point 7 |
| A3 | Assess whether sending query content to Anthropic's US infrastructure is permissible under Home Office data handling policy | GSCP, TCoP Point 5 |

### Must resolve before rollout to 800 users

| # | Action | Standard(s) |
|---|---|---|
| B1 | Implement authentication (SSO + 2FA, integrated with Home Office identity infrastructure) | TCoP Point 6, Cloud Principles 9/10 |
| B2 | Per-user session isolation — officers must only see their own conversation history | Service Standard Point 9, TCoP Point 7 |
| B3 | Replace `chat_log.json` with an immutable, structured audit log (user ID, timestamp, query, response) | Cloud Principle 13, AI CoP |
| B4 | Encrypt the conversation/audit store at rest | GSCP Guidance 1.5, Cloud Principle 2 |
| B5 | Conduct a Data Protection Impact Assessment (DPIA) | TCoP Point 7, UK GDPR Art. 35 |
| B6 | Register the tool on the Algorithmic Transparency Recording Standard (ATRS) | AI Playbook (mandatory for Home Office) |
| B7 | Conduct documented due diligence on Anthropic against NCSC Cloud Security Principles | Service Standard Point 9, AI CoP |
| B8 | Implement prompt injection threat model and mitigations (input guardrails, output logging, scoped permissions) | NCSC Prompt Injection guidance, AI CoP |
| B9 | Add prominent disclaimer to UI: responses are AI-generated, must be verified before acting | Service Standard Point 14, AI Playbook |
| B10 | Implement error handling and Anthropic API outage fallback with user-visible messaging | Service Standard Point 14 |
| B11 | Conduct formal procurement through CCS framework; establish contract requirements | AI Playbook |
| B12 | Assign named senior accountable person for AI security | Service Standard Point 9 |

### Required for ongoing operation

| # | Action | Standard(s) |
|---|---|---|
| C1 | Establish AI-specific incident response and recovery plan | AI CoP, Service Standard Point 14 |
| C2 | Implement response quality monitoring — human-reviewed QA of AI outputs | Service Standard Point 14, AI Playbook |
| C3 | Publish source code (Flask app) under open licence, excluding sensitive prompt logic | Service Standard Point 12, TCoP Point 3 |
| C4 | Document technology decision record (why Claude/Anthropic, vendor lock-in assessment) | Service Standard Point 11, TCoP Point 5 |
| C5 | Provide officers with written guidance on what to include/exclude from queries and known limitations | AI CoP user communication requirements |
| C6 | Add mechanism for officers to report incorrect or harmful AI responses | AI Playbook |
| C7 | Determine spend assurance requirements (GDS/CDDO assessment if >£1m) | TCoP, AI Playbook |

---

*Sources fetched July 2025. Standards in this area are evolving rapidly — the AI Playbook (Feb 2025) and AI Cyber Security Code of Practice (Jan 2025) are both less than six months old at time of writing. Re-check for updates before submission to assurance.*
