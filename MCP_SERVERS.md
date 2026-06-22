# Connected MCP Servers

This document lists the MCP (Model Context Protocol) integrations connected to the Gumloop agent at export time, along with the tools each server exposes.

## apollo
B2B data enrichment & prospecting.
- `enrich_organization` — Enrich data for a company (Organization Enrichment API).
- `enrich_person` — Enrich data for a person (People Enrichment API).
- `find_people` — Find people in Apollo's database (search is free; use enrich=true for full data).
- `get_organization_job_postings` — Retrieve current job postings for an organization.
- `organization_search` — Search for organizations in Apollo's database.

## brandfetch
Brand & company asset lookup.
- `enrich_transaction` — Identify a brand from a raw payment transaction label.
- `get_brand` — Get brand data (logos, colors, fonts, company info, social links) by domain, brand ID, ISIN, ticker, or crypto symbol.
- `search_brands` — Search brands by name; returns domain, icon, and brand ID.

## github
Code repository & project management.
- Repositories: `create_repository`, `list_repositories`, `get_contents`, `create_branch`, `list_branches`, `list_releases`, `list_deployments`, `list_collaborators`, `add_collaborator`, `list_stargazers`.
- Files: `create_or_update_file`.
- Issues & PRs: `create_issue`, `create_label`, `get_milestone`, `create_pull_request`, `update_pull_request`.
- User: `get_user_id`, `get_user_status`, `set_user_status`.

## gpagespeed (Google PageSpeed)
Web performance analysis.
- `get_core_web_vitals` — Core Web Vitals (LCP, FID, CLS, INP, TTFB) field data for a URL.
- `get_lighthouse_audits` — Lighthouse audit results for a category on a URL.
- `run_pagespeed_analysis` — Run PageSpeed analysis; returns Lighthouse scores and loading experience.

## reducto
Document parsing, extraction & editing.
- `upload_document` — Upload a file to Reducto; returns a reducto:// URL.
- `parse_document` — Parse a document into structured content (text, tables, figures).
- `extract_data` — Extract structured JSON from a document using a schema.
- `edit_document` — Fill forms or modify a document via natural-language instructions.
- `split_document` — Split a document into logical sections.
- `download_document` — Download a Reducto result file into Gumloop storage.
- Jobs: `get_job_status`, `list_jobs`, `cancel_job`.

---
_Exported automatically from the Gumloop agent._
