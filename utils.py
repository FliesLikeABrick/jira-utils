#! /usr/bin/env python3
from jira import JIRA
import re
import sre_constants
import logging

def find_and_replace(issue_jql, replacements, additional_tests=None, dry_run=False, server=None, credentials=None, jira=None):
    '''Perform a find and replace in JIRA.  The logic errs on the side of safety and will skip attempting find+replace if a number of sanity checks fail, where the user's input may be flawed.
    Args:
      issue_jql (str): The JQL query to select issues in-scope
      replacements (list): list of dicts with keys `field_name`, `old` and `new` replacements to perform.  old and new are strings, regex is not supported here.
      additional_tests (list): List where each entry is a test to run.  Each entry is a dict containing the `field_name` and `regex`  to test.  All tests must pass for any replacements to occur on this issue.
      dry_run (bool): Perform a dry run, printing replacements to debug only.
      credentials (tuple): tuple of strings for username, password
      jira (obj): An optional jira.JIRA instance to use, instead of creating one
    '''
    additional_tests = additional_tests if additional_tests else []
    # pre-compile regexes
    for test in additional_tests:
        if 'regex' in test:
            try:
                test['regex_compiled'] = re.compile(test['regex'])
            except sre_constants.error:
                sys.stderr.write(f"ERROR: Test for field_name {test['field_name']}, regex {test['regex']} failed compilation. Aborting find and replace to avoid unintended matches with this broken test\n")
                return
        else:
            sys.stderr.write(f"ERROR: Test for field_name {test['field_name']} does not contain a regex. Aborting find and replace to avoid unintended matches with this broken test\n")
            return
    jira = jira if jira else JIRA(server=server, basic_auth=credentials) 
    issues = jira.search_issues(issue_jql, maxResults=0)
    selected_issues = len(issues)
    issues_failed_tests = 0
    changed_issues = 0
    unchanged_issues = 0
    failed_issues = 0
    print(f"find_and_replace evluating {selected_issues} tickets")
    for issue in issues:
        print(f"Evaluating {issue.key}")
        issue_fields = dir(issue.fields)
        tests_passed = True
        for test in additional_tests:
            if test['field_name'] not in issue_fields:
                sys.stderr.write(f"WARNING: Issue {issue.key} does not have field {test['field_name']}, the test is being treated as failed and issue is being skipped")
                tests_passed = False
                break
            if not test['regex_compiled'].search(getattr(issue_fields, test['field_name'])):
                # future refactor when classful - log message to debug about test failing
                tests_passed = False
                break

        if not tests_passed:
            issues_failed_tests += 1
            continue
        # at this point all tests have passed, now check if the find and replace is needed
        replacement_fields = set([replacement['field_name'] for replacement in replacements])
        if not replacement_fields.issubset(set(issue_fields)):
            missing_fields = replacement_fields - set(issue_fields)
            sys.stderr.write(f"ERROR: For issue {issue.key}, the following fields are used in tests are not present in issue: {','.join(missing_fields)}\n")
            sys.stderr.write(f"Skipping any replacement for issue {issue.key}\n")
            failed_issues += 1
            continue
        changes = {}
        for replacement in replacements:
            # order of operations:
            #  1) Check if all fields in the replacement are in the issue - this is done above
            #  2) Check if any fields actually require the replacement
            #  3) If so, perform the replacement and set a `changed` flag to indicate that results need to be pushed back to the API
            #  4) Push the change to the API or if dry_run, print to stdout
            # keep tallies of changes made vs not made
            old_value = getattr(issue.fields, replacement['field_name'])
            if not isinstance(old_value, str):
                print(f"WARNING: skipping update on issue {issue.key} field {replacement['field_name']} due to null or non-str type")
                continue    
            new_value = old_value.replace(replacement['old'],replacement['new'])
            if old_value != new_value:
                changes[replacement['field_name']] = new_value
        if dry_run and changes:
            print(f"Dry run: issue {issue.key} has changes - {changes}")
        elif changes:
            try:
                issue.update(**changes)
                changed_issues += 1
                print(f"{issue.key} fields {','.join(changes.keys())} have been updated")
            # need to identify specific exceptions to catch
            except Exception as exc:
                sys.stderr.write("WARNING: failed to update issue {issue.key}; exception: {exc}\n")
                failed_issues += 1
        else:
            unchanged_issues += 1
    print(f"Summary - issues selected: {selected_issues}, issues which failed tests: {issues_failed_tests}, changed issues: {changed_issues}, unchanged issues: {unchanged_issues}, failed issues {failed_issues}")
