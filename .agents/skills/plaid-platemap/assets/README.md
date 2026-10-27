# Vendored plaid model files

- `plate-design.mzn`, `layout_predicates.mzn`: copied verbatim from
  <https://github.com/pharmbio/plaid> at commit
  `ecf4cfe6d8029dfadfceb79f5d6f2a1814d792c5` (Apache-2.0, see the LICENSE at
  <https://github.com/pharmbio/plaid/blob/main/LICENSE>).
- Do not edit these files; if you upgrade the pin, re-copy both files from
  the new commit and note the new hash in `scripts/plaid_platemap.py`
  (`PLAID_COMMIT`) and in the skill's Prerequisites section.
- The original repo's own examples (regression tests, JSON examples) are not
  vendored; only the two model files the solver needs.
