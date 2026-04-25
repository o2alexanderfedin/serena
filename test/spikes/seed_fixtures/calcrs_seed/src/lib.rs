pub fn add(a: i64, b: i64) -> i64 {
    a + b
}

pub fn mul(a: i64, b: i64) -> i64 {
    a * b
}

pub mod inline {
    pub fn negate(a: i64) -> i64 {
        -a
    }

    pub struct Point {
        pub x: i64,
        pub y: i64,
    }

    impl Point {
        pub fn new(x: i64, y: i64) -> Self {
            Self { x, y }
        }
    }
}

pub use inline::negate;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn add_works() {
        assert_eq!(add(2, 3), 5);
    }
}

#[cfg(feature = "_spike_proc_macro")]
mod proc_macro_target {
    use std::fmt;

    macro_rules! decl_macro {
        ($name:ident) => {
            pub fn $name() -> i64 { 0 }
        };
    }

    decl_macro!(zero);

    #[derive(Debug, Clone)]
    pub struct Sample {
        pub label: String,
    }

    impl fmt::Display for Sample {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "{}", self.label)
        }
    }
}
