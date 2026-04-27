//! Family E: visibility assists. Refactor targets for `fix_visibility`,
//! `change_visibility`, and `pub(crate)` candidate identification.
#![allow(dead_code)]

pub mod producer {
    /// Private struct intentionally not `pub` — `fix_visibility` candidate when
    /// a sibling module references it.
    pub(super) struct PrivateRecord {
        pub value: i64,
    }

    /// Private function — `fix_visibility` candidate.
    pub(super) fn private_helper() -> i64 {
        42
    }

    /// `pub(crate)` candidate — currently fully public but only used in-crate.
    pub fn crate_local_candidate() -> i64 {
        7
    }
}

mod private_module {
    pub fn inner_helper() -> i64 {
        13
    }
}

pub mod consumer {
    use super::producer::{private_helper, PrivateRecord};

    /// Sibling-module reference fires `fix_visibility` on `PrivateRecord` and
    /// `private_helper` (currently `pub(super)` so it compiles; tests will
    /// downgrade visibility to fire the assist).
    pub fn use_private_items() -> i64 {
        let record = PrivateRecord { value: 1 };
        record.value + private_helper()
    }
}

pub fn use_private_module() -> i64 {
    private_module::inner_helper()
}
