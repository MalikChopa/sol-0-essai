# How Sol-0 works

[Français](how-it-works.fr.md) · [Journal](../journal/README.md) · [Atlas](../atlas/README.md) · [Firsts](../firsts/README.md)

Sol-0 is a simulated rover. It lives on a procedural planet, drives with a few very small neural networks, and learns on its own. A scheduled GitHub Action runs one "sol" four times a day, then publishes the images shown on the profile page.

## Everything shown is real

- The picture in the CAM-1 panel is exactly the input the rover's brain received, computed by the simulation engine.
- Every neuron, connection, wheel command, telemetry value, map cell, progress bar and journal line comes from the real state of the simulation and from the real networks. Nothing is decorative and no animation is scripted apart from the computation.
- The journal is not written by a language model. Each sentence is a template whose numbers, and whose every adjective or cause, are tied to a fact computed during the sol. If the fact is missing, the sentence is not written.
- Same inputs, same outputs: the random generator is integer-only and written for this project, so any sol can be replayed exactly.

## One sol

A sol is 1,200 time steps of 72 seconds, i.e. 24 simulated hours; it starts at 05:00 local time. In each sol the rover drives, records what it perceives, then learns from it. The planet is generated on demand from a seed: the terrain (rock, sand, dust, ice), the dunes, the sun and the seasons. Rare events can happen: dust storms, rare deposits, anomalies, comet impacts. Each one has a real effect on the simulation (storms reduce vision and solar power, for example).

## The brains

Small multilayer perceptrons written with numpy only, no deep-learning framework:

- **M0**, the driver: 24 inputs, 16 hidden neurons, 2 outputs (left and right wheel). Trained by evolution strategies: 48 perturbed copies are tried on simulated courses.
- **M1**, the predictor: from the wheel commands, tilt and slip, it predicts how far the rover will actually move. It is scored by an R² on sols that were not used to train it.
- **M2**, the visual encoder: it compresses the camera image into 8 numbers.
- **M3**, the energy manager: it chooses between driving, seeking the sun and sleeping.

The navigation target is a simple rule read on the map, not a learned plan: the direction, among 8, with the most unexplored cells.

## The stages

A stage is passed only when its criterion is reached and a minimum duration has elapsed. The thresholds below are initial values and can be recalibrated; the progress bar always shows the real value and the current threshold.

| Stage | Name | Criterion (initial value) |
|---|---|---|
| 0 | AWAKENING | 200 command-effect pairs recorded |
| 1 | I CAN MOVE | R² of the predictor at least 0.70 on 3 sols in a row |
| 2 | LEARNING TO DRIVE | at least 16 of 20 test courses reached |
| 3 | ENERGY | 20 sols in a row without breakdown, with at least 20 cells driven awake |
| 4 | SAMPLING | at least 10 samples with positive gain among the last 20 |
| 5 | ANALYSIS | 10 sols in a row with an ARI of at least 0.8 |

At the time of writing, the code only knows stages 0 to 3 (stages 4 and 5 are planned). A rover that reaches the last known stage keeps maintenance learning and writes in its journal that it is waiting for a software update.

## Safe mode

The rover is never in a terminal state. After a sol ended stuck in sand or tipped over, the safe mode frees or rights it; after a whole sol below the battery's breakdown threshold, it recharges it; after three sols in a row with fewer than 2 cells driven awake, it doubles the exploration noise for one sol. Each intervention is a computed fact and has its line in the journal: the machinery never acts silently.

## Pages

- [Journal](../journal/README.md): one entry per sol, in French and English.
- [Firsts](../firsts/README.md): founding moments, each with a Git tag.
- [Atlas](../atlas/README.md): substances and life forms, once the rover can analyse them.

Cost: nothing. Standard GitHub runners, a public repository, no paid API, no secret.
