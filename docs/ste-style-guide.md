# The writing standard: ASD-STE100 Simplified Technical English

Use these rules for the `README.md` of ehr2summary and for this file. Section 3 gives the project
vocabulary. Each term in Section 3 has one meaning in all of the documentation.

## 1. The writing rules

### Words

1. Use one word for one meaning, and one meaning for one word. Do not use synonyms for variety.
2. Use a word only as one part of speech. For example, `test` is a noun or a verb, `check` is a verb.
3. Do not use phrasal verbs (`set up`, `carry out`, `find out`, `pick up`, `look up`, `come up with`).
   Use one verb: `prepare`, `do`, `find`, `get`, `make`.
4. Do not use an `-ing` form as a noun or an adjective (`the running job`, `after indexing`).
   Exception: a technical name, a file name, a command or a status value.
5. Do not use contractions (`don't`, `it's`, `can't`). Do not use slang or idioms
   (`out of the box`, `under the hood`, `at a glance`, `gotcha`, `bells and whistles`).
6. Do not use `and/or`. Write `A, B or both`.
7. Do not use `should`, `could`, `would` or `may` for instructions. Use `must` for a rule, the
   imperative for a step and `can` for a possibility.
8. Keep the articles `a`, `an` and `the` in sentences.
9. Do not make a noun cluster of more than three words. A technical name is one word.

### Sentences

1. A procedural sentence (an instruction) has a maximum of **20 words**.
2. A descriptive sentence has a maximum of **25 words**.
3. Write one instruction in one sentence.
4. Use the imperative for an instruction: `Run the tests.` Not `The tests should be run.`
5. Use the active voice. Use the passive voice only when the agent of the action is not important.
6. Use only the simple present, the simple past and the simple future.
7. Put a condition before the instruction: `If the index is stale, build it again.`
8. Do not use semicolons in sentences. Write two sentences.

### Paragraphs, notes and warnings

1. A paragraph has one topic and a maximum of **6 sentences**. Start with the topic sentence.
2. A warning or a caution starts with a clear command. Then it gives the reason.
3. A note gives information. It does not give an instruction.
4. Use a vertical list for a sequence or a set of conditions. Each item of a numbered procedure is one step.

### Tables, headings and diagrams

1. A table cell can be a short phrase. If a cell has a sentence, the sentence obeys the rules.
2. A heading is a noun phrase (`The cost model`) or an imperative (`Run the demo`).
   Do not start a heading with an `-ing` form.
3. A diagram label is a short phrase. Use the same terms as the text.

### What STE does not change

Code, commands, file names, paths, field names, environment variables, status values, enum values,
product names and URLs stay exactly as they are. They are technical names. Put them in backticks.

## 2. General words to replace

| Do not use | Use |
|---|---|
| utilize, leverage | use |
| in order to | to |
| set up | prepare, install, configure |
| carry out, perform | do |
| make sure, ensure | make sure (allowed), or `check that` |
| a lot of, lots of | many, much |
| e.g., i.e. | for example, that is |
| should (instruction) | must (rule) / imperative (step) |
| might, may (possibility) | can |
| very, really, just, simply, easily | (delete) |
| seamless, robust, powerful, blazing | (delete or give a measured fact) |

## 3. Project vocabulary

These terms have one meaning in the ehr2summary documentation. The code names are in backticks.

### 3.1 Technical names (nouns)

| Term | Meaning | Do not use |
|---|---|---|
| **admission** | One hospital stay, with one `hadm_id` in the source tables. | visit, encounter, case |
| **table** | One MIMIC-III style CSV file, for example `DIAGNOSES_ICD`. | sheet, dataset (for one file) |
| **dictionary** | The tables `D_ICD_DIAGNOSES` and `D_ICD_PROCEDURES` that give each ICD-9 code its title. | lookup, mapping table |
| **record** | The structured, de-identified JSON of one admission that the record builder makes. | patient record (in prose), EHR, input |
| **item** | One diagnosis, procedure, medication or lab result in a record, with a reference id. | entry, element, fact |
| **reference id** | The id of an item: `dx1`, `px2`, `med3`, `lab1`. | ref (in prose), key, pointer |
| **record id** | The pseudonymous id of a record: `r-` and 12 hexadecimal characters from a salted SHA-256 value. | patient id, admission id |
| **system** | A generator under evaluation: `template`, `template+hallucination`, `template+omission` or `llm:<model>`. | model (for a system), approach |
| **generator** | The component that writes a summary from a record. | writer, summarizer |
| **summary** | The generated discharge summary: five sections of statements. | output, note (for generated text) |
| **section** | One of `diagnoses`, `procedures`, `hospital_course`, `medications`, `follow_up`. | part, heading |
| **statement** | One sentence of a summary with the reference ids that support it. | claim, line |
| **reference note** | A discharge note from `NOTEEVENTS` that ROUGE compares with the summary. | gold summary, ground truth |
| **lexicon** | All diagnosis titles, procedure titles and drug names of the tables. | vocabulary, term list |
| **mention** | A lexicon term that the faithfulness check finds in a statement. | entity (alone), hit |
| **unsupported term** | A mention that is not an item of the record. | hallucination (as a count), error |
| **hallucination rate** | The share of summaries with at least one unsupported term, invalid reference id or unknown code. | error rate |
| **entity precision** | Supported mentions divided by all mentions in one summary. | accuracy, faithfulness score |
| **entity recall** | Covered diagnoses, procedures and medications divided by all of them in the record. | coverage score, completeness (for this metric) |
| **judge** | The component that scores a summary against its record on four criteria from 0 to 10. | grader, evaluator, critic |
| **rule judge** | The offline judge from the faithfulness check and text statistics. | fake judge, heuristic (alone) |
| **criterion** | One of `clinical_accuracy`, `completeness`, `readability`, `actionability`. | metric (for a criterion), dimension |
| **sample** | One judge call. The judge averages several samples. | run, trial |
| **chat model** | An OpenAI-compatible endpoint or a local Hugging Face model behind the `ChatModel` interface. | LLM (in prose), engine |
| **injector** | A generator that adds known errors to the summaries of another generator. | corrupter, perturbation |
| **rating** | One human score for one summary and one criterion. | label, annotation |

### 3.2 Technical verbs

| Verb | Meaning |
|---|---|
| **build** | Make a record from the tables of one admission. |
| **select** | Choose a seeded sample of admissions. |
| **generate** | Write a summary from a record. |
| **check** | Run the faithfulness check on a summary. |
| **score** | Get judge scores for a summary. |
| **inject** | Add known errors to a summary. |
| **aggregate** | Calculate means and bootstrap intervals for each system. |
