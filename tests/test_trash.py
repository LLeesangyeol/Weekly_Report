from app.repositories.report_repository import ReportRepository


def test_trashed_report_is_hidden_from_normal_document_list(db, tmp_path):
    repository = ReportRepository(db)
    report = repository.create(
        original_filename="삭제할 문서.pdf", stored_filename="trash-test.pdf",
        file_path=str(tmp_path / "trash-test.pdf"), file_size=1,
        content_type="application/pdf", source_type="pdf", model_name="qwen3:1.7b",
    )

    repository.move_to_trash(report)

    assert repository.list() == []
    assert [item.id for item in repository.list(include_deleted=True) if item.deleted_at] == [report.id]
    repository.restore(report)
    assert [item.id for item in repository.list()] == [report.id]
