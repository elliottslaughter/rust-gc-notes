#!/usr/bin/env python

# Summarizes the results running the Rust test suite. Invoke as
# follows:
#
#     make check -k 2>&1 | tee tests.log
#     ./summarize.py tests.log

import pprint, re, sys

# Log format:
#
# running N tests
# test [category] path ...
#(failures:)
#(    [category] path)
# result: ok|FAILED. X passed; Y failed; Z ignored

_re_category = re.compile(r'^running \d+ tests$', re.MULTILINE)
def split_categories(log):
    return re.split(_re_category, log)

_re_result = re.compile(r'\A(.*)^result: (\w+)\. (\d+) passed; (\d+) failed; (\d+) ignored$.*\Z', re.DOTALL | re.MULTILINE)
_re_failures = re.compile(r'\A(.*)^failures:$.*\Z', re.DOTALL | re.MULTILINE)
_re_entry = re.compile(r'^(test \[[\w\-]+\] [\w\-/.]+ \.\.\. \w*)$', re.MULTILINE)
def split_entries(category):
    result = {'status': None, 'passed': None, 'failed': None, 'ignored': None}
    match = re.match(_re_result, category)
    if match is not None:
        category = match.group(1)
        result = {'status': match.group(2),
                  'passed': int(match.group(3)),
                  'failed': int(match.group(4)),
                  'ignored': int(match.group(5))}
    match = re.match(_re_failures, category)
    if match is not None:
        category = match.group(1)
    return (re.split(_re_entry, category), result)

_re_entry_fields = re.compile(r'^test \[([\w\-]+)\] ([\w\-/.]+) \.\.\. (\w*)$', re.MULTILINE)
_re_failure = re.compile(r'\A(.*)^(FAILED)$\s*\Z', re.DOTALL | re.MULTILINE)
def parse_entries(entries):
    tests = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        match = re.match(_re_entry_fields, entry)
        if match is None:
            continue
        category = match.group(1)
        path = match.group(2)
        status = match.group(3)
        output = ''
        peek = entries[i]
        if re.match(_re_entry, peek) is None:
            output = peek
            i += 1
        match = re.match(_re_failure, output)
        if len(status) == 0 and match is not None:
            output = match.group(1)
            status = match.group(2)
        tests.append({'category': category,
                      'path': path,
                      'status': status,
                      'output': output})
    return tests

_re_gcregroot = re.compile(r'LLVM ERROR: Cannot select: intrinsic %llvm.gcregroot')
def diagnose_entries(entries):
    for entry in entries:
        if entry['status'] == 'ok':
            entry['diagnosis'] = 'passed'
            continue
        if entry['status'] == 'ignored':
            entry['diagnosis'] = 'ignored'
            continue
        if entry['status'] == 'FAILED':
            match = re.search(_re_gcregroot, entry['output'])
            if match is not None:
                entry['diagnosis'] = 'gcregroot'
                continue
            # Elliott: etc....
            entry['diagnosis'] = 'unknown'
            continue
        print 'Unknown status %s for entry:' % entry['status']
        pprint.pprint(entry)
        sys.exit(1)
    return entries

def summarize_category(entries, result):
    if len(entries) == 0:
        return None
    name = entries[0]['category']
    assert all(entry['category'] == name for entry in entries)
    entries_by_diagnosis = {}
    for entry in entries:
        if entry['diagnosis'] not in entries_by_diagnosis:
            entries_by_diagnosis[entry['diagnosis']] = []
    for entry in entries:
        entries_by_diagnosis[entry['diagnosis']].append(entry)
    diagnosis = {'passed': 0, 'ignored': 0, 'gcregroot': 0, 'unknown': 0}
    diagnosis.update(dict((diagnosis, len(entries)) for diagnosis, entries in entries_by_diagnosis.iteritems()))
    assert diagnosis['passed'] == result['passed']
    assert diagnosis['ignored'] == result['ignored']
    assert diagnosis['gcregroot'] + diagnosis['unknown'] == result['failed']
    return {'category': name, 'result': result, 'diagnosis': diagnosis, 'entries': entries_by_diagnosis}

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print 'Usage: %s <log>' % sys.argv[0]
    with open(sys.argv[1], 'rb') as f: log = f.read()
    cats = split_categories(log)
    entses = [split_entries(cat) for cat in cats]
    entses = [(diagnose_entries(parse_entries(ents)), result) for ents, result in entses]
    summaries = [summarize_category(ents, result) for ents, result in entses]
    summaries = [summary for summary in summaries if summary is not None]

    print '/========================\\'
    print '      Result Summary     '
    print '\\========================/'
    print

    key_order = ['passed', 'ignored', 'gcregroot', 'unknown']
    for summary in summaries:
        total = sum(v for v in summary['diagnosis'].itervalues())
        print '%12s: %s' % (summary['category'],
                          ','.join('%3s (%5.1f%%) %s' % (summary['diagnosis'][k],
                                                         summary['diagnosis'][k]*100.0/total,
                                                         k)
                                   for k in key_order))

    print
    print '/========================\\'
    print '   Undiagnosed Failures  '
    print '\\========================/'
    print
    for summary in summaries:
        if 'unknown' in summary['entries']:
            for entry in summary['entries']['unknown']:
                print 'test [%s] %s ... %s' % (entry['category'], entry['path'], entry['status'])
                print entry['output']
                print
