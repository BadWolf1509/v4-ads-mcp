"""Clients falsos do SDK do Google Ads compartilhados pelos testes.

`client_com_respostas(per_op_errors)`: `mutate()` devolve uma resposta com status
por operacao (None = sucesso, string = mensagem de erro) e `partial_failure_error`
coerente com eles.

`client_de_sucesso()`: `mutate()` devolve resposta vazia, sem falha parcial.
"""

from unittest.mock import MagicMock


def client_com_respostas(per_op_errors):
    """Mock SDK client whose mutate() returns response with per-op statuses.

    Mirrors Sprint 3b.1 test pattern. Each entry: None = success,
    string = error message.
    """
    client = MagicMock()
    fake_responses = []
    for err in per_op_errors:
        r = MagicMock()
        # _pb.WhichOneof reports the set oneof field name on success, None on failure
        if err is None:
            r._pb.WhichOneof = MagicMock(return_value="ad_group_criterion_result")
        else:
            r._pb.WhichOneof = MagicMock(return_value=None)
        fake_responses.append(r)

    response = MagicMock()
    response.mutate_operation_responses = fake_responses

    # Top-level partial_failure_error: set non-zero code if any errors present
    failed_indices = [i for i, e in enumerate(per_op_errors) if e is not None]
    if failed_indices:
        response.partial_failure_error.code = 1
        # Stub details with a GoogleAdsFailure-like object
        fake_detail = MagicMock()
        fake_detail._pb = fake_detail
        fake_detail.type_url = (
            "type.googleapis.com/google.ads.googleads.v20.errors.GoogleAdsFailure"
        )

        class _FakeError:
            def __init__(self, idx, msg):
                self.message = msg
                self.location = MagicMock()
                self.location.field_path_elements = [MagicMock(index=idx)]

        fake_failure_pb = MagicMock()
        fake_failure_pb.errors = [_FakeError(i, per_op_errors[i]) for i in failed_indices]

        def fake_unpack(target_pb):
            target_pb.errors = fake_failure_pb.errors
            return True

        fake_detail.Unpack = fake_unpack
        response.partial_failure_error.details = [fake_detail]

        failure_type_stub = MagicMock()
        failure_type_stub._meta.pb = lambda: MagicMock(errors=[])
    else:
        response.partial_failure_error.code = 0
        response.partial_failure_error.details = []
        failure_type_stub = MagicMock()
        failure_type_stub._meta.pb = lambda: MagicMock(errors=[])

    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=fake_service)

    def get_type(name):
        if name == "GoogleAdsFailure":
            return failure_type_stub
        return MagicMock(
            mutate_operations=[],
            partial_failure_mode=MagicMock(),
        )

    client.get_type = MagicMock(side_effect=get_type)
    client.enums.PartialFailureModeEnum.PARTIAL_FAILURE = "PARTIAL_FAILURE"
    return client


def client_de_sucesso() -> MagicMock:
    client = MagicMock()
    fake_response = MagicMock()
    fake_response.mutate_operation_responses = []
    fake_response.partial_failure_error = MagicMock(code=0, details=[])
    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    client.get_service = MagicMock(return_value=fake_service)
    client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))
    return client
