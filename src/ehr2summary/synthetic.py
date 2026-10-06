"""Synthetic MIMIC-III style tables for the offline demo and the tests.

The patients, admissions, prescriptions, results and notes are invented. The ICD-9 codes and titles
are public code descriptions. The folder gets a ``SYNTHETIC`` marker file, so records built from it
have ``synthetic=True``.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

DIAGNOSES = {
    "4280": ("CHF NOS", "Congestive heart failure, unspecified"),
    "42731": ("Atrial fibrillation", "Atrial fibrillation"),
    "4019": ("Hypertension NOS", "Unspecified essential hypertension"),
    "25000": ("DMII wo cmp nt st uncntr", "Diabetes mellitus without mention of complication, type II or unspecified type, not stated as uncontrolled"),
    "5849": ("Acute kidney failure NOS", "Acute kidney failure, unspecified"),
    "5990": ("Urin tract infection NOS", "Urinary tract infection, site not specified"),
    "486": ("Pneumonia, organism NOS", "Pneumonia, organism unspecified"),
    "0389": ("Septicemia NOS", "Unspecified septicemia"),
    "99592": ("Severe sepsis", "Severe sepsis"),
    "41401": ("Crnry athrscl natve vssl", "Coronary atherosclerosis of native coronary artery"),
    "2724": ("Hyperlipidemia NEC/NOS", "Other and unspecified hyperlipidemia"),
    "51881": ("Acute respiratry failure", "Acute respiratory failure"),
    "2762": ("Acidosis", "Acidosis"),
    "2859": ("Anemia NOS", "Anemia, unspecified"),
    "496": ("Chr airway obstruct NEC", "Chronic airway obstruction, not elsewhere classified"),
    "5859": ("Chronic kidney dis NOS", "Chronic kidney disease, unspecified"),
    "2449": ("Hypothyroidism NOS", "Unspecified acquired hypothyroidism"),
    "41071": ("Subendo infarct, initial", "Subendocardial infarction, initial episode of care"),
    "3051": ("Tobacco use disorder", "Tobacco use disorder"),
    "53081": ("Esophageal reflux", "Esophageal reflux"),
    "43491": ("Crbl art ocl NOS w infrc", "Cerebral artery occlusion, unspecified with cerebral infarction"),
    "5070": ("Food/vomit pneumonitis", "Pneumonitis due to inhalation of food or vomitus"),
}
PROCEDURES = {
    "9604": ("Insert endotracheal tube", "Insertion of endotracheal tube"),
    "9671": ("Cont inv mec ven <96 hrs", "Continuous invasive mechanical ventilation for less than 96 consecutive hours"),
    "3893": ("Venous cath NEC", "Venous catheterization, not elsewhere classified"),
    "9904": ("Packed cell transfusion", "Transfusion of packed cells"),
    "3615": ("1 int mam-cor art bypass", "Single internal mammary-coronary artery bypass"),
    "3961": ("Extracorporeal circulat", "Extracorporeal circulation auxiliary to open heart surgery"),
    "8856": ("Coronar arteriogr-2 cath", "Coronary arteriography using two catheters"),
    "3995": ("Hemodialysis", "Hemodialysis"),
    "9390": ("Non-invasive mech vent", "Non-invasive mechanical ventilation"),
}
DRUGS = ["Furosemide", "Metoprolol Tartrate", "Heparin", "Insulin", "Vancomycin", "Piperacillin-Tazobactam",
         "Aspirin", "Atorvastatin", "Lisinopril", "Warfarin", "Levothyroxine Sodium", "Pantoprazole",
         "Acetaminophen", "Potassium Chloride", "Albuterol", "Ceftriaxone", "Amiodarone", "Clopidogrel",
         "Docusate Sodium", "Metformin"]
LABS = {50912: ("Creatinine", "mg/dL", 3.1), 50971: ("Potassium", "mEq/L", 5.9), 50983: ("Sodium", "mEq/L", 128),
        51222: ("Hemoglobin", "g/dL", 7.4), 50931: ("Glucose", "mg/dL", 254), 51301: ("White Blood Cells", "K/uL", 18.2),
        50813: ("Lactate", "mmol/L", 4.1), 51006: ("Urea Nitrogen", "mg/dL", 61), 50882: ("Bicarbonate", "mEq/L", 16),
        51265: ("Platelet Count", "K/uL", 92)}

PROFILES = [
    {"name": "heart failure", "dx": ["4280", "42731"], "opt": ["4019", "25000", "5859", "2724"], "px": [],
     "meds": ["Furosemide", "Metoprolol Tartrate", "Warfarin", "Potassium Chloride"], "labs": [50912, 51006, 50983]},
    {"name": "sepsis", "dx": ["0389", "99592"], "opt": ["5990", "5849", "2762", "486"], "px": ["3893"],
     "meds": ["Vancomycin", "Piperacillin-Tazobactam", "Acetaminophen", "Heparin"], "labs": [51301, 50813, 50882]},
    {"name": "bypass surgery", "dx": ["41401", "41071"], "opt": ["4019", "2724", "3051", "25000"], "px": ["3615", "3961"],
     "meds": ["Aspirin", "Atorvastatin", "Metoprolol Tartrate", "Clopidogrel", "Docusate Sodium"], "labs": [51222, 50971]},
    {"name": "respiratory failure", "dx": ["51881", "486"], "opt": ["496", "5070", "3051"], "px": ["9604", "9671"],
     "meds": ["Ceftriaxone", "Albuterol", "Pantoprazole", "Heparin"], "labs": [50813, 51301]},
    {"name": "stroke", "dx": ["43491"], "opt": ["42731", "4019", "2724"], "px": [],
     "meds": ["Aspirin", "Atorvastatin", "Heparin"], "labs": [50931]},
    {"name": "kidney failure", "dx": ["5849"], "opt": ["5859", "25000", "2859", "2762"], "px": ["3995", "9904"],
     "meds": ["Insulin", "Pantoprazole", "Acetaminophen"], "labs": [50912, 50971, 51222, 50882]},
]
LOCATIONS = ["HOME", "HOME HEALTH CARE", "SNF", "REHAB/DISTINCT PART HOSP"]


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _note(rng: random.Random, profile: dict, dx: list[str], px: list[str], meds: list[str], location: str,
          los: float) -> str:
    """A reference note in a different style from the template generator (short titles, prose)."""
    lines = ["Discharge Diagnosis:"]
    lines += [f"- {DIAGNOSES[c][rng.choice([0, 1])]}" for c in dx]
    lines.append("")
    lines.append(f"Brief Hospital Course: Patient admitted with {profile['name']} and treated over {round(los)} days.")
    if px:
        lines.append("Underwent " + "; ".join(PROCEDURES[c][1].lower() for c in px) + ".")
    lines.append("Clinical status improved with treatment." if location != "DEAD/EXPIRED" else "Patient expired.")
    lines.append("")
    lines.append("Discharge Medications: " + ", ".join(m.lower() for m in meds) + ".")
    lines.append(f"Discharge Disposition: {location.title()}. Follow up with primary care in 1-2 weeks.")
    return "\n".join(lines)


def write_synthetic(out: Path, n_admissions: int = 40, seed: int = 7) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    adm, pat, dxr, pxr, rx, lab, notes = [], [], [], [], [], [], []
    lab_id = 1
    for i in range(n_admissions):
        subject, hadm = 10000 + i // 2 * 3 + (i % 2), 100000 + i * 7
        profile = PROFILES[i % len(PROFILES)]
        admit = datetime(2150, 1, 1) + timedelta(days=rng.randint(0, 3000), hours=rng.randint(0, 23))
        los = round(rng.uniform(1.5, 14.0), 2)
        disch = admit + timedelta(days=los)
        if i % 2 == 0 or subject not in {p[0] for p in pat}:
            dob = admit - timedelta(days=365.25 * rng.choice([34, 52, 61, 70, 77, 84, 300]))
            if subject not in {p[0] for p in pat}:
                pat.append([subject, rng.choice(["M", "F"]), dob.strftime("%Y-%m-%d 00:00:00")])
        died = i % 13 == 5
        location = "DEAD/EXPIRED" if died else rng.choice(LOCATIONS)
        adm.append([subject, hadm, admit.strftime("%Y-%m-%d %H:%M:%S"), disch.strftime("%Y-%m-%d %H:%M:%S"),
                    rng.choice(["EMERGENCY", "ELECTIVE", "URGENT"]), location, int(died)])
        dx = profile["dx"] + rng.sample(profile["opt"], k=rng.randint(1, len(profile["opt"])))
        if i == 3:
            dx.append("7999")  # a code with no dictionary entry
        for seq, code in enumerate(dx, start=1):
            dxr.append([subject, hadm, seq, code])
        px = list(profile["px"])
        for seq, code in enumerate(px, start=1):
            pxr.append([subject, hadm, seq, code])
        meds = profile["meds"] + rng.sample([d for d in DRUGS if d not in profile["meds"]], k=rng.randint(0, 2))
        for m in meds:
            for _ in range(rng.randint(1, 2)):
                rx.append([subject, hadm, (admit + timedelta(hours=rng.randint(1, 48))).strftime("%Y-%m-%d"), m,
                           rng.choice(["PO", "IV", "SC"])])
        for itemid in profile["labs"]:
            name, unit, value = LABS[itemid]
            for k in range(2):
                t = admit + timedelta(hours=6 + 12 * k)
                v = round(value * rng.uniform(0.9, 1.1), 1)
                lab.append([lab_id, subject, hadm, itemid, t.strftime("%Y-%m-%d %H:%M:%S"), v, unit, "abnormal"])
                lab_id += 1
            lab.append([lab_id, subject, hadm, 51265 if itemid != 51265 else 50983, admit.strftime("%Y-%m-%d %H:%M:%S"),
                        200, "K/uL", ""])
            lab_id += 1
        if i % 4 != 3:
            notes.append([subject, hadm, "Discharge summary", _note(rng, profile, [c for c in dx if c in DIAGNOSES], px,
                                                                    meds, location, los)])
    _write(out / "ADMISSIONS.csv", ["subject_id", "hadm_id", "admittime", "dischtime", "admission_type",
                                    "discharge_location", "hospital_expire_flag"], adm)
    _write(out / "PATIENTS.csv", ["subject_id", "gender", "dob"], pat)
    _write(out / "DIAGNOSES_ICD.csv", ["subject_id", "hadm_id", "seq_num", "icd9_code"], dxr)
    _write(out / "PROCEDURES_ICD.csv", ["subject_id", "hadm_id", "seq_num", "icd9_code"], pxr)
    _write(out / "D_ICD_DIAGNOSES.csv", ["icd9_code", "short_title", "long_title"],
           [[c, s, t] for c, (s, t) in DIAGNOSES.items()])
    _write(out / "D_ICD_PROCEDURES.csv", ["icd9_code", "short_title", "long_title"],
           [[c, s, t] for c, (s, t) in PROCEDURES.items()])
    _write(out / "PRESCRIPTIONS.csv", ["subject_id", "hadm_id", "startdate", "drug", "route"], rx)
    _write(out / "LABEVENTS.csv", ["row_id", "subject_id", "hadm_id", "itemid", "charttime", "valuenum", "valueuom",
                                   "flag"], lab)
    _write(out / "D_LABITEMS.csv", ["itemid", "label"], [[k, v[0]] for k, v in LABS.items()])
    _write(out / "NOTEEVENTS.csv", ["subject_id", "hadm_id", "category", "text"], notes)
    (out / "SYNTHETIC").write_text("Synthetic tables written by ehr2summary. Not patient data.\n", encoding="utf-8")
    return out
