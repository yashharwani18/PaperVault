from knowledge_library.retrieval import literal_match, literal_query

def test_literal_search_checks_complete_unicode_tokens_and_punctuation():
    assert literal_match('inv25','Invoice Number INV-inv25 customer')
    assert not literal_match('inv25','Invoice Number INV-inv125 customer')
    assert literal_match('shortest-path','Shortest path algorithms')
    assert not literal_match('cat','education')
    assert not literal_match('!!!','anything')

def test_invoice_number_query_can_find_literal_inv_number():
    assert literal_query('invoice number 25') == 'inv25'
    assert literal_query('inv25') == 'inv25'
    assert literal_query('Fourier transform') == 'Fourier transform'
