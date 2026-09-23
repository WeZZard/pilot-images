#!/usr/bin/env python3
"""Bind guest acceptance evidence to the stopped image; never execute guest checks."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import inventory

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('application_checks', REPO / 'applications/check.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def validate_report(report_path, portable, image, document=None):
    report = inventory.read_json(report_path)
    document = inventory.read_json(portable) if document is None else document
    selection = checks.load(REPO / 'images' / inventory.key(image) / 'application-tests.json')
    if (type(report.get('schemaVersion')) is not int or report.get('schemaVersion') != 1 or report.get('image') != image or report.get('status') != 'pass'
            or report.get('unclassified') != [] or report.get('buildId') != document['provenance']['evidenceId']
            or report.get('planSha256') != checks.plan_digest(REPO / 'applications', selection)
            or report.get('inventorySha256') != document['provenance']['rawSha256']
            or report.get('os') != document['inventory']['os']
            or report.get('architecture') != document['inventory']['architecture']
            or report.get('dependencies') != selection['dependencies']
            or report.get('sources', []) != selection.get('sources', [])):
        raise ValueError('missing, failed or stale application acceptance')
    checks.validate_results(REPO / 'applications', selection, document['inventory'], report)
    results = report.get('applications', [])
    expected = checks.expected_plan_inventory_ids(REPO / 'applications', selection, document['inventory'])
    if [r['id'] for r in results] != list(expected):
        raise ValueError('acceptance plan coverage mismatch')
    installed = {a['id'] for a in document['inventory']['applications']}
    covered = set(selection['dependencies'])
    for result in results:
        checks.validate_baseline_report(result)
        if result['id'].startswith('native:'):
            owned = expected[result['id']]
            if result['inventoryIds'] != owned or result['status'] != 'pass' or owned[0].partition(':')[0] not in selection.get('sources', []):
                raise ValueError('native inventory baseline failed or identity mismatch')
            record = next(a for a in document['inventory']['applications'] if a['id'] == owned[0])
            version = next(c for c in result['baseline'] if c['check'] == 'version')
            if version.get('expected') != record['version']:
                raise ValueError('native baseline version differs from inventory')
            covered.update(owned)
            continue
        manifest = checks.load(REPO / 'applications' / result['id'] / 'manifest.json')
        if result['inventoryIds'] != manifest['inventoryIds']:
            raise ValueError('application inventory identity mismatch')
        covered.update(manifest['inventoryIds'])
        config = manifest['platforms'].get(document['inventory']['os'])
        if result['status'] == 'not-applicable':
            owns = set(manifest['inventoryIds']) | {k for k, v in selection['dependencies'].items() if v['plan'] == result['id']}
            if installed & owns or (config and not config['optional'] and document['inventory']['architecture'] in config['architectures']):
                raise ValueError('required or installed application skipped')
        elif result['status'] == 'pass' and config:
            baseline = result['baseline']
            statuses = {c['check']: c['status'] for c in baseline}
            if (len(baseline) != 3 or set(statuses) != {'availability', 'version', 'launch'}
                    or statuses['availability'] != 'pass' or statuses['launch'] != 'pass'
                    or statuses['version'] != ('pass' if config['version'] is not None else 'not-applicable')
                    or [c['check'] for c in result['extensions']] != config['extensions']
                    or any(c['status'] != 'pass' for c in result['extensions'])):
                raise ValueError('baseline/extension evidence incomplete')
        else:
            raise ValueError('application acceptance failed')
    if selection.get('scope') != 'provisioned' and installed - covered:
        raise ValueError('installed applications lack acceptance plans')
    return report


def raw_document(raw):
    original = inventory.read_bytes(raw)
    observed = inventory.read_json(raw)
    inventory.validate(observed, observed['os'])
    if original != inventory.read_bytes(raw):
        raise ValueError('clone inventory changed during validation')
    return dict(inventory=observed, provenance=dict(evidenceId=Path(raw).parent.name,
        rawSha256=inventory.digest(original)))


def record_image_check(evidence, image, name, script, returncode):
    if name not in ('acceptance', 'no-secrets'):
        raise ValueError('unknown image check')
    evidence = Path(evidence)
    value = dict(name=name, image=image, buildId=evidence.name, script=str(Path(script).resolve()),
        scriptSha256=inventory.digest(inventory.read_bytes(script)),
        retainedScript=str((evidence / Path(script).name).resolve()),
        log=str((evidence / (name + '.log')).resolve()), returncode=returncode)
    value['logSha256'] = inventory.digest(inventory.read_bytes(value['log']))
    # Exclusive creation: attempts and failed results must never be overwritten.
    with (evidence / (name + '.result.json')).open('xb') as stream:
        stream.write(inventory.encode(value))


def validate_image_checks(records, image, build_id):
    if not isinstance(records, list) or len(records) != 2:
        raise ValueError('missing image acceptance/no-secrets evidence')
    for name, record in zip(('acceptance', 'no-secrets'), records):
        path = record['result']
        if record['sha256'] != inventory.digest(inventory.read_bytes(path)):
            raise ValueError('image check result changed')
        value = inventory.read_json(path)
        if (value['name'] != name or value['image'] != image or value.get('buildId') != build_id
                or Path(path).parent.name != build_id
                or type(value['returncode']) is not int or value['returncode'] != 0):
            raise ValueError('failed image check: ' + name)
        script = Path(value['script'])
        if script.parent != REPO / 'images' / inventory.key(image) / 'checks' or script.stem != name or script.suffix not in ('.sh', '.zsh'):
            raise ValueError('incorrect image check script identity')
        attempt = Path(path).parent.resolve()
        if Path(value['retainedScript']).resolve() != attempt / script.name or Path(value['log']).resolve() != attempt / (name + '.log'):
            raise ValueError('image check evidence belongs to another attempt')
        for target in (script, value['retainedScript']):
            if value['scriptSha256'] != inventory.digest(inventory.read_bytes(target)):
                raise ValueError('image check script changed')
        if value['logSha256'] != inventory.digest(inventory.read_bytes(value['log'])):
            raise ValueError('image check log changed')
    return records


def seal(report, association, portable, output, image, raw=None, image_receipt=None):
    validate_report(report, portable, image, raw_document(raw) if raw else None)
    pair = inventory.read_json(association)
    inventory.validate_association(pair, image)
    if image_receipt:
        records = inventory.read_json(image_receipt)['imageChecks']
    else:
        records = []
        for name in ('acceptance', 'no-secrets'):
            path = Path(report).parent / (name + '.result.json')
            records.append(dict(result=str(path.resolve()), sha256=inventory.digest(inventory.read_bytes(path))))
    validate_image_checks(records, image, inventory.read_json(portable)['provenance']['evidenceId'])
    value = dict(schemaVersion=1, image=image, association=pair, imageChecks=records,
        report=str(Path(report).resolve()), reportSha256=inventory.digest(inventory.read_bytes(report)))
    if raw:
        value.update(raw=str(Path(raw).resolve()), rawSha256=inventory.digest(inventory.read_bytes(raw)))
    inventory.atomic_write(output, inventory.encode(value))


def verify(receipt, association, portable, image):
    value = inventory.read_json(receipt)
    inventory.fields(value, ('schemaVersion', 'image', 'association', 'report', 'reportSha256', 'imageChecks'), ('raw', 'rawSha256'))
    if value['schemaVersion'] != 1 or value['image'] != image or value['association'] != inventory.read_json(association):
        raise ValueError('acceptance does not match stopped work association')
    if value['reportSha256'] != inventory.digest(inventory.read_bytes(value['report'])):
        raise ValueError('acceptance report changed')
    validate_image_checks(value['imageChecks'], image, inventory.read_json(portable)['provenance']['evidenceId'])
    document = None
    if 'raw' in value or 'rawSha256' in value:
        document = raw_document(value['raw'])
        if document['provenance']['rawSha256'] != value['rawSha256']:
            raise ValueError('acceptance raw inventory changed')
        compare_inventory(document['inventory'], inventory.read_json(portable)['inventory'])
    validate_report(value['report'], portable, image, document)
    return value['report']


def compare_inventory(clone, work):
    """Compare all installed facts; only the top-level collection time is ignored."""
    inventory.validate(clone, work['os'])
    inventory.validate(work, work['os'])
    if {k: v for k, v in clone.items() if k != 'collectedAt'} != {k: v for k, v in work.items() if k != 'collectedAt'}:
        raise ValueError('fresh clone inventory differs from work observation')


def fresh_inputs(association, portable, image, root, vm, kind):
    pair = inventory.read_json(association)
    inventory.verify(pair, root, vm, image, kind, portable)
    verify(inventory.state_directory(root) / 'acceptance/work' / (image + '.json'),
        association, portable, image)
    return pair


def seal_fresh(evidence, association, portable, output, image, root, vm, kind, plan):
    """Caller holds the maintenance lock and establishes stopped state."""
    evidence = Path(evidence)
    pair = fresh_inputs(association, portable, image, root, vm, kind)
    lease = inventory.read_json(evidence / 'lease.json')
    if (lease.get('source') != 'work' or lease.get('source_vm') != vm
            or lease.get('source_fingerprint') != pair['base'] or lease.get('image_kind') != kind
            or lease.get('vm') == vm):
        raise ValueError('lease does not identify the exact stopped work source')
    inventory.key(lease['vm'])
    raw, report_path = evidence / 'inventory.json', evidence / 'applications.json'
    document = raw_document(raw)
    compare_inventory(document['inventory'], inventory.read_json(portable)['inventory'])
    report = validate_report(report_path, portable, image, document)
    if report['planSha256'] != plan:
        raise ValueError('application plan changed during fresh clone acceptance')
    value = dict(schemaVersion=1, image=image, source='work', association=pair,
        planSha256=plan, buildId=report['buildId'])
    for name, path in (('report', report_path), ('raw', raw), ('lease', evidence / 'lease.json')):
        value[name] = str(path.resolve())
        value[name + 'Sha256'] = inventory.digest(inventory.read_bytes(path))
    if pair != fresh_inputs(association, portable, image, root, vm, kind):
        raise ValueError('work association changed during fresh clone acceptance')
    inventory.atomic_write(output, inventory.encode(value))


def verify_fresh(receipt, association, portable, image, root, vm, kind):
    value = inventory.read_json(receipt)
    inventory.fields(value, ('schemaVersion', 'image', 'source', 'association', 'planSha256', 'buildId',
        'report', 'reportSha256', 'raw', 'rawSha256', 'lease', 'leaseSha256'))
    pair = fresh_inputs(association, portable, image, root, vm, kind)
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or value['image'] != image or value['source'] != 'work' or value['association'] != pair:
        raise ValueError('fresh acceptance does not match stopped work association')
    for name in ('report', 'raw', 'lease'):
        if value[name + 'Sha256'] != inventory.digest(inventory.read_bytes(value[name])):
            raise ValueError('fresh acceptance evidence changed: ' + name)
    lease = inventory.read_json(value['lease'])
    if (lease.get('source') != 'work' or lease.get('source_vm') != vm
            or lease.get('source_fingerprint') != pair['base'] or lease.get('image_kind') != kind
            or lease.get('vm') == vm):
        raise ValueError('fresh acceptance lease source mismatch')
    inventory.key(lease['vm'])
    document = raw_document(value['raw'])
    compare_inventory(document['inventory'], inventory.read_json(portable)['inventory'])
    report = validate_report(value['report'], portable, image, document)
    if report['planSha256'] != value['planSha256'] or report['buildId'] != value['buildId']:
        raise ValueError('fresh acceptance plan or build identity mismatch')
    if pair != fresh_inputs(association, portable, image, root, vm, kind):
        raise ValueError('work association changed during receipt verification')
    return value


def main():
    from environment import initialize, check_store_root
    initialize()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['validate', 'seal', 'verify', 'verify-fresh', 'record-image-check'])
    p.add_argument('--image', required=True)
    p.add_argument('--returncode', type=int)
    for name in ('association', 'portable', 'receipt', 'report', 'raw', 'evidence', 'name', 'script', 'image-receipt'):
        p.add_argument('--' + name)
    for name in ('root', 'vm', 'os'):
        p.add_argument('--' + name)
    args = p.parse_args()
    try:
        check_store_root(args.root)
        if args.action == 'record-image-check':
            record_image_check(args.evidence, args.image, args.name, args.script, args.returncode)
        elif args.action == 'validate':
            document = None
            if args.raw:
                document = raw_document(args.raw)
            validate_report(args.report, args.portable, args.image, document)
        elif args.action == 'seal':
            seal(args.report, args.association, args.portable, args.receipt, args.image, args.raw, args.image_receipt)
        elif args.action == 'verify-fresh':
            value = verify_fresh(args.receipt, args.association, args.portable, args.image, args.root, args.vm, args.os)
            print(value['report'])
            print(value['raw'])
        else:
            print(verify(args.receipt, args.association, args.portable, args.image))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.exit(1, 'application acceptance: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
