# 주간업무일지 LLM 요약 시스템

PPT/PPTX/PDF 주간업무일지를 업로드하면 텍스트 추출, Ollama 구조화, 요약, 이력 조회와 원본 다운로드를 제공하는 사내용 FastAPI MVP입니다.

## 주요 동작

- 확장자, MIME, 파일 시그니처를 함께 검사하고 UUID 파일명으로 `data/uploads/YYYY/MM/`에 저장합니다.
- `.ppt`는 LibreOffice `soffice --headless`로 임시 PPTX 변환 후 삭제합니다.
- PPTX의 텍스트 상자·표를 슬라이드별로, `top`/`left` 좌표 순서로 추출합니다.
- PDF는 페이지 제한을 적용해 `pypdf`로 추출하며 텍스트가 거의 없으면 별도 OCR 서비스 지점으로 넘깁니다. 이 MVP에는 OCR 구현이 연결되어 있지 않습니다.
- 긴 문서는 페이지/문단 경계로 나눠 부분 요약한 후 구조화하며 중복 항목을 제거합니다.
- Ollama 호출은 프로세스 내에서 동시에 하나만 실행하며 `think: false`와 JSON 출력을 사용합니다. JSON 파싱 실패 시 형식 수정 요청을 정확히 한 번 재시도합니다. 최종 Markdown은 구조화된 항목을 그대로 렌더링해 두 번째 LLM 요약 단계에서 업무가 누락되지 않게 합니다.
- SQLite JSON 컬럼과 WAL 모드를 사용합니다.
- 최대 10개의 일지를 한 묶음으로 업로드하고, 사람별 지난주 완료 업무와 금주 예정 업무를 카드형 팀 요약 화면에서 비교합니다.

## 준비

Python 3.11 이상, Ollama, 구형 `.ppt` 처리를 위한 LibreOffice가 필요합니다.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
ollama pull qwen3:1.7b
```

LibreOffice가 PATH에 없다면 `.env`의 `SOFFICE_PATH`에 `soffice.exe` 절대 경로를 지정합니다. 기본 디스크 정책은 사용률 80% 미만이면서 여유 공간 15GB 이상일 때만 업로드를 허용합니다. 개발 PC 여건에 맞게 `.env`에서 조정할 수 있습니다.

## 실행

프로젝트 루트에서 다음을 실행하고 `http://127.0.0.1:8000`을 엽니다.

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

상태 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

## 테스트

Ollama가 없어도 HTTP mock으로 전체 테스트를 실행할 수 있습니다.

```powershell
pytest -q
```

## API

- `GET /` 업로드 및 처리 이력 화면
- `POST /api/reports` 업로드(비동기 처리 등록)
- `POST /api/reports/batch` 최대 10개 팀 일지 업로드(비동기 처리 등록)
- `GET /api/reports` 목록
- `GET /api/reports/{id}` 상세 JSON
- `GET /api/reports/{id}/status` 처리 상태
- `GET /api/reports/{id}/download` 등록 원본 다운로드
- `GET /api/health` 상태 확인

팀 묶음 업로드는 화면에서 파일을 최대 10개 선택하면 됩니다. 각 보고서에 작성자·부서·기준일이 들어 있는 표준 양식이면 해당 값을 자동으로 읽으며, 완료 후 팀 요약 화면으로 이동합니다.

## 운영상 제한

백그라운드 처리는 FastAPI 프로세스 내부 작업을 사용합니다. 별도 큐가 없으므로 프로세스 재시작 시 `uploaded` 또는 `processing` 작업이 유실될 수 있고, 다중 워커에서는 LLM 동시 실행 제한이 워커별로 적용됩니다. 운영 확장 시에는 영속 작업 큐와 재시작 복구 절차가 필요합니다.

스캔 PDF OCR은 의도적으로 `ScannedPdfService`로 분리했지만 외부 OCR 서비스는 포함하지 않았습니다. 암호화·DRM 문서, 손상된 문서, LibreOffice가 변환하지 못하는 일부 구형 PPT는 실패 상태와 오류 메시지로 기록됩니다.

실제 샘플 `.ppt`는 저장소에 포함하지 않습니다. 로컬에서 업로드해 추출과 처리를 통합 검증할 수 있습니다.
