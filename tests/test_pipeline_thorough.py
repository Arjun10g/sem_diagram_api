from app.services.pipeline import run_render_pipeline


def test_pipeline_runs():
    syntax = "f =~ x1 + x2"
    result = run_render_pipeline(syntax)
    assert "graph" in result

def test_large_sem_model_runs():
    syntax = '''
    f1 =~ x1 + x2 + x3
    f2 =~ x4 + x5 + x6
    f3 =~ x7 + x8 + x9

    f2 ~ f1
    f3 ~ f2

    x1 ~~ x1
    x2 ~~ x2
    x3 ~~ x3
    x4 ~~ x4
    x5 ~~ x5
    x6 ~~ x6
    x7 ~~ x7
    x8 ~~ x8
    x9 ~~ x9
    '''

    result = run_render_pipeline(syntax)
    assert result["graph"] is not None
    assert result["dot"] is not None