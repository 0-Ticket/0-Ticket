version: test-verdict-1
Return only a JSON object for the Verdict contract. Do not include markdown fences or prose.
Use exactly these fields: verdict (tp, fp, or unknown), confidence (0 to 1), summary, evidence,
recommended_action, needs_human, and human_reason. Evidence is a list of objects with ref_type,
ref_id, and note. Use the evidence_id from the input as ref_id.
