//! `expandMacro` extension targets. Three macro flavours: declarative
//! `vec!` from std, custom `macro_rules!`, and `#[derive(Debug)]`.
#![allow(dead_code)]

pub fn vec_macro_call() -> Vec<i64> {
    vec![1, 2, 3]
}

#[macro_export]
macro_rules! double {
    ($x:expr) => {
        $x * 2
    };
}

pub fn double_macro_call() -> i64 {
    double!(21)
}

#[derive(Debug)]
pub struct DebugStruct {
    pub id: i64,
    pub name: String,
}

pub fn debug_struct_user() -> String {
    format!("{:?}", DebugStruct { id: 1, name: "x".to_string() })
}
