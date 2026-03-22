After the first test run, do the following loop for a MINIMUM of 9 rounds:

Round Protocol:
1. Run the full test suite
2. Collect ALL failures, warnings, and observations — do not stop at the first failure
3. Categorise each issue:
   - [APP BUG] — fix in application source code
   - [TEST BUG] — fix in test or page object code
   - [MISSING FEATURE] — scaffold the missing feature with a TODO and a passing stub test
   - [FLAKY TEST] — add retry logic or wait strategy, document the root cause
4. Apply ALL fixes before rerunning — do not rerun after fixing just one issue
5. Log each round in a file: test-run-log.md in this format:

   ## Round N — [PASS COUNT] passed / [FAIL COUNT] failed / [SKIP COUNT] skipped
   ### Fixed this round:
   - [APP BUG] Description of fix — file changed
   - [TEST BUG] Description of fix — file changed
   ### Still outstanding:
   - Issue description — reason not yet fixed
   ### Observations:
   - Any non-failure notes (slow queries, UI inconsistencies, accessibility warnings)

6. After Round 9, produce a final summary:
   - Total issues found across all rounds
   - Issues resolved vs outstanding
   - Recurring failure patterns
   - Recommendations for the development team

---

## STOPPING CRITERIA

Stop the loop early only if:
- All tests pass for 3 consecutive rounds with zero flaky retries
- You have completed Round 9 (whichever comes first)

Do NOT stop because a fix seems complex. Scaffold a stub and mark it TODO if needed.

---