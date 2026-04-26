//! `calcrs-core` — minimum companion crate for Stage 1H smoke fixtures.
//!
//! This crate gives rust-analyzer enough surface to offer extract,
//! inline, rename, and visibility-change code actions.  The full Stage
//! 1H plan budgets 18 RA companion crates; the v0.1.0 minimum scope
//! ships only this one.  See
//! `docs/superpowers/plans/stage-1h-results/PROGRESS.md` for the
//! deferred crates routed to v0.2.0.

#![allow(dead_code)]

pub mod ast;
pub mod errors;
pub mod eval;

pub use ast::Expr;
pub use errors::CalcError;
pub use eval::evaluate;
