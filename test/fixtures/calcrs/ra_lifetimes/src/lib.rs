//! Family J: lifetime assists. Refactor targets for `introduce_named_lifetime`,
//! `add_explicit_lifetime`, and reduce-static-to-named-lifetime.
#![allow(dead_code)]

pub struct Foo {
    s: String,
}

// Method with elided lifetimes — `introduce_named_lifetime` candidate.
impl Foo {
    pub fn name(&self) -> &str {
        &self.s
    }
}

// Cross-borrow candidate — fn returning a borrow tied to one of two inputs;
// `add_explicit_lifetime` will explicate which input the output borrows from.
pub fn cross_borrow<'a>(a: &'a str, _b: &str) -> &'a str {
    a
}

// `'static` reference reduceable to a named lifetime — when this becomes a
// method on a struct holding the str, the assist replaces 'static.
pub struct Holds {
    pub label: &'static str,
}

impl Holds {
    pub fn label(&self) -> &'static str {
        self.label
    }
}

pub fn elided_input_output(s: &str) -> &str {
    s
}
