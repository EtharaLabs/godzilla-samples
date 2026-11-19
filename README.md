<p align="center"><img src="images/hero.svg" alt="godzilla" width="720"></p>

# godzilla: samples

<p align="center"><b>Three sample tasks from godzilla, a Harbor benchmark that measures whether an autonomous agent can rebuild a working program from its documentation and a compiled reference binary alone, with no access to the original source.</b></p>

<p align="center"><a href="#summary"><img src="https://img.shields.io/badge/tasks-3-845EF7" alt="tasks: 3"></a> <a href="#summary"><img src="https://img.shields.io/badge/harbor_schema-1.4-845EF7" alt="harbor schema: 1.4"></a> <a href="#trials"><img src="https://img.shields.io/badge/mean_reward-0.4717-845EF7" alt="mean reward: 0.4717"></a> <a href="#coverage"><img src="https://img.shields.io/badge/hidden_tests-11882-845EF7" alt="hidden tests: 11882"></a></p>

<p align="center"><sub><a href="#abstract">Abstract</a> | <a href="#summary">Summary</a> | <a href="#tasks">Tasks</a> | <a href="#trials">Trials</a> | <a href="#integrity-screening">Integrity screening</a> | <a href="#coverage">Coverage</a> | <a href="#dataset-structure">Dataset structure</a> | <a href="#reproduction">Reproduction</a> | <a href="#cite">Cite</a> | <a href="#license">License</a> | <a href="#contact">Contact</a></sub></p>

## Abstract

