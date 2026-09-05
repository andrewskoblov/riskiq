# Deploying RiskIQ

## Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **New app**.
3. Select this repository, branch `main`.
4. Set **Main file path** to `Home.py`.
5. Click **Deploy**.

The first build installs everything in `requirements.txt` and takes a couple of
minutes. Streamlit discovers the `pages/` directory automatically, so the three
secondary pages appear in the sidebar with no extra configuration.

## Repository layout requirements

Streamlit Cloud expects the app at the repository root:

```
Home.py               <- main file path
pages/                <- auto discovered, ordered by filename prefix
.streamlit/config.toml
requirements.txt
```

If `Home.py` sits inside a subfolder, either set the main file path to include
that folder or move the contents up to the root.

## Local development

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
source .venv/bin/activate   # macOS and Linux

pip install -r requirements.txt
streamlit run Home.py
```

The app opens on `http://localhost:8501`.

## Verification

The Python layer is covered by Streamlit's own `AppTest` harness, which
executes each page and surfaces any exception:

```python
from streamlit.testing.v1 import AppTest

for page in ["Home.py", "pages/1_Risk_Explorer.py",
             "pages/2_Case_Investigation.py", "pages/3_Model_Insights.py"]:
    at = AppTest.from_file(page, default_timeout=120)
    at.run()
    assert not at.exception, page
```

## Notes

- `use_container_width` was removed from Streamlit after 2025-12-31. This app
  uses `width="stretch"` instead, which is the supported replacement.
- No secrets or environment variables are required. All data is synthetic and
  generated at runtime, so there is no database or API key to configure.
