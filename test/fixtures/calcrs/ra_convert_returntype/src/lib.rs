//! Family H return-type conversions. Refactor targets for
//! `wrap_return_type_in_result`, `wrap_return_type_in_option`,
//! `unwrap_result_return_type`, `unwrap_option_return_type`.
#![allow(dead_code)]

// Plain `i64` to wrap in Result — `wrap_return_type_in_result` candidate.
pub fn returns_plain_i64() -> i64 {
    7
}

// `Result<i64, std::io::Error>` to unwrap — `unwrap_result_return_type`
// candidate.
pub fn returns_result_i64() -> Result<i64, std::io::Error> {
    Ok(7)
}

// `Option<i64>` to unwrap — `unwrap_option_return_type` candidate.
pub fn returns_option_i64() -> Option<i64> {
    Some(7)
}

// Plain `String` to wrap in Option — `wrap_return_type_in_option` candidate.
pub fn returns_plain_string() -> String {
    String::from("hello")
}
