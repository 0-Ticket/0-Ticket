"""OCSF normalization (box 4), Lookup join (box 4 -> 5) and entity branch (box 25).

Box 4 turns stored C2 into C3 (then C5) and C13 by mapping-profile alias tables
(C20) only, and keeps what it cannot turn as C12. It never calls an LLM.
"""
