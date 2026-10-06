# Data for ehr2summary

The repository contains no patient data, no generated summaries and no ratings. The demo and the
tests use synthetic tables that `ehr2summary synth` or `ehr2summary demo` writes.

## 1. MIMIC-III Clinical Database Demo (development)

| Item | Value |
|---|---|
| Source | PhysioNet, MIMIC-III Clinical Database Demo v1.4 (100 de-identified patients) |
| URL | https://physionet.org/content/mimiciii-demo/1.4/ |
| Licence | Open Data Commons Open Database License v1.0 (ODbL). Cite the data set as PhysioNet asks |
| Download | `wget -r -N -c -np https://physionet.org/files/mimiciii-demo/1.4/` |

Put the CSV files in `data/mimic-iii-demo/` (or set `EHR2SUMMARY_DATA_DIR`). File names can be upper
case or lower case, and `.csv.gz` is also accepted.

| Table | Required? | Columns that ehr2summary reads |
|---|---|---|
| `ADMISSIONS` | Yes | `subject_id`, `hadm_id`, `admittime`, `dischtime`, `admission_type`, `discharge_location`, `hospital_expire_flag` (optional) |
| `PATIENTS` | Yes | `subject_id`, `gender`, `dob` |
| `DIAGNOSES_ICD` | Yes | `hadm_id`, `seq_num`, `icd9_code` |
| `D_ICD_DIAGNOSES` | Yes | `icd9_code`, `short_title`, `long_title` |
| `PROCEDURES_ICD` | Yes | `hadm_id`, `seq_num`, `icd9_code` |
| `D_ICD_PROCEDURES` | Yes | `icd9_code`, `short_title`, `long_title` |
| `PRESCRIPTIONS` | No | `hadm_id`, `drug`, `route`, `startdate` (optional) |
| `LABEVENTS` | No | `hadm_id`, `itemid`, `charttime`, `valuenum`, `valueuom`, `flag` |
| `D_LABITEMS` | No | `itemid`, `label` |
| `NOTEEVENTS` | No | `hadm_id`, `category`, `text`. Rows with category `Discharge summary` are the reference notes |

The demo release has no discharge notes, so ROUGE needs another source of reference notes.

## 2. Full MIMIC-III or MIMIC-IV (real evaluation)

The full releases and MIMIC-IV-Note need credentialed PhysioNet access and a data use agreement.
Keep these files and every output made from them on approved machines. ehr2summary refuses to send a
record that is not synthetic to a remote model endpoint unless `EHR2SUMMARY_ALLOW_REMOTE_RECORDS=true`.
Set it only if your agreement permits it.

## 3. Human ratings

`ehr2summary agreement` reads a CSV file with the columns `record_id`, `system`, `criterion` and
`rating` (0 to 10). `criterion` is one of `clinical_accuracy`, `completeness`, `readability` and
`actionability`. If more than one rater rates the same summary, the ratings are averaged.

## 4. Synthetic data

`ehr2summary synth --out data/synthetic` writes the ten tables above for 40 invented admissions in six
clinical profiles, plus a `SYNTHETIC` marker file. The ICD-9 codes and titles are public code
descriptions. Everything else is invented. Records from this folder have `synthetic=true`.
