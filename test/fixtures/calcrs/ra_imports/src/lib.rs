//! Family D: import assists. Refactor targets for `remove_unused_imports`,
//! `merge_imports`, `qualify_path`, `split_imports`, `normalize_imports`.
#![allow(dead_code)]
#![allow(unused_imports)]

// Unused import — `remove_unused_imports` candidate.
use std::collections::HashMap;

// Mergeable imports — `merge_imports` candidate.
use std::io::{Read};
use std::io::{Write};

// Split-target sibling imports — `split_imports` candidate.
use std::sync::{Arc, Mutex};

// Normalize-target tree imports — `normalize_imports` candidate.
use std::collections::{BTreeMap, BTreeSet};
use std::collections::{HashSet, VecDeque};

pub fn qualify_path_target() -> Vec<i64> {
    // `Vec::new()` is qualifyable to `std::vec::Vec::new()` — `qualify_path`
    // candidate.
    Vec::new()
}

pub struct UsesArcMutex {
    pub inner: Arc<Mutex<i64>>,
}

pub fn use_btreemap_btreeset() -> (BTreeMap<i64, i64>, BTreeSet<i64>) {
    (BTreeMap::new(), BTreeSet::new())
}

pub fn use_hashset_vecdeque() -> (HashSet<i64>, VecDeque<i64>) {
    (HashSet::new(), VecDeque::new())
}

pub fn read_write_user<R: Read, W: Write>(_r: R, _w: W) {}
