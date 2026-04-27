//! Family D glob subfamily: targets for `expand_glob_import` and
//! `expand_glob_reexport`.
#![allow(dead_code)]
#![allow(unused_imports)]

// `expand_glob_import` candidate — wildcard pulls in every io trait/struct.
use std::io::*;

pub mod inner {
    pub fn alpha() -> i64 {
        1
    }

    pub fn beta() -> i64 {
        2
    }

    pub struct Gamma {
        pub value: i64,
    }
}

// `expand_glob_reexport` candidate — wildcard re-export of inner module.
pub use crate::inner::*;

pub fn glob_user() -> i64 {
    alpha() + beta() + Gamma { value: 3 }.value
}
