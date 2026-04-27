//! Family L: diagnostic-quickfix targets. One item per kind cluster:
//! missing semicolon (test will remove), missing type annotation
//! (typed in baseline; tests trigger by removing), missing turbofish in
//! generic context, dead-code (always present), snake_case lint trigger,
//! `let_else` candidate, `Option::unwrap()` candidate.
#![allow(dead_code)]
#![allow(non_snake_case)]
#![allow(clippy::let_and_return)]

// Cluster 1: missing-semicolon candidate. Tests remove the trailing `;`
// from the let to fire the quickfix.
pub fn missing_semicolon_target() -> i64 {
    let value = 7;
    value
}

// Cluster 2: missing-type-annotation candidate. Tests remove the `: i64`
// to fire the type-annotation quickfix.
pub fn missing_type_annotation_target() -> i64 {
    let x: i64 = 1;
    x
}

// Cluster 3: missing-turbofish candidate in generic context.
pub fn missing_turbofish_target() -> Vec<i64> {
    let v: Vec<i64> = Vec::new();
    v
}

// Cluster 4: dead-code item — always present, fires dead-code quickfix
// when the module-level allow is removed.
fn dead_code_target() -> i64 {
    42
}

// Cluster 5: snake_case lint trigger — `nonSnakeCase` identifier fires
// non_snake_case quickfix when the module-level allow is removed.
pub fn nonSnakeCase_function() -> i64 {
    1
}

#[allow(non_camel_case_types)]
pub struct nonSnakeCaseStruct {
    pub innerField: i64,
}

// Cluster 6: `let_else` candidate.
pub fn let_else_candidate(opt: Option<i64>) -> i64 {
    let value = match opt {
        Some(v) => v,
        None => return 0,
    };
    value
}

// Cluster 7: `Option::unwrap()` quickfix candidate.
pub fn option_unwrap_target() -> i64 {
    let opt: Option<i64> = Some(7);
    opt.unwrap()
}
