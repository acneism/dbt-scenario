# Review an existing-project trial

The [participant protocol](PILOT.md) describes the trial. The [pilot form](https://github.com/acneism/dbt-scenario/issues/new?template=01_pilot.yml) can record interest before setup and be updated later. The [bug form](https://github.com/acneism/dbt-scenario/issues/new?template=02_bug.yml) captures implementation or compatibility problems. Publishing either report is a manual action by the participant.

## Establish the case

First identify one actual incremental model, its intended change policy and a concern the participant already has. An anonymized alias is sufficient. Record whether the report comes from an independent team, a tool-author demonstration or a public-model replay. Several reports from one team do not establish several independent pilots.

Confirm the versions, warehouse and supported configuration before asking for completed fixtures. PostgreSQL 16 with Python 3.12, dbt Core 1.11 and dbt-postgres 1.10 is the current scope. A Snowflake/Fusion case or a model requiring refused SQL settings is a compatibility result, not a connected pilot. Record the specific blocker rather than requesting that someone rewrite their business SQL to fit the tool.

For an unclear report, ask for the missing decision-critical fact: a safe reason code, the selected model's configuration, or a small permitted synthetic example. Public source access, production rows and credentials are not prerequisites. Keep follow-up in the participant's chosen channel; the tool does not initiate messages.

## Record evidence as it arrives

| State | Evidence needed | What it establishes |
| --- | --- | --- |
| Interest | A team expresses interest and identifies a concern | A possible participant |
| Attempted | Actual setup steps or a compatibility refusal, with versions | A tried path or blocker |
| First scenario | Participant runs a completed scenario on the chosen model, with outcome and help recorded | Technical use on that model |
| Compared | Same concern/inputs evaluated with existing checks, with human effort recorded | A comparison for that concern |
| Second scenario | Another case is added; authorship, time and assistance are explicit | Independent addition only when no tool-author assistance was needed |
| Retained | Four observed weeks, at least three meaningful CI runs on project changes, and a participant decision to keep the tests | Retention for that team and period |
| Stopped | Participant removes the tests or ends the trial, with reason if shared | A stopped trial; preserve its earlier observations |

A form's selected stage alone does not establish the corresponding evidence. Mark participant-reported observations and independently checked artifacts separately. Unknown minutes are unknown, not zero. CLI elapsed time, CI duration and benchmark samples do not measure human setup effort. Count installation, editing, debugging and assistance in the human comparison. A machine-generated second scenario does not establish independent authoring.

Use the same report for dated updates when possible. Record start/follow-up dates, actual weeks observed, meaningful project-change runs, compatibility problems, help and the participant's kept/removed/stopped decision. A two-week checkpoint does not meet the four-week criterion. Old issue age and repeated manual demo dispatches do not establish retention.

## Classify a mismatch

Reproduce the minimal permitted concern against the chosen model and explicit expected state. An ERROR is not evidence of a model defect. A FAIL needs review of both SQL and the intended business policy. Distinguish a known historical regression, an intentionally injected defect, an unresolved mismatch and a newly confirmed defect. Use a known-correct control where practical.

Run the participant's existing tests against the same concern when feasible. Native key tests can catch duplicate materialization rows; native unit tests can catch many SELECT errors. Do not claim unique detection without the equivalent baseline actually running. If another approach needs similar or less work, record that result.

## Decide what the pilot supports

The original product criterion is three participating independent teams, at least two connecting a real scenario in one working session (target at most 60 minutes with the database ready), reproducing a known defect or replacing a maintained manual check, and retaining the tests for four weeks with at least three meaningful project-change runs each. At least one participant should add the second scenario independently.

Publish only the conclusions supported by observed reports. Author-run controls, stars, installs, interest and public issue requests do not substitute for those criteria. With no participant evidence, keep the adoption and human-effort roadmap items open. New adapter work should follow a concrete participant's need.
