# Development Data Lab — eCourts (district courts, 2010–2018)

Used by `ml/train_delay_model.py`. Licence: CC BY-NC-SA 4.0 — non-commercial use only,
attribution required, share-alike. Do not commit the data to this repository.

1. Download the "Judicial Data" case files (cases_YYYY.csv) and the key files
   (acts/sections, courts, districts) from the Development Data Lab website.
2. Place them in `data/external/ddl/` (gitignored).
3. Run `python ml/train_delay_model.py --ddl data/external/ddl`.

Without the files, the training script falls back to a synthetic dataset with the same
schema so the pipeline and tests run end-to-end; the resulting model is for demonstration
only and is labelled as such.
