def test_a_long_page_cannot_vote_multiple_times():
    from scripts.evaluate_android_retrieval import page_unique,fuse
    chunks=[{'id':1,'document':'a','page_number':1},{'id':2,'document':'a','page_number':1},{'id':3,'document':'b','page_number':1}]
    semantic=page_unique([(0,.9),(1,.89),(2,.8)],chunks)
    assert semantic==[0,2]
    ranked=fuse([semantic,[2]],chunks,[.5,.5],60)
    assert ranked[0]==2


def test_fusion_preserves_the_best_source_passage_for_a_page():
    from scripts.evaluate_android_retrieval import page_unique,fuse
    chunks=[{'id':1,'document':'a','page_number':1},{'id':2,'document':'a','page_number':1},{'id':3,'document':'b','page_number':2}]
    assert page_unique([(1,.9),(0,.8),(2,.7)],chunks)==[1,2]
    result=fuse([[1],[0,2]],chunks,[.75,.25],60)
    assert result==[1,2]
