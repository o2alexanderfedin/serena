//! Family A: module-layout swap targets for `convert_module_layout`.
//! `foo` uses the `mod.rs` form (foo/mod.rs + foo/bar.rs); `baz` uses the
//! file form (baz.rs). Both layouts coexist intentionally so the assist
//! has a target either direction.
#![allow(dead_code)]

pub mod foo;
pub mod baz;

pub fn root_user() -> i64 {
    foo::bar::bar_value() + baz::baz_value()
}
