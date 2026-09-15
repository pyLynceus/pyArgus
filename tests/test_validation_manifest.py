import pytest
from devtools.validate import junit_summary, decision

def test_junit_records_skips_failures_and_collection_errors(tmp_path):
    p=tmp_path/'result.xml'
    p.write_text('''<testsuites><testsuite>
    <testcase classname="a" name="ok"/>
    <testcase classname="a" name="skip"><skipped message="requires PDAL"/></testcase>
    <testcase classname="a" name="bad"><failure message="wrong result"/></testcase>
    <testcase classname="a" name="collect"><error>import failed</error></testcase>
    </testsuite></testsuites>''')
    r=junit_summary(p)
    assert r['counts']==dict(passed=1,skipped=1,failure=1,error=1)
    assert [t['reason'] for t in r['nonpassing']]==['requires PDAL','wrong result','import failed']

@pytest.mark.parametrize('code,skips,after,want',[
    (0,0,'same','passed_requested_checks'),
    (0,1,'same','needs_skip_review'),
    (1,0,'same','failed'),
    (0,0,'changed','invalid_source_changed'),
])
def test_gate_never_calls_skipped_or_changed_run_passed(code,skips,after,want):
    tests=dict(total=2,counts=dict(passed=2-skips,skipped=skips,failure=0,error=0))
    assert decision([dict(returncode=code)],tests,'same',after)==want

def test_empty_results_cannot_pass():
    assert decision([dict(returncode=0)],dict(total=0),'same','same')=='failed_missing_test_results'
