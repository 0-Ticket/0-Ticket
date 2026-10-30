"""Entity branching (boxes 10-13): where each normalized alert goes, by rules only.

Stage 0 (alerts) in this package: duplicate removal, then scenario Tickets, then
the L1 entity lookup path. Shared entity removal, the Incident check and the L2
entry come later. Run with ``python -m soc.branch [--all]``.
"""
