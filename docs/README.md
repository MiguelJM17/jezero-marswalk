# Documentation

| Path | What it is |
|---|---|
| `validation/` | The comparison against Perseverance's real drives: the script, its output, the per-route table and the figure. Run it with `MARSWALK_GRID=<grid> python3 docs/validation/baseline_check.py` |
| `README_photos_meda.md` | Which Perseverance photos and MEDA pressure files were used for each science stop, how they were chosen, and the credits |
| `BASE44_PROMPT.md` | The prompt used to generate the front-end code, kept for transparency about how AI tools were used |

The project's main documentation is the repository `README.md`. The model's
constants and their sources are in `routing/config.py`, and the generated outputs
describe their own fields in `outputs/README.md`.
