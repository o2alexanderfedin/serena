//! Extension SSR (structural search and replace). Refactor targets shaped
//! for SSR queries: `.unwrap()` on Option and Result, `Result<T, E>`
//! typedefs, and a literal pattern match.
#![allow(dead_code)]

pub fn unwrap_option_call() -> i64 {
    let some_value: Option<i64> = Some(7);
    some_value.unwrap()
}

pub fn unwrap_result_call() -> i64 {
    let result_value: Result<i64, std::io::Error> = Ok(7);
    result_value.unwrap()
}

pub fn unwrap_chained() -> i64 {
    let nested: Option<Result<i64, std::io::Error>> = Some(Ok(7));
    nested.unwrap().unwrap()
}

pub type SsrResult<T> = Result<T, std::io::Error>;
pub type SsrIntResult = Result<i64, std::io::Error>;

pub fn use_ssr_alias(x: i64) -> SsrResult<i64> {
    Ok(x)
}

pub fn use_ssr_int_alias(x: i64) -> SsrIntResult {
    Ok(x)
}

// Literal pattern match — common SSR query target.
pub fn literal_match(x: i64) -> &'static str {
    match x {
        0 => "zero",
        _ => "other",
    }
}

pub fn literal_match_string(s: &str) -> &'static str {
    match s {
        "" => "empty",
        _ => "non-empty",
    }
}
