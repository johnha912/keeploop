# Post-hoc sensitivity run: keeploop with noise_runs 10

This is not the headline. It was run after the headline proof run (`../PROOF.md`) had
shown keeploop stuck on some seeds, to check one explanation: sigma measured from only
3 baseline runs is a noisy estimate. The same 25 seeds and 20 proposals were used, with
one change in keeploop mode only: `noise_runs: 10` instead of 3. Naive mode is unchanged.

    python tools/proof_run.py --keeploop-set noise_runs=10 --out docs/proof/posthoc-noise_runs-10

`proof.json` holds every number and `sweep.tsv` one row per seed and mode. The
`summary.keeploop` block is the one to compare with `../proof.json`.
