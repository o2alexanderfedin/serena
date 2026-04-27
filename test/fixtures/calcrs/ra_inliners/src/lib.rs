//! Family C: inliners. Refactor targets for `inline_local_variable`,
//! `inline_call`, `inline_into_callers`, `inline_type_alias`,
//! `inline_macro`, `inline_const_as_literal`.
#![allow(dead_code)]

pub fn inline_local_variable_target() -> i64 {
    let x = 7;
    x * 2
}

pub fn inline_call_callee(x: i64) -> i64 {
    x + 1
}

pub fn inline_call_target() -> i64 {
    inline_call_callee(41)
}

pub fn inline_into_callers_definition(n: i64) -> i64 {
    n * 3 + 1
}

pub fn inline_into_callers_caller_a() -> i64 {
    inline_into_callers_definition(1)
}

pub fn inline_into_callers_caller_b() -> i64 {
    inline_into_callers_definition(2)
}

pub fn inline_into_callers_caller_c() -> i64 {
    inline_into_callers_definition(3)
}

pub type InlineTypeAliasTarget = Result<Vec<i64>, std::io::Error>;

pub fn inline_type_alias_user() -> InlineTypeAliasTarget {
    Ok(vec![1, 2, 3])
}

#[macro_export]
macro_rules! square {
    ($x:expr) => {
        $x * $x
    };
}

pub fn inline_macro_target() -> i64 {
    square!(5)
}

pub const INLINE_CONST_AS_LITERAL_TARGET: i64 = 1024;

pub fn inline_const_as_literal_user() -> i64 {
    INLINE_CONST_AS_LITERAL_TARGET + 1
}
