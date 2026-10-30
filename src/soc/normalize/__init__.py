"""OCSF normalization (box 6), Lookup join (boxes 6 -> 7) and entity branch (boxes 10-13).

Box 6 turns stored C2 into C3 (then C5) and C13 by per-scenario alias tables
(C20) only, and keeps what it cannot turn as C12. It never calls an LLM.
"""
