"""Tests for the OpenHands steward publisher module."""
import importlib.util
import pathlib
import unittest
from unittest.mock import patch

p=pathlib.Path(__file__).resolve().parents[2]/"charts/openhands/files/steward/publisher.py"
s=importlib.util.spec_from_file_location("publisher",p)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
class Publisher(unittest.TestCase):
 """Tests for the steward publisher PR rules."""

 def test_no_generic_or_merge(self) -> None:
  """Verify the publisher issues no generic or merge commits."""
  with patch.object(m,"api") as api:
   for a in ["create","life_head","life_ci","life_ready","merge","push","delete","request","approve","resolve","workflow_dispatch"]:
    with self.assertRaises(ValueError):
     m.dispatch({"action":a})

   api.assert_not_called()
 def test_path(self) -> None:
  """Verify only sanctioned repository paths are writable."""
  for p in ["server/tests/../a.py",".github/workflows/a.yml","server/tests/x.sh","server/app/.git/a.py"]:
   with self.assertRaises(ValueError):
    m.changes({p:"x"})
 def test_other_branch(self) -> None:
  """Verify foreign branches are never pushed to."""
  sha="a"*40
  with patch.object(m,"api",return_value={"state":"open","base":{"ref":"main"},"head":{"repo":{"full_name":m.REPO},"ref":"main","sha":sha},"user":{"login":"alchemmist"}}) as api:
   with self.assertRaises(ValueError):
    m.owned_pr(1,sha)
   assert api.call_count == 1
 def test_qa_create_rejects_unowned_issue(self) -> None:
  """Verify QA issue creation is refused for unowned issues."""
  with patch.object(m,"api",return_value={"state":"open","user":{"login":"alchemmist"},"body":"ordinary issue"}) as api:
   with self.assertRaises(ValueError):
    m.dispatch({"action": "qa_create","issue": 509,"head": "a"*40,"title": "Scoped test","files": {"web/src/test.ts":"x"}})
   assert api.call_count == 1
 def test_qa_files_and_credential_filter(self) -> None:
  """Verify QA file filtering and credential redaction."""
  assert len(m.changes({"web/e2e/filter.spec.ts": "abc"}, True)) == 1
  for v in ["Bearer token","github_pat_fake","https://host"]:
   with self.assertRaises(ValueError):
    m.clean_text(v,1,90)

 def test_retired_mutation_branch_is_not_owned(self) -> None:
  sha = "a" * 40
  pr = {"state":"open","base":{"ref":"main"},"head":{"repo":{"full_name":m.REPO},"ref":"openhands/issue-509/" + "b" * 32,"sha":sha},"user":{"login":"alchemmist"}}
  with patch.object(m,"api",return_value=pr), self.assertRaises(ValueError):
   m.owned_pr(509,sha)
