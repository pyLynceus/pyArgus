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


def test_distribution_inventory_reports_nameless_metadata_without_crashing():
    from types import SimpleNamespace
    from devtools.validate import distribution_inventory
    result = distribution_inventory([
        SimpleNamespace(metadata={'Name':'numpy'},version='2.4',_path='numpy.dist-info'),
        SimpleNamespace(metadata={},version=None,_path='pyargus-0.1.0.dist-info'),
        SimpleNamespace(metadata={'Name':'laspy'},version='2.7',_path='laspy.dist-info')])
    assert [row['name'] for row in result['packages']] == ['laspy','numpy']
    assert result['environment_warnings'] == [dict(
        location='pyargus-0.1.0.dist-info', error='ValueError: missing distribution Name')]


def test_environment_warning_cannot_get_clean_pass_but_does_not_hide_failure():
    tests = dict(total=1,counts=dict(passed=1,skipped=0,failure=0,error=0))
    warnings = [dict(location='bad.dist-info',error='bad metadata')]
    assert decision([dict(returncode=0)],tests,'same','same',warnings) == 'needs_environment_review'
    assert decision([dict(returncode=1)],tests,'same','same',warnings) == 'failed'
