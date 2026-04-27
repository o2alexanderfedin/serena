//! Auxiliary fixture module for Stage 3 long-tail Rust scenarios (E16).
//!
//! Hosts a sealed `Op` enum with a wildcard match that rust-analyzer's
//! `quickfix.add_missing_match_arms` assist can expand into explicit
//! arms. Kept out of the four E1-split clusters (`ast`, `errors`,
//! `parser`, `eval`) so it does not interfere with the existing
//! split / semantic-equivalence baselines.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Op {
    Plus,
    Minus,
    Times,
}

/// Classify an `Op` via a non-exhaustive match (uses `_` placeholder so
/// the source compiles today). E16 invokes `complete_match_arms` on this
/// match expression to expand the placeholder into one arm per variant.
pub fn classify(op: Op) -> &'static str {
    match op {
        Op::Plus => "additive",
        _ => "other",
    }
}
