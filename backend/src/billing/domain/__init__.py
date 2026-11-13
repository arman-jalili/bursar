"""Billing domain — framework-free, persistence-ignorant.

Canonical: .pi/architecture/modules/billing.md#components
Reference: docs/contracts/billing-contract-freeze.md

Service-depth context (ADR-008): the five captured types below are the whole model. There are no domain
services, no extra aggregates and no extra events — Billing is bookkeeping over documents, and the
interesting decisions belong to Authority.

Every function body raises `NotImplementedError("B-n — see module doc")` until Phase B. The suffix is
the invariant the body must satisfy, not a decoration: it is what the failing tests point at.
"""
