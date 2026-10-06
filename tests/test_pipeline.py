"""Synthetic regressions for policy, import identity, and transactional reporting."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import trends
from trendlib import importer
from trendlib.classifier import classify_market
from trendlib.profiles import Profile, load_profile


def payload(path):
    return json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>', path.read_text(), re.S)[1])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'dataset'
        self.profile = load_profile()

    def preview(self, ios=(), android=(), cs=(), profile=None):
        with contextlib.redirect_stdout(io.StringIO()):
            trends.preview(self.directory, profile or self.profile, ios, android, cs)
        return trends.read_json(self.directory / 'preview.json')

    def apply(self, profile=None):
        with contextlib.redirect_stdout(io.StringIO()):
            trends.apply(self.directory, profile or self.profile)
        return trends.read_json(self.directory / 'history.json')

    def csv(self, rows, name='input.csv'):
        path = Path(self.temp.name) / name
        with path.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['comment_date', 'star', 'content', 'author']); w.writerows(rows)
        return path

    def test_default_history_repeat_increment_and_report(self):
        args = ([ROOT/'examples/media-ios.csv'], [ROOT/'examples/media-OPPO.csv'], [ROOT/'examples/support.csv'])
        plan = self.preview(*args)
        self.assertEqual((len(plan['new_market']), len(plan['new_cs'])), (72, 12))
        data = self.apply()
        report = self.directory/data['report']/'report.html'
        d = payload(report)
        self.assertEqual(d['topics'], ['播放', '风控', '广告', '下载', '网页浏览与搜索'])
        self.assertEqual(d['baseline']['monthly']['ios'] + d['baseline']['monthly']['and'], 72)
        self.assertEqual(len(d['monthly']['双端汇总']['播放']), 4)
        self.assertEqual(d['cs']['total'], 12)
        published = payload(ROOT/'docs/demo/report.html')
        published.pop('datasetId')
        generated = dict(d)
        generated.pop('datasetId')
        self.assertEqual(published, generated)
        for name in ('details.js', 'details_cs.js'):
            self.assertEqual((report.parent/'assets'/name).read_bytes(),
                             (ROOT/'docs/demo/assets'/name).read_bytes())
        before = (self.directory/'history.json').read_bytes()
        again = self.preview(*args)
        self.assertEqual((again['new_market'], again['new_cs']), ([], []))
        self.apply()
        self.assertEqual((self.directory/'history.json').read_bytes(), before)
        new = self.csv([['2025-05-01', 2, '视频无法播放', 'synthetic-new']])
        self.preview([new]); after = self.apply()
        self.assertEqual(after['market'][:-1], data['market'])
        self.assertEqual(after['cs'], data['cs'])
        self.assertEqual(after['market'][-1]['record_id'], 'R000073')
        self.assertEqual(after['revision'], 2)
        self.assertTrue(report.exists())

    def test_custom_simple_topics_reach_dashboard(self):
        p = load_profile(ROOT/'profiles/commerce.json')
        self.preview([ROOT/'examples/commerce.csv'], profile=p)
        data = self.apply(p)
        d = payload(self.directory/data['report']/'report.html')
        self.assertEqual(d['topics'], ['支付', '物流', '性能'])
        overview = d['overview']['monthly']['双端汇总']
        self.assertEqual(overview['支付']['total'], 27)
        self.assertEqual(overview['支付']['rel'], 6)
        self.assertEqual(overview['支付']['neg'], 3)
        self.assertAlmostEqual(overview['支付']['negRate'], 3/27)
        self.assertEqual(overview['物流']['rel'], 6)
        self.assertEqual(overview['性能']['rel'], 6)
        self.assertEqual(d['cs']['total'], 0)
        self.assertEqual(d['overview']['monthly']['AND']['支付']['total'], 0)
        before = (self.directory/'history.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Profile changed'):
            self.preview([ROOT/'examples/commerce.csv'])
        self.assertEqual((self.directory/'history.json').read_bytes(), before)

    def test_shared_cases_and_mixed_matchers(self):
        cases = trends.read_json(ROOT/'tests/semantic_cases.json')['cases']
        for case in cases:
            result = classify_market({'comment_text': case['text'], 'star': case['rating']}, self.profile)
            self.assertEqual(result['final_topics'], case['topic_matches'], case['id'])
        mixed = Profile({'schema_version': 1, 'id':'mixed', 'topics':[
            {'key':'payment','name':'Payment','keywords':['pay'],'requires':['order'],'excludes':['demo'],'order':2},
            {'key':'player','name':'Player','matcher':'builtin','builtin':'播放','order':1}]})
        self.assertEqual(mixed.names, ['Player','Payment'])
        self.assertEqual(classify_market({'comment_text':'视频播放流畅 ORDER PAY'}, mixed)['final_topics'], ['Player','Payment'])
        self.assertFalse(mixed.judge('Payment', 'order pay demo')[0])
        self.assertFalse(mixed.judge('Payment', 'pay')[0])
        self.assertTrue(mixed.judge('Payment', 'order pay', domain='cs')[0])

    def test_multiset_and_author_duplicate_policy(self):
        row = {'platform':'IOS','and_channel':'','comment_date':'2025-01-01','star':1,'comment_text':'无法播放','author':'synthetic-a'}
        index = importer.MarketIndex('multiset'); keys = importer.market_keys(row)
        index.add(*keys, row); index.add(*keys, row)
        self.assertEqual([index.take(*keys) for _ in range(3)], ['existing','existing','new'])
        deleted = {**row, 'comment_text':'（该条评论已经被删除）无法播放'}
        self.assertTrue(importer.is_true_duplicate(row, deleted))
        self.assertFalse(importer.is_true_duplicate(row, {**deleted,'author':'synthetic-b'}))
        self.assertFalse(importer.is_true_duplicate({**row,'author':''}, {**deleted,'author':''}))
        changed = {**row,'star':2}; index = importer.MarketIndex();index.add(*keys,row)
        self.assertEqual(index.take(*importer.market_keys(changed)), 'updated')

    def test_customer_service_lossy_ambiguity_and_time_windows(self):
        old={'record_id':'CS000001','period_start':'2025-01-01','period_end':'2025-01-07',
             'cs_text_clean':'播放—失败','cs_text':'用户：播放—失败'}
        new={**old,'cs_text_clean':'播放?失败','cs_text':'用户：播放?失败','source_is_lossy_export':True}
        index=importer.CsIndex();index.add(old)
        self.assertEqual(importer.diff_cs(index,new)[0],'existing_lossy')
        index=importer.CsIndex();index.add(old);index.add({**old,'record_id':'CS000002','cs_text_clean':'播放！失败'})
        self.assertEqual(importer.diff_cs(index,new)[0],'ambiguous_lossy')
        index=importer.CsIndex();index.add(old)
        self.assertEqual(importer.diff_cs(index,{**new,'source_is_lossy_export':False})[0],'new')
        index=importer.CsIndex();index.add(old)
        later={**old,'period_start':'2025-02-01','period_end':'2025-02-07'}
        self.assertEqual(importer.diff_cs(index,later)[0],'new')

    def test_review_updates_are_not_automatically_applied(self):
        src = self.csv([['2025-01-01',1,'无法播放','synthetic-a']])
        self.preview([src]); data = self.apply(); before=(self.directory/'history.json').read_bytes()
        self.csv([['2025-01-01',5,'无法播放','synthetic-a']])
        plan=self.preview([src]); self.assertEqual(len(plan['sources']['ios']['updated']),1)
        self.apply(); self.assertEqual((self.directory/'history.json').read_bytes(),before)

    def test_report_failure_does_not_commit_or_destroy_history(self):
        src=self.csv([['2025-01-01',1,'无法播放','synthetic-a']])
        self.preview([src]); data=self.apply(); before=(self.directory/'history.json').read_bytes()
        src=self.csv([['2025-02-01',1,'无法播放','synthetic-b']])
        self.preview([src])
        with patch.object(trends,'build',side_effect=ValueError('forced failure')):
            with self.assertRaisesRegex(ValueError,'forced failure'): self.apply()
        self.assertEqual((self.directory/'history.json').read_bytes(),before)
        self.assertTrue((self.directory/data['report']/'report.html').exists())

    def test_stale_preview_is_rejected(self):
        src=self.csv([['2025-01-01',1,'无法播放','synthetic-a']])
        self.preview([src]);self.apply()
        with self.assertRaisesRegex(ValueError,'stale'): self.apply()

    def test_small_unrated_dataset_and_html_escaping(self):
        src=self.csv([['2025-01-02','','播放 </script><script>throw 1</script>','synthetic-a']])
        self.preview([src]);data=self.apply();html=self.directory/data['report']/'report.html'
        d=payload(html)
        self.assertIsNone(d['summary']['lastCompleteMonth'])
        self.assertEqual(d['star']['monthly']['scopes']['双端汇总']['stars']['unrated'],1)
        self.assertEqual(data['market'][0]['is_negative'],False)
        self.assertNotIn('</script><script>throw 1</script>',html.read_text())
        if shutil.which('node'):
            # Execute the actual shared UI predicate, not a Python imitation.
            function=re.search(r'function isNegative\(r\)\{[^}]+\}',html.read_text())[0]
            result=subprocess.check_output(['node','-e',function+'; console.log(JSON.stringify([null,1,2,3,4,5].map(s=>isNegative({s}))));'],text=True)
            self.assertEqual(json.loads(result),[False,True,True,True,False,False])

    def test_validation_dates_ratings_profile_and_headers(self):
        for row in [['bad-date',1,'播放','synthetic-a'],['2025-01-01','bad-rating','播放','synthetic-a']]:
            with self.assertRaises(ValueError): self.preview([self.csv([row])])
        malformed=copy.deepcopy(self.profile.data);malformed['topics'][0]['name']='<img>'
        with self.assertRaises(ValueError): Profile(malformed)
        malformed=copy.deepcopy(self.profile.data);malformed['topics'][1]['key']=malformed['topics'][0]['key']
        with self.assertRaises(ValueError): Profile(malformed)
        bad=Path(self.temp.name)/'bad.csv';bad.write_text('foo,bar\na,b\n')
        with self.assertRaisesRegex(ValueError,'recognizable'): self.preview([bad])

    def test_xlsx_and_tsv_imports(self):
        from openpyxl import Workbook
        path=Path(self.temp.name)/'source.xlsx'; w=Workbook()
        w.active.append(['comment_date','star','content']);w.active.append(['2025-01-01',2,'下载速度慢']);w.save(path)
        plan=self.preview([path]);self.assertEqual(plan['new_market'][0]['comment_text'],'下载速度慢')
        tsv=Path(self.temp.name)/'source.tsv';tsv.write_text('comment_date\tstar\tcontent\n2025-01-02\t5\t视频播放流畅\n')
        plan=self.preview([tsv]);self.assertEqual(plan['new_market'][0]['star'],5)

    def test_public_file_guards(self):
        from scripts import check_public
        root=Path(self.temp.name)/'public';root.mkdir()
        manifest=root/'public-files.txt'
        manifest.write_text('public-files.txt\nexample.txt\n')
        example=root/'example.txt';example.write_text('Artificial example')
        with patch.object(check_public, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()):
            check_public.check()
            unexpected=root/'extra.txt';unexpected.write_text('unlisted')
            with self.assertRaisesRegex(SystemExit, 'Allowlist mismatch'): check_public.check()
            unexpected.unlink()
            example.write_text('ghp_' + 'x' * 30)
            with self.assertRaisesRegex(SystemExit, 'Private-data marker'): check_public.check()
            example.unlink();example.symlink_to(manifest)
            with self.assertRaisesRegex(SystemExit, 'Symlink'): check_public.check()
            example.unlink();example.write_text('Artificial example')
            private=root/'classification.json';private.write_text('[]')
            manifest.write_text('public-files.txt\nexample.txt\nclassification.json\n')
            with self.assertRaisesRegex(SystemExit, 'Invalid public file'): check_public.check()


if __name__ == '__main__':
    unittest.main()
