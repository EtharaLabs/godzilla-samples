//! Error values carrying exactly what the JS layer needs to construct the original's
//! exception: the constructor (`Error` / `TypeError` / `RangeError`), the optional
//! `err.code`, and the message.

use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ErrorKind {
    Error,
    TypeError,
    RangeError,
}

impl ErrorKind {
    /// JS constructor name.
    pub fn name(&self) -> &'static str {
        match self {
            ErrorKind::Error => "Error",
            ErrorKind::TypeError => "TypeError",
            ErrorKind::RangeError => "RangeError",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CryptoError {
    pub kind: ErrorKind,
    /// Value of `err.code` (e.g. `ERR_CRYPTO_INVALID_IV`), `None` when the original sets none.
    pub code: Option<&'static str>,
    pub message: String,
}

impl CryptoError {
    pub fn new(kind: ErrorKind, code: Option<&'static str>, message: impl Into<String>) -> Self {
        CryptoError { kind, code, message: message.into() }
    }
    /// Plain `Error` without a code.
    pub fn error(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Error, None, message)
    }
    /// `TypeError` without a code.
    pub fn type_error(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::TypeError, None, message)
    }
    /// `RangeError` without a code.
    pub fn range_error(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::RangeError, None, message)
    }
    /// `Error` with a code.
    pub fn coded(kind: ErrorKind, code: &'static str, message: impl Into<String>) -> Self {
        Self::new(kind, Some(code), message)
    }
}

impl fmt::Display for CryptoError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CryptoError {}

impl From<CryptoError> for String {
    fn from(e: CryptoError) -> String {
        e.message
    }
}