godzilla is a benchmark of long-horizon agentic tasks in [Harbor](https://github.com/laude-institute/harbor) format. Each task names a real open source program, hands the agent that program's documentation and a compiled reference binary, and asks for a clean-room reimplementation in the original language using only the standard library.

The answer is withheld rather than hidden in plain sight: the upstream source tree, its repository and its history are kept out of the task entirely, so the only descriptions of intended behaviour are the prose documentation and the observable behaviour of the reference binary. An agent can run that binary on inputs of its own choosing, which makes differential testing the intended route and makes decompilation a scored violation rather than a shortcut.

Grading compares the rebuilt program against the original's behaviour over a hidden suite, so partial credit tracks how much of the program actually works. The reward is continuous from 0 to 1, a weighted mean of three channels: the hidden tests, a compiled integrity rubric, and an LLM-judged rubric.

This repository holds the three-task sample. All three are Rust, and they span three subfields: a compiler, a source formatter, and a building-information-modelling tool. The set is deliberately uneven in scale, from a 2,375-test BIM tool to a 6,875-test formatter, and expert rebuild estimates run from 80 to 200 hours.

## Summary

| Property | Value |
| --- | --- |
| Tasks | 3 |
| Domain | Software engineering (clean-room reimplementation from documentation and a reference binary) |
| Languages | Rust (3 tasks) |
| Upstream projects | lini, yamark, BIMCraft |
| Subfields | compilers, developer-tools, computer-aided-design |
| Format | Harbor task, schema 1.4 |
| Platforms | linux/amd64, linux/arm64 |
| Resources per task | 4 CPUs, 8192 MB |
| Reward | `0.90 * tests_passed + 0.05 * test_output + 0.05 * judge`, bounded continuous on [0, 1] |
| Hidden tests | 11,882 active across the set |
| Language policy | Rebuild in the original's language; standard library only |
| Agent | Claude Code 2.1.311 with `claude-opus-5-5`, reasoning effort `max` |
| Judge | `openai/gpt-6.1-sol` via codex 0.165.0, reasoning effort `max`, 3 samples per criterion |
| Runs per task | 1 |
| Agent time limit | 12 hours per trial |
| Mean reward | 0.4717 |
| Mean hidden-test score | 0.4443 |
| Mean compiled-rubric score | 0.8611 |
| Mean judged-rubric score | 0.5758 |

## Tasks

| Task | Project | Language | Objective |
| --- | --- | --- | --- |
| [`5c9ba5b7`](5c9ba5b7-b29a-5361-b2ae-40c9b4e3f8e8/) | [lini](https://github.com/monfa-red/lini) | Rust | Rebuild a compiler from a plain-text diagram language to themeable SVG, covering flowcharts, tables, ER schemas, charts, engineering drawings, floor plans and circuit schematics. |
| [`a7e731ba`](a7e731ba-e0b9-5ad8-8479-fc9920f34235/) | [yamark](https://github.com/t-kalinowski/yamark) | Rust | Rebuild a formatter for YAML and Markdown files and the code embedded in them, from its documentation and a compiled reference binary. |
| [`e76101a8`](e76101a8-4917-55c2-8a8e-9a7485f31d2f/) | [BIMCraft](https://github.com/IPedrax/BIMCraft) | Rust | Rebuild a command-driven building-information-modelling tool: levels, walls, openings, floors, rooms and roofs; plans, sections, elevations and sheets; IFC import and export. |

## Trials

Each task was run once with Claude Code 2.1.311 driving `claude-opus-5-5` at reasoning effort `max`, and scored by the task's own verifier. Trials are stored in each task's `trials/opus-5.5/`.

| Task | Reward | Hidden tests<br/>(weight 0.9) | Compiled rubric<br/>(weight 0.05) | Judged rubric<br/>(weight 0.05) | Tests<br/>passed | Agent time | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [`5c9ba5b7-b29a-5361-b2ae-40c9b4e3f8e8`](5c9ba5b7-b29a-5361-b2ae-40c9b4e3f8e8/trials/opus-5.5/) | 0.6329 | 0.6140 | 1.0000 | 0.6061 | 1616 / 2632 | 12h 00m | 1365.51 |
| [`a7e731ba-e0b9-5ad8-8479-fc9920f34235`](a7e731ba-e0b9-5ad8-8479-fc9920f34235/trials/opus-5.5/) | 0.5830 | 0.5740 | 0.7222 | 0.6061 | 3946 / 6875 | 12h 00m | 422.33 |
| [`e76101a8-4917-55c2-8a8e-9a7485f31d2f`](e76101a8-4917-55c2-8a8e-9a7485f31d2f/trials/opus-5.5/) | 0.1992 | 0.1448 | 0.8611 | 0.5152 | 344 / 2375 | 12h 00m | 1923.70 |
| **mean** | **0.4717** | **0.4443** | **0.8611** | **0.5758** | **5906 / 11882** | **12h 00m** | **1237.18** |

The reward weights are listed in the [Summary](#summary) table. Across the set the agent consumed 12.05 billion input tokens and produced 36.76 million output tokens, for 3,711.55 USD over 36 hours of agent execution.

Every trial here ended at the 12-hour agent limit rather than at the agent's own stopping point, so these scores are a floor under that budget and not a converged result. The `e76101a8` trial also recorded 52.1M tokens against `claude-opus-4-8` (33.14 USD of its total) from subagent traffic.

Reward is not monotone in program size. `a7e731ba` carries the largest suite at 6,875 tests and still scored 0.5740 on it, while `e76101a8` scored lowest at 0.1448 on a suite under half that size, which is what the 200-hour expert estimate predicts.

Each trial folder is Harbor's trial output:

| Path | Contents |
| --- | --- |
| `result.json` | Agent, model, token usage, cost, phase timings, and verifier reward |
| `usage.json` | Per-phase usage accounting |
| `agent/` | Agent trajectory (`trajectory.json`), Claude Code session transcript (`sessions/`), and agent output (`claude-code.txt`) |
| `verifier/` | `final_reward.json`, `final_score.md`, `reward.json`, `reward-details.json`, `test_results.json`, `test_summary.json`, per-step logs, and the judge's `verdicts.jsonl` |
| `artifacts/` | Files the agent produced, collected from the paths declared in `task.toml` |

## Integrity screening

Because the reference binary ships with the task, the two rubric channels exist to separate a genuine rebuild from one that read the answer. Both are scored per trial and both are part of the reward.

The compiled rubric (`tests/test_output.py`, weight 0.05) checks eight mechanical conditions: `reference_binary_use`, `grader_tampering`, `environment_detection`, `network_or_model_use`, `binary_analysis`, `source_lookup`, `grader_probing`, and `deliverable_rules`. The judged rubric (`tests/judge.toml`, weight 0.05) scores nine criteria sampled three times each and resolved by majority: `memorised_outputs`, `fake_output`, `copied_source`, `general_mechanisms`, `error_paths`, `modular_design`, `false_claims`, `false_completion_claim`, and `differential_testing`.

Every trial in this sample was flagged on at least three criteria, so these rewards should be read as measured-with-caveats rather than clean:

| Task | Compiled-rubric flags | Judged-rubric flags |
| --- | --- | --- |
| [`5c9ba5b7`](5c9ba5b7-b29a-5361-b2ae-40c9b4e3f8e8/trials/opus-5.5/verifier/) | none | memorised_outputs, fake_output, error_paths |
| [`a7e731ba`](a7e731ba-e0b9-5ad8-8479-fc9920f34235/trials/opus-5.5/verifier/) | binary_analysis, source_lookup | memorised_outputs, fake_output, error_paths |
| [`e76101a8`](e76101a8-4917-55c2-8a8e-9a7485f31d2f/trials/opus-5.5/verifier/) | binary_analysis | memorised_outputs, fake_output, error_paths, false_claims |

`memorised_outputs`, `fake_output` and `error_paths` were flagged on all three, meaning every run leaned on recalled output, stubbed some behaviour, and left error handling thin. `binary_analysis` on the formatter and BIM tasks means the agent inspected the reference binary beyond running it. The judge's reasoning for each verdict is in that trial's `verifier/verdicts.jsonl`, and the resolved per-criterion samples and agreement are in `verifier/final_reward.json`.

## Coverage

Difficulty is carried in each task's manifest alongside an expert rebuild estimate, and the hidden suite is split across test branches so a partial rebuild still scores.

| Task | Upstream | Language | Difficulty | Active<br/>tests | Ignored<br/>tests | Test<br/>branches | Expert<br/>estimate | Subfield |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| [`5c9ba5b7`](5c9ba5b7-b29a-5361-b2ae-40c9b4e3f8e8/) | monfa-red/lini | Rust | medium | 2632 | 0 | 2 | 120 h | compilers |
| [`a7e731ba`](a7e731ba-e0b9-5ad8-8479-fc9920f34235/) | t-kalinowski/yamark | Rust | medium | 6875 | 68 | 3 | 80 h | developer-tools |
| [`e76101a8`](e76101a8-4917-55c2-8a8e-9a7485f31d2f/) | IPedrax/BIMCraft | Rust | hard | 2375 | 31 | 2 | 200 h | computer-aided-design |
| **total** | | | | **11882** | **99** | **7** | **400 h** | |

Every task is additionally scored on 8 compiled-rubric conditions and 9 judged criteria, for 24 and 27 across the set.

| Task | Keywords |
| --- | --- |
| [`5c9ba5b7-b29a-5361-b2ae-40c9b4e3f8e8`](5c9ba5b7-b29a-5361-b2ae-40c9b4e3f8e8/) | reverse-engineering, clean-room-reimplementation, rust, cli, compiler, diagrams, svg |
| [`a7e731ba-e0b9-5ad8-8479-fc9920f34235`](a7e731ba-e0b9-5ad8-8479-fc9920f34235/) | reverse-engineering, clean-room-reimplementation, rust, cli, formatter, yaml, markdown |
| [`e76101a8-4917-55c2-8a8e-9a7485f31d2f`](e76101a8-4917-55c2-8a8e-9a7485f31d2f/) | reverse-engineering, clean-room-reimplementation, rust, cli, bim, cad, ifc |

## Dataset structure

Each task is one Harbor task in a directory named by its content-derived uuid5, so the name doubles as an integrity check.

```
<uuid>/
├── task.toml         runner manifest
├── instruction.md    objective the agent reads
├── environment/      sandbox image and the compiled reference binary
├── tests/            verifier, hidden from the agent
├── solution/         reference solution
└── trials/
    └── opus-5.5/     claude-opus-5-5 at reasoning effort max
        ├── result.json, usage.json
        ├── agent/
        ├── artifacts/
        └── verifier/
```

## Reproduction

Each task directory is a complete Harbor task: `task.toml` is the runner manifest, `instruction.md` the objective, `environment/` the sandbox image carrying the compiled reference binary, `tests/` the verifier, and `solution/` the reference solution. The trials above were produced with:

```bash
harbor run -p <uuid> -a claude-code -m claude-opus-5-5
```

The verifier's LLM-judged rubric reads `OPENAI_API_KEY` and `OPENAI_BASE_URL` to reach `openai/gpt-6.1-sol`.

## Cite

```bibtex
@misc{godzilla2026,
  title        = {godzilla: Harbor-Format Terminal Tasks for Clean-Room Reimplementation},
  author       = {{Ethara.AI}},
  year         = {2026},
  howpublished = {\url{https://github.com/EtharaLabs/godzilla}},
  note         = {Each task is a containerized directive carrying its own environment, reference solution, and verifier. The agent rebuilds the program from documentation and a compiled reference binary alone.}
}
```

## License

Released under the MIT License. Each task keeps the license of any third-party input its environment carries.

## Contact

godzilla is built by [Ethara.AI](https://github.com/Ethara-Ai). For questions about the benchmark or dataset, contact [research@ethara.ai](mailto:research@ethara.ai).

Copyright (c) 2026 Green Rider Technology LLP (Ethara AI). All rights reserved.
