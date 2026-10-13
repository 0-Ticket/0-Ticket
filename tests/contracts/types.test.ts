import type { RawRecord, HumanReview, Ticket, Entity } from '../../frontend/src/contracts/index.js';
const raw: RawRecord = { raw_id: 'raw_sample', source_type: 'example.custom', received_at: 1, payload: '', sha256: '' };
const review: HumanReview = { ticket_id: 'tk_sample', reviewer: 'sample', decision: 'tp', overturned: false, reason: null, created_at: 1 };
const entity: Entity = { type: 'example.custom', value: 'sample' };
// @ts-expect-error nullable reason must still be present
const missing: HumanReview = { ticket_id: 'tk_sample', reviewer: 'sample', decision: 'tp', overturned: false, created_at: 1 };
// @ts-expect-error fixed enum is closed
const wrong: HumanReview = { ...review, decision: 'custom' };
// @ts-expect-error required string cannot be null
const nullId: RawRecord = { ...raw, raw_id: null };
const verdict: Ticket['verdict'] = null;
void [raw, review, entity, missing, wrong, nullId, verdict];
