use calcrs_e2e::{eval, parse};

#[test]
fn add_two_plus_three() {
    let e = parse("2+3").expect("parse");
    assert_eq!(eval(&e).expect("eval"), 5);
}

#[test]
fn mul_four_times_five() {
    let e = parse("4*5").expect("parse");
    assert_eq!(eval(&e).expect("eval"), 20);
}

#[test]
fn div_hundred_by_four() {
    let e = parse("100/4").expect("parse");
    assert_eq!(eval(&e).expect("eval"), 25);
}

#[test]
fn div_by_zero_errors() {
    let e = parse("1/0").expect("parse");
    assert!(eval(&e).is_err());
}
