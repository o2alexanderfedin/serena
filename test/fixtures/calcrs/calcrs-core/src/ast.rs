//! AST node definitions for the calcrs fixture calculator.

#![allow(dead_code)]

/// A minimal arithmetic expression tree.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Expr {
    Lit(i64),
    Add(Box<Expr>, Box<Expr>),
    Mul(Box<Expr>, Box<Expr>),
    Neg(Box<Expr>),
}

impl Expr {
    /// Returns the literal value if this is a `Lit`, otherwise `None`.
    pub fn as_literal(&self) -> Option<i64> {
        match self {
            Expr::Lit(v) => Some(*v),
            _ => None,
        }
    }

    /// Build a new addition node.
    pub fn add(lhs: Expr, rhs: Expr) -> Self {
        Expr::Add(Box::new(lhs), Box::new(rhs))
    }

    /// Build a new multiplication node.
    pub fn mul(lhs: Expr, rhs: Expr) -> Self {
        Expr::Mul(Box::new(lhs), Box::new(rhs))
    }
}
