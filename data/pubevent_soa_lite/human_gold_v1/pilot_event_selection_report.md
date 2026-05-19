# Pilot Event Selection Report

- version: pilot_events_v1
- created_at: 2026-05-16T07:33:16.885749+00:00

## Selected Events

| category | event_id | reason | gold_prompt_coverage | tuples | chains | probe_f1 | probe_error |
|---|---:|---|---:|---:|---:|---:|---|
| high_coverage | E015 | highest gold evidence prompt coverage (1.0000) | 1.0000 | 3 | 3 |  |  |
| low_coverage | E049 | lowest gold evidence prompt coverage (0.1250) | 0.1250 | 5 | 2 |  |  |
| many_tuples | E020 | largest silver tuple count (5) | 0.5385 | 5 | 3 |  |  |
| many_chains | E050 | largest chain count (3) | 1.0000 | 3 | 3 |  |  |
| model_probe_poor | E002 | model probe poor performance: F1=0.0000, zero_pred=1 | 0.7143 | 3 | 3 | 0.0000 | zero_prediction |
