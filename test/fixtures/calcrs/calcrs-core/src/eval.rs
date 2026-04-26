//! Evaluator over `ast::Expr`.

#![allow(dead_code)]

use crate::ast::Expr;

/// Evaluate an expression to an `i64`.  Saturating arithmetic keeps
/// the fixture deterministic under refactor scenarios that introduce
/// large literals.
pub fn evaluate(expr: &Expr) -> i64 {
    match expr {
        Expr::Lit(v) => *v,
        Expr::Add(l, r) => evaluate(l).saturating_add(evaluate(r)),
        Expr::Mul(l, r) => evaluate(l).saturating_mul(evaluate(r)),
        Expr::Neg(inner) => evaluate(inner).saturating_neg(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lit_returns_value() {
        assert_eq!(evaluate(&Expr::Lit(42)), 42);
    }

    #[test]
    fn add_sums_branches() {
        let e = Expr::add(Expr::Lit(2), Expr::Lit(3));
        assert_eq!(evaluate(&e), 5);
    }

    #[test]
    fn mul_multiplies_branches() {
        let e = Expr::mul(Expr::Lit(4), Expr::Lit(5));
        assert_eq!(evaluate(&e), 20);
    }

    #[test]
    fn neg_negates_value() {
        assert_eq!(evaluate(&Expr::Neg(Box::new(Expr::Lit(7)))), -7);
    }
}
