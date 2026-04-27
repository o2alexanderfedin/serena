//! Family B: extractors. Every public item exists only as a refactor target.
//! `extract_function`, `extract_variable`, `extract_type_alias`,
//! `extract_struct_from_enum_variant`, `promote_local_to_const`,
//! `extract_constant`, `extract_module`, `extract_expression`.
#![allow(dead_code)]

pub fn extract_function_target(x: i64, y: i64) -> i64 {
    let sum = x + y;
    let scaled = sum * 2;
    let offset = scaled + 7;
    offset
}

pub fn extract_variable_target() -> i64 {
    (1 + 2) * (3 + 4)
}

pub fn extract_type_alias_target() -> Result<Vec<(String, i64)>, std::io::Error> {
    Ok(vec![("a".to_string(), 1)])
}

pub enum ExtractStructFromVariant {
    First,
    Pair { left: i64, right: i64 },
    Triple(i64, i64, i64),
}

pub fn promote_local_to_const_target() -> i64 {
    let pi_thousandths: i64 = 3142;
    pi_thousandths
}

pub fn extract_constant_target() -> i64 {
    42 * 1024
}

pub mod extract_module_target {
    pub fn alpha() -> i64 { 1 }
    pub fn beta() -> i64 { 2 }
    pub fn gamma() -> i64 { 3 }
}

pub fn extract_expression_target() -> i64 {
    let a = 1;
    let b = 2;
    a + b + a * b
}
