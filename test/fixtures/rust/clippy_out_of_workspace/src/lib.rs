//! clippy_out_of_workspace fixture — drives invariant-3 (path filter).
//!
//! The fixture itself is a normal in-workspace crate; the *driver* for
//! the test is `.scalpel-target` at the fixture root, whose contents
//! are the deterministic out-of-workspace path the path filter must
//! reject. Keeping the rejected path inside a fixture file (not as a
//! literal in the test body) makes the fixture's purpose explicit for
//! future readers and avoids a programmatic `/etc/passwd` literal in
//! Python source.

pub fn placeholder() {}
