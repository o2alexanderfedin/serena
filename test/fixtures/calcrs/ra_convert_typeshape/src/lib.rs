//! Family H type-shape conversions. Refactor targets for
//! `convert_named_struct_to_tuple_struct`,
//! `convert_tuple_struct_to_named_struct`,
//! `convert_match_to_iflet` (two-arm bool match candidate).
#![allow(dead_code)]

// Named struct — `convert_named_struct_to_tuple_struct` candidate.
pub struct Point {
    pub x: i64,
    pub y: i64,
}

// Tuple struct — `convert_tuple_struct_to_named_struct` candidate.
pub struct Pair(pub i64, pub i64);

// Two-arm bool match — `convert_match_to_iflet` candidate.
pub fn two_arm_bool_match(flag: bool) -> i64 {
    match flag {
        true => 1,
        false => 0,
    }
}

pub fn use_point(p: Point) -> i64 {
    p.x + p.y
}

pub fn use_pair(p: Pair) -> i64 {
    p.0 + p.1
}
