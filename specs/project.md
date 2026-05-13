<!-- This is from a brief report I was writing to the hired consultant that is helping me search for jobs. Trying to mentally work through how to talk about this project as a portfolion project, and for resume entries. etc. -->
### job-scraper-9000

An automated pipeline that scrapes job postings from every major source, uses LLM Agents to classify remote-work policy, match jobs to your skills, and then presents the curated list daily for your perusal. Cuts a fire-hose of listings down to a daily shortlist of roles actually worth reading.

Built for my own personal job hunting, and as a learning project to experiment with some Multi-agent Systems I had read about but not been able to implement before. 

**Pipeline:**

The full pipeline has four phases:

1. **Ingestion**
	* Scrape LinkedIn, Indeed, ZipRecruiter, Glassdoor, and direct ATS boards (Greenhouse, Lever, Ashby) for target keyword searches. 
	* Deduplicate across sources using a composite hash of company + title + location.
2. **Remote Filter Agent (OpenAI Framework)** 
	* Send each description to the Remote Filter Agent.
	* Distinguish genuine remote-flexible roles from deceptive hybrid listings. Returns a binary PASS/TRASH decision with a short rationale. 
	* Runs on local hardware (RTX 4090).
3. **Skills Fit  scoring Agent** — Batch-send surviving postings to a cloud LLM (OpenAI / Anthropic) or to local Ollama instance: 
	* Score each against the candidate profile, with a rubric:
		* Technical Overlap: Does the stack match my core experise (C++, Python, AI, data engineering, etc.
		* Level Alignment: Senior/Lead, or entry role?
		* Domain Context: involves engineering, automation, or deep learning domains, where I have deep experience
	* Returns structured JSON w/ fit_score, top_matches, gaps, verdict
4. **Collate and dispatch the hot list to user**:
	* Get the list into my hands ASAP via email or custom web GUI (Likely FastAPI, love it)
	* Room for future automation: 
		* Browser extension calling backend LLM Agent to fill DOM fields
	
**Current state:** 
* [x] Phase 1 (scraper library) is built and tested.
	* [x] Precommit hooks for lint/formatting
	* [x] GitHub Actions for tests during push/PR
* [ ] **Phase 2 (Remote Filter):** 
	* [x] Build validation schema to sanitize agent output
	* [x] Agent is functional. 
	* [ ] Teacher + HITL implemented, assembling golden dataset
	* [ ] Build evaluation framework to enable tracking drift & compare eligible foundation models using golden data. 
* [ ] Phase 3 (Skills Fit): designed but not implemented.
	* [ ] Similar bones to Remote Filter agent, adjust for new Pydantic schema for validation
* [ ] Phase 4 (Azure Deployment): 
	* [ ] use IaC (Bicep) & Az CLI to deploy

**Keywords**:
* model evaluation
* telemetry
* prompt engineering
* few-shot
* human-in-the-loop
* Infrastructure-as-Code

  



  