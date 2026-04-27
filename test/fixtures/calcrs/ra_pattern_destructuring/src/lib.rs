//! Family I: pattern + destructuring assists. Refactor targets for
//! `add_missing_match_arms`, `add_missing_impl_members`,
//! `destructure_tuple_binding` / `destructure_struct_binding`.
#![allow(dead_code)]

// Enum + non-exhaustive match — `add_missing_match_arms` candidate when
// wildcard arm is removed.
pub enum Shape {
    Circle,
    Square,
    Triangle,
}

pub fn classify(shape: &Shape) -> &'static str {
    match shape {
        Shape::Circle => "round",
        // Tests will remove the wildcard to fire add_missing_match_arms.
        _ => "polygon",
    }
}

// Trait with 3 unimplemented members — `add_missing_impl_members` candidate.
pub trait Greeter {
    fn hello(&self) -> String;
    fn goodbye(&self) -> String;
    fn name(&self) -> String;
}

// Tuple struct + binding — `destructure_tuple_binding` candidate.
pub struct Pair(pub i64, pub i64);

pub fn make_pair() -> Pair {
    Pair(1, 2)
}

pub fn use_pair_binding() -> i64 {
    let pair = make_pair();
    pair.0 + pair.1
}

// Named struct + binding — `destructure_struct_binding` candidate.
pub struct NamedPair {
    pub left: i64,
    pub right: i64,
}

pub fn use_named_pair_binding() -> i64 {
    let pair = NamedPair { left: 1, right: 2 };
    pair.left + pair.right
}
