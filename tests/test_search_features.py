import io
import fitz
import pytest
from tests.test_desktop import session, FIX

def test_skipped_files_auditor_endpoint(session):
    client, desktop = session
    res = client.get('/api/auditor/skipped-files')
    assert res.status_code == 200
    data = res.json()
    assert 'summary' in data
    assert 'documents' in data
    assert 'tasks' in data
    assert 'discovered' in data
    assert 'total_skipped' in data['summary']
    assert 'needs_ocr' in data['summary']
    assert 'unreadable_or_corrupt' in data['summary']
    assert 'partial' in data['summary']
    assert isinstance(data['documents'], list)

def test_prefix_search_query_parsing(session):
    client, desktop = session
    # Test bill prefix
    res = client.post('/api/search', json={'query': 'bill: 5310'})
    assert res.status_code == 200
    data = res.json()
    assert 'applied_prefixes' in data
    assert 'Bills only' in data['applied_prefixes']

    # Test ext prefix
    res = client.post('/api/search', json={'query': 'ext:pdf bhagwanti'})
    assert res.status_code == 200
    data = res.json()
    assert 'applied_prefixes' in data
    assert 'Extension: .pdf' in data['applied_prefixes']

    # Test combined prefixes
    res = client.post('/api/search', json={'query': 'ext:pdf bill:yes bhagwanti'})
    assert res.status_code == 200
    data = res.json()
    assert 'applied_prefixes' in data
    assert 'Extension: .pdf' in data['applied_prefixes']
    assert 'Bills only' in data['applied_prefixes']

def test_two_tier_fast_indexing_creates_partial_then_complete(session, tmp_path):
    client, desktop = session
    # Create an 8-page test PDF
    pdf_path = tmp_path / "eight_pages.pdf"
    doc = fitz.open()
    for i in range(8):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} content with keyword FastTier_{i+1}")
    doc.save(str(pdf_path))
    doc.close()

    folder_id = client.post('/api/folders', json={'name': 'Two Tier Folder'}).json()['id']

    progress_events = []
    def track_progress(evt):
        progress_events.append(evt)

    with desktop.lib() as lib:
        result = lib.import_pdf(
            pdf_path,
            folder_id,
            progress=track_progress
        )

    # Document should finish as indexed
    assert result['document']['page_count'] == 8
    assert result['document']['status'] == 'indexed'
    
    # Confirm that tier1_ready progress stage was emitted
    tier1_events = [e for e in progress_events if e.get('stage') == 'tier1_ready']
    assert len(tier1_events) >= 1
    assert tier1_events[0]['page'] == 5
