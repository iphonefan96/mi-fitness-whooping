# Mi Fitness Whooping — Project Specification

## Purpose

Build a trustworthy, local-first history and analytics system for Xiaomi/Mi Fitness health data. Its primary consumer is the owner of the health data; future CLI, UI and API clients should be able to present results without owning calculation rules.

## Current delivery target (2026-10-07)

Deliver a usable WHOOP-like **baseline from the existing Mi Fitness export and the calculations already present in Legacy**. Show sleep and Recovery plus the heart-rate/RHR, SpO2, respiratory, stress and activity outputs that the current code and source data actually support. Identify missing, reduced-quality and stale results. SpO2 is blood oxygen saturation, not a blood test; Xiaomi data does not provide measured HRV. Do not add new formulas, device integrations or a new UI to reach this baseline.

Keep the installed ingestion and analytics working while adapting useful Legacy behavior into the target package. The target Sleep Core and reader now serve the local target `run`; installed scheduling has not switched. The active plan defines the remaining integration. Optional improvements go to `BACKLOG.md`.

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
- Significant behavior changes preserve explicit contracts and receive proportional verification. A migration initially preserves existing observable behavior unless a separately specified feature changes it. A separate audit is needed before production activation or after substantial integration, not after each small implementation step.

## Global locked contract policy

The migration must treat existing source formats, deployed persistent schemas/locations, externally consumed CLI behavior and the explicitly locked contracts in feature specifications as unchanged until a separate compatibility decision authorizes a change. A proposed boundary is not itself an implemented interface. See `ARCHITECTURE.md` for current contracts and proposed dependency rules.

## Non-goals

- Medical diagnosis or clinical interpretation.
- Assuming that every field preserved from a vendor export is a supported analytics feature.
- Storing real personal data or production databases in Git.
- Choosing a final UI, API, deployment layout or all future formulas in this specification.

## Definition of project success

For the current baseline, supported existing data reaches usable date/history analytics for sleep, Recovery and the available vitals/activity outputs, with honest quality and freshness information. Relevant synthetic, compatibility and end-to-end checks pass before a production switch. The broader reconciliation, historical completeness and future-client goals above remain long-term goals rather than prerequisites for each baseline task.

This document states long-term product intent. `CURRENT_STATE.md` records what exists today; `ARCHITECTURE.md` distinguishes the current implementation from proposed boundaries; feature specifications own metric behavior.
