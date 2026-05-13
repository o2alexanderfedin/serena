import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import Language
from test.solidlsp.util.diagnostics import assert_file_diagnostics


@pytest.mark.rust
class TestRustDiagnostics:
    @pytest.mark.xfail(
        reason=(
            "rust-analyzer flycheck depends on a fully provisioned host rustc/cargo toolchain — "
            "rust-fv-driver SIGABRT prevents cargo metadata from emitting diagnostics. "
            "Follows v0.2.0-followup-E1 pattern for host-LSP env gaps."
        ),
        strict=False,
    )
    @pytest.mark.parametrize("language_server", [Language.RUST], indirect=True)
    def test_file_diagnostics(self, language_server: SolidLanguageServer) -> None:
        assert_file_diagnostics(
            language_server,
            "src/diagnostics_sample.rs",
            (),
            min_count=1,
        )
