# Persisted result reports and regression comparison

These standalone commands consume an execution directory produced by
`scripts/certify_runner.py`. They add a human-readable HTML report, JUnit XML
for CI consumers, and a machine-readable comparison between two runs. Python
3.11+ is sufficient; there are no additional packages or network calls.

This is post-processing of saved JSON, not a new conformance execution or
independent verification of suite artifacts. Synthetic test fixtures are not
conformance evidence. These tools do not implement Verify automation, combined
execution, TestNG/Extent adapters, expected-failure suppression, or certification.

## Generate reports

After the existing live runner produces an `execution/` directory, use its actual
path in place of `<run>`:

```bash
python scripts/report_results.py results/certify/<run>/execution --html results/report.html --junit results/junit.xml
```

Outputs must have distinct, previously unused paths, with existing parent
directories. This prevents accidental replacement of saved evidence. Reports
are standalone files with no scripts, external fonts, or network dependencies.
Suite-supplied text is escaped in HTML. Suite URLs are not turned into links.
Review report content before publishing: a raw persisted summary can contain
internal errors or other sensitive environment information.

The command returns the persisted release gate's exit code:

| Exit | Meaning |
| --- | --- |
| 0 | Persisted harness gate accepted the run |
| 1 | Persisted harness gate rejected the run; reports still written |
| 2 | Infrastructure failure or invalid evidence/output; valid ERROR runs can still produce reports |

Do not interpret the existence of an HTML/XML file as a passing gate. A render
failure returns 2. If writing the second output fails, the first file may remain;
select fresh output paths when retrying. The commands never modify input JSON.

## JUnit semantics

Each module/variant is a testcase, with generated suite IDs kept in `system-out`.
The mapping preserves authoritative suite outcomes:

| Saved result | JUnit representation |
| --- | --- |
| PASSED | Passing testcase |
| FAILED | Failure |
| WARNING, REVIEW, SKIPPED | Skipped testcase; original value retained |
| Infrastructure or cancellation failure | Error |

A separate **Persisted release gate** testcase is added whenever the saved
gate exit is 1 or 2. It preserves policy rejection, export failures, and
preflight failures even if individual modules appear to pass. Consumers must
not count this synthetic gate case as an additional OIDF module. A tolerated
module failure still appears as a JUnit failure: no protocol finding is hidden.

## Compare runs

```bash
python scripts/compare_results.py results/certify/<baseline>/execution results/certify/<candidate>/execution --output results/comparison.json
```

Run IDs change on every execution. Comparisons instead match component, plan
name, test name, and all selected variants, with variant key order ignored.
Different scenarios, components, or saved benchmark policies are rejected as
incomparable. Source revision changes are permitted so upgrades can be assessed;
inspect the original run's `sources.lock.json` separately for provenance.

The comparison uses this explicit severity order:
`PASSED < WARNING < REVIEW < SKIPPED < FAILED`. Moving right is a regression;
moving left is an improvement. Added FAILED, REVIEW, or SKIPPED modules count
as regressions. Added PASSED/WARNING modules are listed without regression.
Any removed module/variant means incomplete coverage. A variant change therefore
appears as one removal and one addition, rather than a misleading direct match.

| Exit | Meaning |
| --- | --- |
| 0 | No regression under the comparison policy |
| 1 | At least one regression |
| 2 | Either run is infrastructure-failed, coverage was removed, or inputs are invalid/incomparable |

An unchanged failing run returns comparison exit 0 while retaining
`candidate_gate_exit: 1`. Always enforce the candidate's original gate as well
as any regression policy. A comparison does not replace that gate.

## Evidence validation and verification

Both commands reject duplicate module identities, duplicate JSON properties,
unknown suite outcomes, inconsistent normalization, inconsistent summary exit
codes, nonterminal results without an explicit infrastructure failure, and
entirely skipped runs presented as passing. An ERROR summary without results
is supported for a readiness failure before suite execution. A JSON input file
is limited to 16 MiB. Deliberately larger suites need a reviewed limit change.

Run the isolated reporting suite without Docker or upstream checkouts:

```bash
python -m unittest discover -s tests -p test_result_reporting.py -v
```

The 19 tests cover untrusted HTML, XML character handling, original result
semantics, export and preflight failures, malformed input, output preservation,
variant matching, coverage removal, policy changes, and comparison exit codes.
All fixtures are explicitly synthetic.
