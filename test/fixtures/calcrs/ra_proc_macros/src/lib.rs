//! Proc-macro pathway crate. The only fixture crate with crates.io deps.
//! Refactor targets exercise rust-analyzer's proc-macro server: serde
//! `#[derive]`, `#[tokio::main]`, `#[async_trait]`, `#[derive(clap::Parser)]`.
#![allow(dead_code)]

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
pub struct Payload {
    pub id: u64,
    pub label: String,
}

#[derive(clap::Parser)]
pub struct Cli {
    #[arg(long)]
    pub name: String,

    #[arg(long, default_value_t = 0)]
    pub count: u32,
}

#[async_trait]
pub trait AsyncGreeter {
    async fn greet(&self, who: &str) -> String;
}

pub struct EnglishGreeter;

#[async_trait]
impl AsyncGreeter for EnglishGreeter {
    async fn greet(&self, who: &str) -> String {
        format!("Hello, {who}!")
    }
}

// Use current-thread flavor so the crate can compile with the spec's
// `tokio = { features = ["macros", "rt"] }` set (rt-multi-thread is not
// enabled — keeping the dep set tight per the leaf spec).
#[tokio::main(flavor = "current_thread")]
pub async fn run_main() -> Payload {
    let g = EnglishGreeter;
    let label = g.greet("world").await;
    Payload { id: 1, label }
}
