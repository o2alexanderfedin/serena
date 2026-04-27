//! Extension shapes — one item per WorkspaceEdit variant per scope-report
//! §4.6: TextDocumentEdit-only target, SnippetTextEdit candidate, CreateFile
//! candidate (referenced-but-missing module), RenameFile candidate (file
//! with mismatched primary-symbol name), DeleteFile candidate
//! (`#[deprecated]` empty file), changeAnnotations candidate (renameable
//! item).
#![allow(dead_code)]

// TextDocumentEdit-only target — plain rename target with no
// cross-file ripple.
pub fn rename_me_inplace() -> i64 {
    1
}

// SnippetTextEdit candidate — a fn-stub callsite the assist can complete
// with a snippet placeholder.
pub fn snippet_target_callsite() -> i64 {
    let _ = snippet_target_callee;
    7
}

pub fn snippet_target_callee(x: i64) -> i64 {
    x + 1
}

// CreateFile candidate — referenced-but-missing module declaration kept
// commented so the workspace stays green; tests uncomment to fire
// the assist's CreateFile workspace edit.
// pub mod missing;

// Stand-in for the would-be module so the workspace_edit_shapes crate
// compiles; tests will swap this for the `pub mod missing;` form.
pub mod missing_stub {
    pub fn placeholder() -> i64 {
        0
    }
}

// RenameFile candidate — primary symbol name `RenameFilePrimary` lives
// inside `mod mismatched_filename` (would-be filename
// `mismatched_filename.rs` — the assist offers RenameFile to align
// filename with primary symbol).
pub mod mismatched_filename {
    pub struct RenameFilePrimary {
        pub value: i64,
    }
}

// DeleteFile candidate — `#[deprecated]` empty module, future cleanup
// proposed by the assist as a DeleteFile workspace edit.
#[deprecated(note = "kept as DeleteFile workspace-edit candidate")]
pub mod deprecated_empty {}

// changeAnnotations candidate — the public symbol is renameable and
// the assist annotates the change with rationale metadata.
pub fn change_annotation_target() -> i64 {
    13
}
