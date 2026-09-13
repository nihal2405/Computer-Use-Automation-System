# Preserved failed acceptance attempt

This attempt installed a fresh locked environment and passed all 349 tests.
The additional genuine-artifact suite passed 39 of 40 cases and stopped acceptance.
See [acceptance.json](acceptance.json) for the actual failed stage and source hashes.

`test_human_can_complete_interrupted_navigation_without_repeating_it` incorrectly
copied an optional postcondition from the hand-authored fixture to construct its
test obstacle. The generated capability did not contain that optional condition,
so the test failed to stop before account navigation. The test now constructs
the reviewed Accounts-heading precondition explicitly and selects the step by
operation rather than a fixture position. Runtime handoff code was unchanged.

This report and its source archive are preserved, not rewritten as a success.
The corrected independent fresh run is in [phase9-verified](../phase9-verified/README.md).
The real CLI scenario stage was not reached in this first attempt.
