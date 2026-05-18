# HubSpot Deal & Customer Journey — Sankey Dashboard

Streamlit dashboard that pulls live deals + contacts from HubSpot and renders
multi-view Sankey diagrams: the contact → deal → outcome funnel, attribution
splits by Contact Form / Ads / Demo Source, and per-pipeline stage flow.

## Setup

```bash
cd hubspot_sankey
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env, paste your HubSpot Private App token
```

**HubSpot Private App scopes required (3):**
- `crm.objects.deals.read` (also grants read access to deal pipelines/stages)
- `crm.objects.contacts.read`
- `crm.schemas.deals.read`

Create the token at: HubSpot → Settings → Integrations → Private Apps.

## Streamlit Cloud deployment

For cloud hosting (no Terminal needed by end users):

1. Push this folder to a GitHub repo.
2. At [share.streamlit.io](https://share.streamlit.io), sign in with GitHub.
3. Click **Create app** → pick the repo, branch `main`, main file `app.py`.
4. In **Advanced settings → Secrets**, paste:
   ```toml
   HUBSPOT_PRIVATE_APP_TOKEN = "pat-na1-..."
   ```
5. Click **Deploy**. You'll get a bookmarkable URL.

The app reads the token from `st.secrets` on Streamlit Cloud and falls back to `.env`/env vars locally — same code, both places.

## Run

```bash
streamlit run app.py
```

Open http://localhost:8501.

## What you'll see

| Tab | Sankey |
|---|---|
| Overview | All Deals → Pipeline → Outcome (Won/Lost/Open/Dormant) |
| Contact journey | Contacts → Has deal? → Best outcome (one row per contact) |
| Deal journey | Contacts → Deal created → Outcome (one row per deal) |
| By dimension | Deals Created → {Form / Ads / Demo Source} → Pipeline → Outcome |
| Pipeline stages | Per-pipeline stage-by-stage flow using actual `date entered stage` timestamps |
| Close rates | Win-rate table by dimension (by-create and by-close formulas) |

Every Sankey renders **twice**: by deal **count** and by deal **amount ($)**.
Each link is labeled `value (% of source)` so you can see the fraction of
each parent group that moves on.

## Date ranges

Sidebar offers presets `2025–2026 YTD` and `2026 YTD`, plus a custom date
range picker. Use the **🔄 Refresh from HubSpot** button to bypass the
10-minute API cache after a sync.

## Dimension property names

Internal property names in HubSpot may differ from the display labels. The
app tries to auto-resolve `contact_form_submission`, `attributable_to_ads`,
`demo_source` against your live property list. If a dimension column comes
back all `(blank)`, edit `DIMENSIONS` in `config.py` with the real internal
name (find it under HubSpot → Settings → Properties).

## Files

```
app.py             Streamlit UI + tabs
hubspot_client.py  Paginated REST client
transforms.py      Sankey link/node builders
sankey.py          Plotly renderer with count+% labels
kpis.py            Close-rate calculations
config.py          Pipeline stage order, outcome mapping, dimension names
```
