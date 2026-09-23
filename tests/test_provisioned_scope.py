"""Catalog contents do not automatically expand provisioned application acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('scope_checks',REPO/'applications/check.py')
checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)

class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.apps=self.root/'applications';self.apps.mkdir()
        shutil.copy(REPO/'applications/check.py',self.apps/'check.py')
        shutil.copy(REPO/'applications/gui.py',self.apps/'gui.py')
        source=self.root/'images/fixture/guest/40-added.sh';source.parent.mkdir(parents=True);source.write_text('# installs added\n')
        app=self.apps/'added';app.mkdir()
        (app/'manifest.json').write_text(json.dumps(dict(schemaVersion=1,id='added',inventoryIds=['pkg:added'],platforms={'linux':dict(architectures=['arm64'],executable='added',version=['--version'],launch=dict(mode='command',args=['--version']),timeoutSeconds=5,extensions=[],optional=False)})))
        self.selection=dict(schemaVersion=1,image='fixture',scope='provisioned',plans=['added'],dependencies={},provisioning={'added':dict(path='images/fixture/guest/40-added.sh',reason='Explicitly installed by provisioning.')})
        self.inventory=dict(os='linux',architecture='arm64',applications=[dict(id='pkg:added',version='1'),dict(id='pkg:os',version='2')])
        self.calls=[]
    def execute(self,argv,*args,**kwargs):
        self.calls.append(argv);return dict(status='pass',argv=argv)
    def run_plan(self):
        with patch.object(checks.shutil,'which',return_value='/fixture/added'):
            return checks.run(self.apps,self.selection,self.inventory,'attempt',self.execute,observe_native=lambda *a:self.fail('OS software must not execute a native test'))
    def test_os_inventory_is_reported_not_tested_not_passed(self):
        original=copy.deepcopy(self.inventory);report=self.run_plan()
        self.assertEqual(report['status'],'pass');self.assertEqual([r['id'] for r in report['applications']],['added'])
        self.assertEqual(report['notTestedInventoryIds'],['pkg:os']);self.assertEqual(report['unclassified'],[])
        self.assertEqual(self.inventory,original);checks.validate_results(self.apps,self.selection,self.inventory,report)
    def test_missing_selected_software_still_fails(self):
        with patch.object(checks.shutil,'which',return_value=None):
            report=checks.run(self.apps,self.selection,self.inventory,'attempt',self.execute)
        self.assertEqual(report['status'],'fail');self.assertEqual(self.calls,[])
    def test_cannot_hide_scope_or_untested_inventory(self):
        report=self.run_plan()
        for key,value in [('scope',None),('notTestedInventoryIds',[]),('applications',[])]:
            bad=copy.deepcopy(report);bad[key]=value
            with self.assertRaises(ValueError):checks.validate_results(self.apps,self.selection,self.inventory,bad)
    def test_source_references_required_and_changes_invalidate_plan(self):
        before=checks.plan_digest(self.apps,self.selection)
        (self.root/'images/fixture/guest/40-added.sh').write_text('# changed provisioning\n')
        self.assertNotEqual(checks.plan_digest(self.apps,self.selection),before)
        for change in ({'sources':['dpkg']},{'provisioning':{}},{'provisioning':{'added':dict(path='../outside',reason='bad')}}):
            with self.assertRaises(ValueError):checks.validate_selection({**self.selection,**change})
    def test_guest_home_is_not_expanded_against_validator_host(self):
        manifest=self.apps/'added/manifest.json';data=json.loads(manifest.read_text());data['platforms']['linux']['executable']='~/.local/bin/added';manifest.write_text(json.dumps(data))
        with patch.dict('os.environ',HOME='/home/guest-fixture'):
            report=self.run_plan()
        with patch.dict('os.environ',HOME='/Users/host-fixture'):
            checks.validate_results(self.apps,self.selection,self.inventory,report)
            for bad_home in (None,'relative','/','/home/../wrong','/home/other'):
                altered=copy.deepcopy(report);altered['guestHome']=bad_home
                with self.assertRaises(ValueError):checks.validate_results(self.apps,self.selection,self.inventory,altered)

    def test_os_root_alias_is_allowed_but_source_symlinks_are_not(self):
        alias=self.root/'staged-alias';alias.symlink_to(self.root,target_is_directory=True)
        self.assertEqual(checks.plan_digest(alias/'applications',self.selection),checks.plan_digest(self.apps,self.selection))
        source=self.root/'images/fixture/guest/40-added.sh'
        original=source.read_bytes();source.unlink();target=self.root/'outside.sh';target.write_bytes(original);source.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'symlink'):checks.plan_digest(self.apps,self.selection)

    def test_catalog_expansion_does_not_expand_execution(self):
        self.inventory['applications'].append(dict(id='pkg:new-os-component',version='1'))
        report=self.run_plan();self.assertEqual(len(report['applications']),1)
        self.assertEqual(report['notTestedInventoryIds'],['pkg:new-os-component','pkg:os'])
        checks.validate_results(self.apps,self.selection,self.inventory,report)

if __name__=='__main__':unittest.main()
