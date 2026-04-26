//! calcrs_e2e — kitchen-sink baseline used by Stage 2B E2E scenarios.
//!
//! The four `mod` blocks below (`ast`, `errors`, `parser`, `eval`) are co-located
//! here so the E1 4-way split scenario can move each `mod foo {...}` body into
//! a sibling file (`src/ast.rs`, `src/errors.rs`, etc.) and the post-split
//! `cargo test` continues to pass byte-identically against the baseline below.

pub mod ast {
    #[derive(Clone, Debug, PartialEq, Eq)]
    pub enum Expr {
        Num(i64),
        Add(Box<Expr>, Box<Expr>),
        Sub(Box<Expr>, Box<Expr>),
        Mul(Box<Expr>, Box<Expr>),
        Div(Box<Expr>, Box<Expr>),
    }
}

pub mod errors {
    #[derive(Debug, PartialEq, Eq)]
    pub enum CalcError {
        ParseError(String),
        DivisionByZero,
    }
}

pub mod parser {
    use super::ast::Expr;
    use super::errors::CalcError;

    pub fn parse(input: &str) -> Result<Expr, CalcError> {
        let s = input.trim();
        if let Some(idx) = s.rfind('+') {
            let l = parse(&s[..idx])?;
            let r = parse(&s[idx + 1..])?;
            return Ok(Expr::Add(Box::new(l), Box::new(r)));
        }
        if let Some(idx) = s.rfind('-') {
            if idx > 0 {
                let l = parse(&s[..idx])?;
                let r = parse(&s[idx + 1..])?;
                return Ok(Expr::Sub(Box::new(l), Box::new(r)));
            }
        }
        if let Some(idx) = s.rfind('*') {
            let l = parse(&s[..idx])?;
            let r = parse(&s[idx + 1..])?;
            return Ok(Expr::Mul(Box::new(l), Box::new(r)));
        }
        if let Some(idx) = s.rfind('/') {
            let l = parse(&s[..idx])?;
            let r = parse(&s[idx + 1..])?;
            return Ok(Expr::Div(Box::new(l), Box::new(r)));
        }
        s.parse::<i64>()
            .map(Expr::Num)
            .map_err(|e| CalcError::ParseError(e.to_string()))
    }
}

pub mod eval {
    use super::ast::Expr;
    use super::errors::CalcError;

    pub fn eval(expr: &Expr) -> Result<i64, CalcError> {
        match expr {
            Expr::Num(n) => Ok(*n),
            Expr::Add(l, r) => Ok(eval(l)? + eval(r)?),
            Expr::Sub(l, r) => Ok(eval(l)? - eval(r)?),
            Expr::Mul(l, r) => Ok(eval(l)? * eval(r)?),
            Expr::Div(l, r) => {
                let rv = eval(r)?;
                if rv == 0 {
                    Err(CalcError::DivisionByZero)
                } else {
                    Ok(eval(l)? / rv)
                }
            }
        }
    }
}

pub use ast::Expr;
pub use errors::CalcError;
pub use eval::eval;
pub use parser::parse;
