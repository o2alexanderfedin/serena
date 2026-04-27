//! clippy_collision fixture — body designed so a rust-analyzer assist
//! ("introduce named lifetime") and a clippy fix ("needless_lifetimes")
//! can both target the same span. The collision is exercised by the
//! invariant-1 atomicity test which asserts the merger rolls back when
//! one of the two edits is malformed.

pub fn first<'a>(slice: &'a [u8]) -> &'a u8 {
    &slice[0]
}
