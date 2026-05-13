# Sugestatorium

Sugestatorium is a local-first review tool for AI-generated accessibility suggestions. It helps you import recurring CSV exports, bind each batch to a prompt version, review suggestions over time, and compare prompt quality across batches.

## Features

- Import CSV batches and bind each one to a prompt version
- Keep prompt versions as Markdown files with metadata and full prompt text
- Persist operational state in SQLite while keeping raw file artifacts on disk
- Re-open any imported batch and continue reviewing later
- Review rows inline with status, score, tags, actions, and comments
- Open a right-side drawer for full code, issue context, and re-review editing
- Review cross-batch items from the Insights area

## Local Run

Quick start:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 app.py
```

Requirements:

- Python 3.10+
- `pip`

Recommended setup with a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Run locally:

```bash
python3 app.py
```

Then open `http://localhost:5000`.

Custom port:

```bash
PORT=3001 python3 app.py
```

## Update Workflow

When you pull a newer version of the app:

```bash
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 app.py
```

## Clean Reset

This app stores local runtime data in `storage/`.

- If each person runs their own copy locally, each copy keeps its own prompts, imports, and review state.
- If you want a fresh local reset, remove the SQLite file and stored artifacts:

```bash
rm -f storage/*.sqlite3
rm -f storage/imports/*
rm -f storage/prompt_snapshots/*
```

- Prompt files in `prompts/` are not part of that reset.

## Minimal Install

If you do not want to use `venv`, the minimal install is:

```bash
python3 -m pip install -r requirements.txt
```

## Project Data

- Prompt files live in `prompts/`
- Imported app data is created automatically in `storage/`
- SQLite state lives in `storage/sugestatorium.sqlite3`
- CSV files can be uploaded directly or placed in the project root for quick import

## Shared Hosting

- `wsgi.py` and `passenger_wsgi.py` are included for Python hosting setups
- The app object is exposed as `application`
