//! Family F: ordering. Refactor targets for `sort_items`,
//! `reorder_methods`, `reorder_fields`.
#![allow(dead_code)]

pub struct Foo {
    pub value: i64,
}

// impl block with 3 methods in non-alphabetic order — `reorder_methods` candidate.
impl Foo {
    pub fn zeta(&self) -> i64 {
        self.value + 3
    }

    pub fn alpha(&self) -> i64 {
        self.value
    }

    pub fn mu(&self) -> i64 {
        self.value + 1
    }
}

// Free fn list in non-alphabetic order — `sort_items` candidate.
pub fn z_function() -> i64 {
    3
}

pub fn a_function() -> i64 {
    1
}

pub fn m_function() -> i64 {
    2
}

// Struct with reorder-target field list — `reorder_fields` candidate.
pub struct ReorderableFields {
    pub zulu: i64,
    pub alpha: i64,
    pub mike: i64,
    pub bravo: i64,
}
