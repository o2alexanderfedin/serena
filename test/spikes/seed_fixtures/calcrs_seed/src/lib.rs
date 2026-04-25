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
