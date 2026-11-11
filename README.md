# RAG-TEND

**End-to-end data pipeline that turns unstructured Spanish public-tender documents into a queryable, structured database, using web scraping, a vector store and LLM-based extraction.**

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.0-092E20?logo=django&logoColor=white)
![SQL Server](https://img.shields.io/badge/SQL%20Server-CC2927?logo=microsoftsqlserver&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-vector%20store-FF6F00)
![Playwright](https://img.shields.io/badge/Playwright-scraping-2EAD33?logo=playwright&logoColor=white)
![Llama 3.3](https://img.shields.io/badge/LLM-Llama%203.3%2070B-0467DF?logo=meta&logoColor=white)

> Bachelor's thesis, Computer Engineering, Universitat Politècnica de València (2025).

![Tender dashboard](docs/thesis/images/VentanaPrincipal.png)

## The problem

Public tenders in Spain are published on the [Plataforma de Contratación del Sector Público](https://contrataciondelestado.es). The useful information (budget, execution period, award criteria, pricing formulas, guarantees...) is buried in long PDF, DOCX and ODT annexes. Each contracting body writes them with its own layout and vocabulary. Companies that bid on tenders spend hours reading them by hand.

## What RAG-TEND does

RAG-TEND automates the full path from source documents to analytics:

1. **Ingests** tender metadata and attached documents from the official platform (Valencia region) with a Playwright scraper.
2. **Parses and chunks** heterogeneous documents into section-aware JSON.
3. **Indexes** the chunks as embeddings in ChromaDB.
4. **Extracts 47 structured fields** per tender with a retrieval-augmented LLM, keeping a source reference for every extracted value.
5. **Loads** the results into SQL Server and serves them through a Django dashboard with filters, statistics, Excel export and per-user email alerts.

## Architecture

```mermaid
flowchart LR
    subgraph Ingestion
        A[contrataciondelestado.es] -->|Playwright scraper| B[(SQL Server<br/>Licitaciones / Documentos)]
    end
    subgraph Transformation
        B --> C[Document parser<br/>pdfplumber · python-docx · odfpy]
        C --> D[Section-aware recursive chunking<br/>800 chars · 400 overlap]
        D --> E[Embeddings<br/>nomic-embed-text]
        E --> F[(ChromaDB)]
    end
    subgraph Extraction
        F --> G[Hybrid retrieval<br/>semantic + keyword]
        G --> H[BM25 re-ranking]
        H --> I[LLM extraction<br/>Llama 3.3 70B · Pydantic]
        I --> J[(SQL Server<br/>AnexoI + AnexoI_Fuentes)]
    end
    subgraph Serving
        J --> K[Django dashboard<br/>filters · stats · Excel export]
        J --> L[Scheduled job<br/>email alerts]
    end
```

| Stage | What happens | Key tools |
|-------|--------------|-----------|
| Ingestion | Navigates the platform, filters by region, stores tender metadata and document URLs. Retries on timeouts. | Playwright (async), pyodbc |
| Parsing | Downloads each annex and normalises PDF/DOCX/ODT to text. Detects document sections and keeps tables readable. | pdfplumber, python-docx, odfpy |
| Chunking | Splits each detected section recursively (800 chars, 400 overlap) and carries the section context into its chunks. | LangChain text splitters |
| Indexing | Embeds every chunk into a cosine-distance collection, rebuilt for each document. | nomic-embed-text, ChromaDB |
| Retrieval | Semantic search plus keyword matching (per-field keyword lists in `Strings.json`), re-ranked with BM25. | rank-bm25, spaCy (lemmatisation) |
| Extraction | One prompt per field. Each answer is captured as a typed record together with the chunks it came from (traceability). | OpenAI-compatible API, Pydantic |
| Serving | Dashboard, statistics, saved tenders and alert rules that email users when a new tender matches. | Django, SMTP |

## Results

Evaluated on a **random sample of 30 tenders** with [Ragas](https://docs.ragas.io/) metrics. The LLM judge was first validated against **282 manually reviewed fields**.

| Metric | Score |
|--------|-------|
| Context Precision | **0.79** |
| Response Relevancy | **0.79** |
| Faithfulness | **0.76** |

- About **70% of all scores are ≥ 0.75**. Weak spots are concentrated in fields that rarely appear in the documents, or that depend on keyword lists (environmental and social criteria, pricing formulas). The thesis analyses each one.
- **Embedding fine-tuning experiment:** I trained a linear adapter on top of `all-MiniLM-L6-v2` with a synthetic question corpus. It raised Hit Rate@10 to **66.7% (+7.8%)** and MRR by **+6.2%**, but it made query encoding **about 3x slower**. That trade-off is documented in the thesis.
- **Throughput:** one annex produces 190-250 chunks and takes about 10-15 minutes end to end (embeddings plus 47 prompts). That is why tenders are pre-processed on ingestion rather than on demand.

## Data model

The full schema is in [`database/schema.sql`](database/schema.sql). The core tables:

| Table | Grain | Content |
|-------|-------|---------|
| `Licitaciones` | one row per tender | Scraped metadata: contracting body, status, budget, CPV code, procedure, award result |
| `Documentos` | one row per tender | URLs of the attached documents |
| `AnexoI` | one row per tender | The 47 LLM-extracted fields |
| `AnexoI_Fuentes` | one row per tender | Source chunks behind each extracted field (auditability) |
| `alertas` | one row per alert rule | User-defined filters (JSON) for email notifications |
| `anexos_guardados` | one row per saved tender | Tenders each user saved |

## Screenshots

| Tender details | Statistics |
|---|---|
| ![Details](docs/thesis/images/detalles.png) | ![Statistics](docs/thesis/estadisticas.png) |
| **Alert rules** | **Saved tenders** |
| ![Alerts](docs/thesis/images/alertas_ventana.png) | ![Saved](docs/thesis/images/guardadas.png) |

## Repository structure

```
.
├── project/                 Django project
│   ├── app/
│   │   ├── util/            Pipeline: scraper, document handler, RAG, DB manager, mailer
│   │   │   ├── JSON/        Prompts, field keywords and ground-truth annotations
│   │   │   ├── testing/     Evaluation: Ragas, LLM judge, linear adapter, corpus generator
│   │   │   └── results/     Evaluation outputs
│   │   ├── templates/       Dashboard views
│   │   ├── periodic.py      Scheduled scraping, extraction and alerts
│   │   └── views.py
│   └── manage.py
├── database/schema.sql      SQL Server schema
└── docs/thesis/             Full thesis (Spanish): LaTeX source, Markdown and figures
```

## Running it locally

**Prerequisites:** Python 3.13, SQL Server with [ODBC Driver 17](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server), and an API key for an OpenAI-compatible LLM endpoint. The project used UPV's PoliGPT; to use another endpoint, change `base_url` and the model names in `project/app/util/rag_operations.py`.

```bash
git clone https://github.com/Oppen-OC/TFG.git && cd TFG
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python -m spacy download es_core_news_md
python -m spacy download es_core_news_lg

cp .env.example .env                               # then fill in the values
# Create the database: run database/schema.sql in SQL Server (SSMS or sqlcmd)

python project/manage.py createsuperuser
python project/manage.py runserver
```

Open http://localhost:8000. The scheduled job starts with the server and fills the database.

**Tests** (no SQL Server needed):

```bash
DB_ENGINE=sqlite DISABLE_PERIODIC=1 python project/manage.py test app
```

## Limitations and future work

- Scanned PDFs are not supported. The next step would be adding OCR.
- Some fields depend on handcrafted keyword lists, which do not generalise well across contracting bodies.
- Processing time per document is driven by remote embedding and LLM latency.
- Only the Valencia region is scraped. Extending to other regions mostly means parameterising the scraper's filters.

## Thesis

The full write-up (in Spanish) covers the state of the art, the requirements analysis, the design decisions (chunking strategies, vector DB comparison, re-ranking), the evaluation and a legal and ethical analysis of web scraping and LLM use under Spanish and EU law. See [`docs/thesis/`](docs/thesis/).

---

Author: [@Oppen-OC](https://github.com/Oppen-OC)
