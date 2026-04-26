//! Error type for the calcrs fixture calculator.

#![allow(dead_code)]

use std::fmt;

/// Errors raised by the evaluator.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CalcError {
    Overflow,
    DivisionByZero,
    UnknownOperator(String),
}

impl fmt::Display for CalcError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CalcError::Overflow => write!(f, "arithmetic overflow"),
            CalcError::DivisionByZero => write!(f, "division by zero"),
            CalcError::UnknownOperator(op) => write!(f, "unknown operator: {op}"),
        }
    }
}

impl std::error::Error for CalcError {}
