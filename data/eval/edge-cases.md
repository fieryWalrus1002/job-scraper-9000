# Eval Edge Cases

Known failure modes and ambiguous cases surfaced during eval runs.

---

## EC-1 — Regional dialect requirement misread as local presence

**Record:** `466e17c1`  
**Job:** Data Annotation Specialist, Arabic Language Najdi/Hijazi Dialect @ Cohere  
**Gold:** `pass` (fully_remote)  
**Pred:** `trash` (reason: `requires_local_presence`)  
**First seen:** `gpt4o_mini_baseline`

The agent read a regional dialect requirement ("Najdi/Hijazi") as implying the candidate must be physically located in the Najd/Hejaz region of Saudi Arabia. The human reviewer correctly identified it as a language skill requirement on a fully remote role.

**Failure mode:** Agent cannot reliably distinguish "must speak this dialect" from "must live where this dialect is spoken." Likely compounded by wording in the posting around native-speaker availability or regional hours.

**Golden dataset implication:** Add more remote annotation/contractor roles with regional language requirements to confirm whether this is a systematic blind spot or a one-off.
