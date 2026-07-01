use pyo3::prelude::*;

#[path = "../services/settings_service.rs"]
pub mod settings_service;

#[pymodule]
fn launcher_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    settings_service::register(m)?;
    Ok(())
}
