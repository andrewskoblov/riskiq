# Deployment

Live app: <https://andrewskoblovriskiq.streamlit.app/>

Repository: <https://github.com/andrewskoblov/riskiq>

Deployed on Streamlit Community Cloud from `main`, entry point `Home.py`.
Pushes to `main` redeploy automatically.

## Configuration

| Setting | Value |
| --- | --- |
| Branch | `main` |
| Main file path | `Home.py` |
| Secrets | none required |
| Environment variables | none required |

Streamlit discovers `pages/` automatically, so the four secondary pages appear
in the sidebar with no extra configuration. Both datasets ship in the
repository as Parquet, so nothing is fetched at runtime and there is no
database or API key to configure.

## Local development

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
source .venv/bin/activate   # macOS and Linux

pip install -r requirements.txt
streamlit run Home.py
```

Opens on `http://localhost:8501`.

## Verification

Every page is executed by Streamlit's `AppTest` harness against every data
source, which surfaces any exception the Python layer would raise:

```python
from streamlit.testing.v1 import AppTest

PAGES = ["Home.py", "pages/1_Risk_Explorer.py", "pages/2_Case_Investigation.py",
         "pages/3_Model_Insights.py", "pages/4_Model_Validation.py"]
SOURCES = ["Real (UCI Online Retail II)", "Real (UCI Credit Default)", "Synthetic"]

for source in SOURCES:
    for page in PAGES:
        at = AppTest.from_file(page, default_timeout=600)
        at.session_state["source"] = source
        at.run()
        assert not at.exception, f"{page} / {source}"
```

## Notes

- `pyarrow` is required to read the Parquet datasets. It is pinned below 25
  because Streamlit Cloud rejects 25.x for a known segfault and downgrades it
  on every boot.
- `use_container_width` was removed from Streamlit after 2025-12-31. This app
  uses `width="stretch"`.
- `.github/workflows/keep-awake.yml` runs daily, pings the app, and pushes an
  empty commit only once the repository has been quiet for five days. Streamlit
  Community Cloud sleeps an app after roughly seven days without traffic.
- Viewer access is controlled in the Streamlit Cloud dashboard, not in this
  repository. A public repository does not by itself make the app public.
