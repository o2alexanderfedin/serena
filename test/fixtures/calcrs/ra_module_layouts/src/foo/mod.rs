//! `mod.rs` form — half of the layout-swap target pair.
#![allow(dead_code)]

pub mod bar;

pub fn foo_value() -> i64 {
    bar::bar_value() + 1
}
