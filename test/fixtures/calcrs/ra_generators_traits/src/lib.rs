//! Family G trait scaffolders. Refactor targets for `generate_default_impl`,
//! `generate_from_impl`, `generate_default_from_new`.
#![allow(dead_code)]

// Bare struct, no Default / no From — `generate_default_impl` and
// `generate_from_impl` candidate.
pub struct Token {
    pub kind: i64,
    pub text: String,
}

// Enum with no From — `generate_from_impl` candidate.
pub enum Color {
    Red,
    Green,
    Blue,
}

// Struct with `new()` constructor but no Default — `generate_default_from_new`
// candidate (the assist synthesizes Default::default delegating to new()).
pub struct Builder {
    name: String,
}

impl Builder {
    pub fn new() -> Self {
        Builder {
            name: String::new(),
        }
    }

    pub fn with_name(mut self, name: String) -> Self {
        self.name = name;
        self
    }
}
