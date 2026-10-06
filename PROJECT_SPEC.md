# Mi Fitness Whooping — Project Specification

## Purpose

Build a trustworthy, local-first history and analytics system for Xiaomi/Mi Fitness health data. Its primary consumer is the owner of the health data; future CLI, UI and API clients should be able to present results without owning calculation rules.

## Core outcomes

- Ingest Xiaomi/Mi Fitness exports safely while preserving the source data and its provenance.
- Maintain a canonical health history that can be reconciled when source records change, disappear or conflict.
- Compute reproducible sleep, recovery, activity and vitals analytics from explicit inputs and versioned rules.
- Expose measurement quality, provenance, calculation status and freshness alongside results so consumers can distinguish a measured value, an estimate, insufficient data and stale history.
- Keep raw exports, personal health databases, populated profiles and generated personal reports outside Git.
- Allow presentation through future CLI, UI or API layers without coupling analytics to those layers.

## High-level data flow

Xiaomi/Mi Fitness source → safe ingestion → canonical history → dated inputs → analytics → versioned results → presentation.

Orchestration coordinates these steps. Storage preserves the canonical history and analytics lineage. Presentation consumes results and status; it does not define them.

## Global invariants and quality requirements

- Source health data is read without intentional mutation. Import failures must not silently publish partial history.
- A result is traceable to source signals, input coverage, algorithm/version and quality decisions.
- Given the same canonical inputs, profile and algorithm version, calculations should reproduce the same values and statuses. Time-dependent freshness is evaluated explicitly.
- Repeated processing of unchanged input should not duplicate active results. Historical corrections must be detectable and able to revise affected analytics.
- Missing, unverified or vendor-derived signals must not be presented as independently measured signals. In particular, ordinary heart-rate samples do not establish HRV.
- Privacy-sensitive source and derived data remain outside the repository; synthetic data supports automated tests.
- Significant features follow contract → implementation → verification → integration → audit. A migration initially preserves existing observable behavior unless a separately specified feature changes it.

## Global locked contract policy

The migration must treat existing source formats, deployed persistent schemas/locations, externally consumed CLI behavior and the explicitly locked contracts in feature specifications as unchanged until a separate compatibility decision authorizes a change. A proposed boundary is not itself an implemented interface. See `ARCHITECTURE.md` for current contracts and proposed dependency rules.

## Non-goals

- Medical diagnosis or clinical interpretation.
- Assuming that every field preserved from a vendor export is a supported analytics feature.
- Storing real personal data or production databases in Git.
- Choosing a final UI, API, deployment layout or all future formulas in this specification.

## Definition of project success

The system can safely rebuild or reconcile canonical history from supported exports, reproduce versioned analytics with provenance and quality status, recover from interrupted runs, and supply stable results to presentation clients. Acceptance is demonstrated by contract, regression, persistence and end-to-end tests using non-personal fixtures, plus an independent architecture audit.

This document states long-term product intent. `CURRENT_STATE.md` records what exists today; `ARCHITECTURE.md` distinguishes the current implementation from proposed boundaries; feature specifications own metric behavior.
