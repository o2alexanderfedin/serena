//! Family G method scaffolders. Refactor targets for `generate_new`,
//! `generate_getter`, `generate_setter`, `generate_function`.
#![allow(dead_code)]

// User struct with no constructor / no getters / no setters — fires
// `generate_new`, `generate_getter`, `generate_setter`.
pub struct User {
    id: u64,
    name: String,
}

// Forward-declaration so the not-yet-defined call site below compiles.
// Tests will remove the forward decl + body to re-arm `generate_function`.
pub fn not_yet_defined(_x: i64) -> i64 {
    0
}

// Call-site target — when the assist runs against the missing-fn version,
// `generate_function` will scaffold the receiver. With the forward decl
// in place we keep the workspace green.
pub fn call_site_for_generate_function() -> i64 {
    not_yet_defined(7)
}
