//! Headline `calcrs` fixture entry crate.
//!
//! Exists only as a refactor target for rust-analyzer assist families.
//! Re-exports `calcrs-core` symbols and adds a few thin wrappers so
//! integration tests have something to ask `extract`/`inline`/`rename`
//! about across the workspace.

#![allow(dead_code)]

use calcrs_core::ast::Expr;
use calcrs_core::eval::evaluate;

/// Convenience wrapper that evaluates a constant expression.
pub fn eval_const(expr: &Expr) -> i64 {
    evaluate(expr)
}

/// Wrapper that evaluates and doubles — a small refactor target.
pub fn eval_doubled(expr: &Expr) -> i64 {
    let value = evaluate(expr);
    value * 2
}

/// Build the canonical demo expression: (1 + 2) * 3.
pub fn demo_expr() -> Expr {
    let one = Expr::Lit(1);
    let two = Expr::Lit(2);
    let three = Expr::Lit(3);
    let sum = Expr::Add(Box::new(one), Box::new(two));
    Expr::Mul(Box::new(sum), Box::new(three))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn demo_expr_evaluates_to_nine() {
        assert_eq!(eval_const(&demo_expr()), 9);
    }

    #[test]
    fn demo_expr_doubled_is_eighteen() {
        assert_eq!(eval_doubled(&demo_expr()), 18);
    }
}
