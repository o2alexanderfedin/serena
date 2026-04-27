//! clippy_a fixture — single deliberate clippy lint for the v1.1
//! Rust+clippy multi-server invariant suite.
//!
//! The body of `seeded_lint` returns `Vec::<u8>::new()` so clippy's
//! `useless_vec` lint surfaces a `suggested_replacement` we can project
//! into a `WorkspaceEdit`.

pub fn seeded_lint() -> usize {
    let v: Vec<u8> = vec![1, 2, 3];
    v.len()
}
