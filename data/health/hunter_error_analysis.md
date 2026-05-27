# Hunter Error Analysis

## Shot Statistics

| Category | Count |
|----------|-------|
| Total shots | 18 |
| Shot wolf (good) | 14 |
| Shot good (bad) | 4 |
| No evidence random shot | 0 |
| Good restraint (didn't shoot) | 9 |

## Issues

- Hunter has only 18 shot opportunities across 56 games
- hunter_shot_quality: differentiated by target alignment + evidence
- hunter_restraint_quality: scored on vote/speech behavior
- Low sample count makes model training unreliable
- Recommendation: increase Hunter shot opportunities via game config or simulation
