"""Bounded model-to-test interchange. No exec or eval."""
import ast
import re


def artifact_response(raw):
 # -p text output may include kubectl warnings. Only accept one bounded Python artifact;
 # never evaluate surrounding prose, commands, paths, or agent claims.
 matches=re.findall(r'(?ms)^```python[ \t]*\r?\n(.{1,19999}?)^```[ \t]*$',raw)
 if len(matches)!=1:raise ValueError('Expected exactly one fenced Python file')
 text=matches[0];ast.parse(text);return text

