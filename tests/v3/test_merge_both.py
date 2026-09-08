import json
import sqlite3

from tests.v3 import test_merge_driver
from storyteller.domain.merge_conflicts import MergeConflictService
from storyteller.domain.uow import UnitOfWork
from storyteller.merge_driver import build_merge
from storyteller.storage.connection import Database


class KeepBothTests(test_merge_driver.MergeDriverTests):
    def merge(self):
        return build_merge(self.base_root / 'story.db', self.ours_root / 'story.db', self.theirs_root / 'story.db', self.result_root / 'story.db')

    def test_plot_versions_preview_and_undo(self):
        for root, summary in ((self.ours_root, '当前版本'), (self.theirs_root, '远程版本')):
            self.update(root / 'story.db', "UPDATE plots SET summary=? WHERE entity_id='plot:1'", (summary,), 'plot:1')
        _, session = self.merge()
        database = Database(self.result_root)
        service = MergeConflictService(database, 'demo')
        item = next(i for i in service.current()['items'] if i['entityId'] == 'plot:1')
        self.assertTrue(item['keepBothAllowed'])
        choices = {f['name']: {'choice': 'both'} for f in item['fields']}
        service.save(item['id'], choices)
        with self.assertRaisesRegex(Exception, '预览'):
            service.finalize(session)
        preview = service.preview(session)
        duplicate = preview['copies'][0]['newEntityId']
        self.assertTrue(any(c['entityId'] == duplicate and c['before'] is None for c in preview['chapters']))
        with self.assertRaisesRegex(Exception, '预览'):
            service.finalize(session, 'stale')
        service = MergeConflictService(database, 'demo')
        result = service.finalize(session, preview['token'])
        with database.read() as c:
            self.assertEqual('当前版本', c.execute("SELECT summary FROM plots WHERE entity_id='plot:1'").fetchone()[0])
            self.assertEqual('远程版本', c.execute('SELECT summary FROM plots WHERE entity_id=?', (duplicate,)).fetchone()[0])
            ordered = [r[0] for r in c.execute('SELECT entity_id FROM active_plots ORDER BY sort_key')]
            self.assertEqual(ordered.index('plot:1') + 1, ordered.index(duplicate))
            numbers = [r[0] for r in c.execute('SELECT chapter_number FROM active_plots') if r[0] is not None]
            self.assertEqual(len(numbers), len(set(numbers)))
        with self.assertRaisesRegex(Exception, '不存在'):
            service.finalize(session, preview['token'])
        UnitOfWork(database, 'demo').undo(result.operation_id, result.project_revision)
        with database.read() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM entities WHERE id=?', (duplicate,)).fetchone())

    def add_fragment(self, root, title, body):
        with sqlite3.connect(root / 'story.db') as c:
            c.execute("INSERT INTO entities(id,project_id,kind,stable_id,title,created_at,updated_at,extra_json) VALUES('fragment:999','demo','fragment','999',?,1,1,?)", (title, '{"fragmentType":"chapter","custom":"preserved"}'))
            c.execute("INSERT INTO fragments(entity_id,body_markdown) VALUES('fragment:999',?)", (body,))
            c.execute("INSERT INTO fragment_tags(fragment_id,tag) VALUES('fragment:999',?)", (title,))
            c.execute("INSERT INTO entity_references(source_entity_id,target_entity_id,marker) VALUES('fragment:999','character:1','character:1')")

    def test_independent_fragments_auto_keep_both_with_metadata(self):
        self.add_fragment(self.ours_root, '海滩', '本地正文')
        self.add_fragment(self.theirs_root, '独享', '远程正文')
        count, session = self.merge()
        self.assertEqual(0, count)
        self.assertIsNone(session)
        with Database(self.result_root).read() as c:
            found = list(c.execute("SELECT e.id,e.extra_json,f.body_markdown FROM entities e JOIN fragments f ON e.id=f.entity_id WHERE title IN ('海滩','独享')"))
            self.assertEqual(2, len(found))
            self.assertEqual({'本地正文', '远程正文'}, {r['body_markdown'] for r in found})
            for row in found:
                self.assertEqual('preserved', json.loads(row['extra_json'])['custom'])
                self.assertEqual(1, c.execute('SELECT COUNT(*) FROM fragment_tags WHERE fragment_id=?', (row['id'],)).fetchone()[0])
                self.assertEqual(1, c.execute('SELECT COUNT(*) FROM entity_references WHERE source_entity_id=?', (row['id'],)).fetchone()[0])

    def test_same_fragment_two_versions_remain_distinct(self):
        for root in (self.base_root, self.ours_root, self.theirs_root):
            self.add_fragment(root, '同一碎片', '共同正文')
        for root, body in ((self.ours_root, '本地改稿'), (self.theirs_root, '远程改稿')):
            self.update(root / 'story.db', "UPDATE fragments SET body_markdown=? WHERE entity_id='fragment:999'", (body,), 'fragment:999')
        count, session = self.merge()
        self.assertGreater(count, 0)
        database = Database(self.result_root)
        service = MergeConflictService(database, 'demo')
        item = next(i for i in service.current()['items'] if i['entityId'] == 'fragment:999')
        self.assertTrue(item['keepBothAllowed'])
        service.save(item['id'], {f['name']: {'choice': 'both'} for f in item['fields']})
        preview = service.preview(session)
        service.finalize(session, preview['token'])
        with database.read() as c:
            versions = list(c.execute("SELECT e.title,f.body_markdown FROM entities e JOIN fragments f ON e.id=f.entity_id WHERE e.title LIKE '同一碎片%'"))
            self.assertEqual({'本地改稿', '远程改稿'}, {r['body_markdown'] for r in versions})
            self.assertEqual(2, len(versions))

    def test_both_keeps_side_specific_tags_extensions_and_assets(self):
        import hashlib
        for root in (self.base_root, self.ours_root, self.theirs_root):
            self.add_fragment(root, '同名碎片', '初稿')
        for root, body, tag in ((self.ours_root, '本地正文', '本地标签'), (self.theirs_root, '远程正文', '远程标签')):
            self.update(root / 'story.db', "UPDATE fragments SET body_markdown=? WHERE entity_id='fragment:999'", (body,), 'fragment:999')
            with sqlite3.connect(root / 'story.db') as c:
                c.execute("UPDATE fragment_tags SET tag=? WHERE fragment_id='fragment:999'", (tag,))
                c.execute("UPDATE entities SET extra_json=? WHERE id='fragment:999'", (json.dumps({'fragmentType':'chapter', 'custom':tag}),))
                data = body.encode()
                c.execute("INSERT INTO assets(id,project_id,entity_id,filename,media_type,content,content_hash,created_at) VALUES('same-asset','demo','fragment:999','note.txt','text/plain',?,?,1)", (data, hashlib.sha256(data).hexdigest()))
        _, session = self.merge()
        database = Database(self.result_root)
        service = MergeConflictService(database, 'demo')
        eligible = next(i for i in service.current()['items'] if i['keepBothAllowed'])
        service.save(eligible['id'], {f['name']: {'choice':'both'} for f in eligible['fields']})
        status = service.current()
        self.assertEqual(status['session']['totalFields'], status['session']['resolvedFields'])
        preview = service.preview(session)
        service.finalize(session, preview['token'])
        duplicate = preview['copies'][0]['newEntityId']
        with database.read() as c:
            for identifier, tag, body in (('fragment:999', '本地标签', '本地正文'), (duplicate, '远程标签', '远程正文')):
                self.assertEqual(tag, c.execute('SELECT tag FROM fragment_tags WHERE fragment_id=?', (identifier,)).fetchone()[0])
                self.assertEqual(tag, json.loads(c.execute('SELECT extra_json FROM entities WHERE id=?', (identifier,)).fetchone()[0])['custom'])
                self.assertEqual(body.encode(), c.execute('SELECT content FROM assets WHERE entity_id=?', (identifier,)).fetchone()[0])
            self.assertEqual(2, c.execute('SELECT COUNT(DISTINCT filename) FROM assets').fetchone()[0])

    def test_legacy_row_conflict_does_not_advertise_unsafe_both(self):
        for root, summary in ((self.ours_root, 'A'), (self.theirs_root, 'B')):
            self.update(root / 'story.db', "UPDATE plots SET summary=? WHERE entity_id='plot:1'", (summary,), 'plot:1')
        self.merge()
        database = Database(self.result_root)
        with database.write() as c:
            c.execute("UPDATE merge_conflicts SET resolution_json='{}'")
        service = MergeConflictService(database, 'demo')
        item = service.current()['items'][0]
        self.assertFalse(item['keepBothAllowed'])
        with self.assertRaisesRegex(Exception, '完整'):
            service.save(item['id'], {f['name']: {'choice':'both'} for f in item['fields']})

    def test_api_preview_token_expiry_and_export_readback(self):
        from fastapi.testclient import TestClient
        from storyteller.app import create_app
        from storyteller.settings import Settings
        for root, summary in ((self.ours_root, 'API 本地'), (self.theirs_root, 'API 远程')):
            self.update(root / 'story.db', "UPDATE plots SET summary=? WHERE entity_id='plot:1'", (summary,), 'plot:1')
        _, session = self.merge()
        settings = Settings.create(self.result_root, content_root=self.result_root.parent, default_project='demo')
        with TestClient(create_app(settings)) as client:
            meta = client.get('/api/v1/meta?project=demo').json()
            headers = {'X-Story-Teller-Token':meta['mutationToken']}
            item = client.get('/api/v1/projects/demo/merge-conflicts').json()['items'][0]
            path = '/api/v1/projects/demo/merge-conflicts/' + item['id']
            payload = {'resolutions':{f['name']:{'choice':'both'} for f in item['fields']}}
            self.assertEqual(403, client.put(path, json=payload).status_code)
            self.assertEqual(200, client.put(path, json=payload, headers=headers).status_code)
            preview_path = '/api/v1/projects/demo/merge-conflicts/' + session
            preview = client.get(preview_path+'/preview').json()
            self.assertEqual(409, client.post(preview_path+'/finalize', json={'previewToken':'stale'}, headers=headers).status_code)
            result = client.post(preview_path+'/finalize', json={'previewToken':preview['token']}, headers=headers)
            self.assertEqual(200, result.status_code, result.text)
            self.assertFalse(client.get('/api/v1/meta?project=demo').json()['mergeRequired'])
            duplicate = preview['copies'][0]['newEntityId']
            self.assertEqual('API 远程', client.get('/api/v1/projects/demo/entities/'+duplicate).json()['data']['summary'])
        with Database(self.result_root).read() as c:
            self.assertEqual('API 远程', c.execute('SELECT summary FROM plots WHERE entity_id=?',(duplicate,)).fetchone()[0])
        exported = json.loads((self.result_root/'project.snapshot.json').read_text())
        self.assertTrue(any(p['entityId']==duplicate and p['summary']=='API 远程' for p in exported['plots']))

    def test_independent_children_in_shared_line_get_distinct_numbers(self):
        for root in (self.base_root, self.ours_root, self.theirs_root):
            with sqlite3.connect(root/'story.db') as c:
                c.execute("INSERT INTO entities(id,project_id,kind,stable_id,title,created_at,updated_at,extra_json) VALUES('fragment:line','demo','fragment','line','共同剧情线',1,1,?)", ('{"fragmentType":"line"}',))
                c.execute("INSERT INTO fragments(entity_id) VALUES('fragment:line')")
        self.add_fragment(self.ours_root, '子章本地', '本地')
        self.add_fragment(self.theirs_root, '子章远程', '远程')
        for root in (self.ours_root, self.theirs_root):
            with sqlite3.connect(root/'story.db') as c:
                c.execute("UPDATE entities SET extra_json=? WHERE id='fragment:999'", ('{"fragmentType":"chapter","parentFragmentId":"fragment:line","chapterNumber":1,"fragmentOrder":0}',))
        count, session = self.merge()
        self.assertEqual(0, count)
        with Database(self.result_root).read() as c:
            children = [json.loads(r[0]) for r in c.execute("SELECT extra_json FROM entities WHERE title LIKE '子章%'")]
            self.assertEqual({1,2}, {r['chapterNumber'] for r in children})
            self.assertEqual({0,1}, {r['fragmentOrder'] for r in children})


    def test_changed_choices_invalidate_real_preview_even_when_both_is_cancelled(self):
        for root, summary in ((self.ours_root, '本地'), (self.theirs_root, '远程')):
            self.update(root / 'story.db', "UPDATE plots SET summary=? WHERE entity_id='plot:1'", (summary,), 'plot:1')
        _, session = self.merge()
        service = MergeConflictService(Database(self.result_root), 'demo')
        item = service.current()['items'][0]
        service.save(item['id'], {f['name']:{'choice':'both'} for f in item['fields']})
        preview = service.preview(session)
        service.save(item['id'], {f['name']:{'choice':'ours'} for f in item['fields']})
        with self.assertRaisesRegex(Exception, '预览'):
            service.finalize(session, preview['token'])
        self.assertTrue(service.current()['required'])

    def test_same_named_independent_fragments_get_distinct_export_names(self):
        self.add_fragment(self.ours_root, '同名', '正文一')
        self.add_fragment(self.theirs_root, '同名', '正文二')
        self.assertEqual(0, self.merge()[0])
        with Database(self.result_root).read() as c:
            titles = [r[0] for r in c.execute("SELECT title FROM entities WHERE title LIKE '同名%'")]
            self.assertEqual({'同名', '同名（远程版本）'}, set(titles))

    def test_invalid_reference_prevents_preview_and_preserves_database(self):
        from storyteller.domain.merge_entities import VERSIONS
        for root, summary in ((self.ours_root, '本地'), (self.theirs_root, '远程')):
            self.update(root / 'story.db', "UPDATE plots SET summary=? WHERE entity_id='plot:1'", (summary,), 'plot:1')
        _, session = self.merge()
        database = Database(self.result_root)
        with database.write() as c:
            row = c.execute('SELECT id,resolution_json FROM merge_conflicts LIMIT 1').fetchone()
            saved = json.loads(row['resolution_json'])
            for item in saved[VERSIONS]['theirs']:
                if item['table'] == 'plot_characters':
                    item['row']['character_id'] = 'character:missing'
                    item['key']['character_id'] = 'character:missing'
                    break
            c.execute('UPDATE merge_conflicts SET resolution_json=? WHERE id=?', (json.dumps(saved), row['id']))
        service = MergeConflictService(database, 'demo')
        item = service.current()['items'][0]
        service.save(item['id'], {f['name']:{'choice':'both'} for f in item['fields']})
        with database.read() as c:
            count = c.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
        with self.assertRaisesRegex(Exception, '引用|关系'):
            service.preview(session)
        with database.read() as c:
            self.assertEqual(count, c.execute('SELECT COUNT(*) FROM entities').fetchone()[0])
            self.assertEqual([], c.execute('PRAGMA foreign_key_check').fetchall())
        self.assertTrue(service.current()['required'])

    def test_fragment_copies_keep_each_sides_parent_line(self):
        for root in (self.base_root, self.ours_root, self.theirs_root):
            self.add_fragment(root, '改稿', '初稿')
            with sqlite3.connect(root/'story.db') as c:
                for name in ('a','b'):
                    c.execute("INSERT INTO entities(id,project_id,kind,stable_id,title,created_at,updated_at,extra_json) VALUES(?,'demo','fragment',?,?,1,1,?)", ('fragment:'+name,name,name,'{"fragmentType":"line"}'))
                    c.execute('INSERT INTO fragments(entity_id) VALUES(?)',('fragment:'+name,))
        for root, parent, body in ((self.ours_root,'a','本地改稿'),(self.theirs_root,'b','远程改稿')):
            self.update(root/'story.db', "UPDATE fragments SET body_markdown=? WHERE entity_id='fragment:999'", (body,), 'fragment:999')
            with sqlite3.connect(root/'story.db') as c:
                c.execute("UPDATE entities SET extra_json=? WHERE id='fragment:999'", (json.dumps({'fragmentType':'chapter','parentFragmentId':'fragment:'+parent,'chapterNumber':1,'fragmentOrder':0}),))
        _, session = self.merge()
        database = Database(self.result_root)
        service = MergeConflictService(database,'demo')
        item = next(i for i in service.current()['items'] if i['keepBothAllowed'])
        service.save(item['id'],{f['name']:{'choice':'both'} for f in item['fields']})
        preview = service.preview(session)
        service.finalize(session,preview['token'])
        with database.read() as c:
            for identifier,parent in (('fragment:999','fragment:a'),(preview['copies'][0]['newEntityId'],'fragment:b')):
                extra = json.loads(c.execute('SELECT extra_json FROM entities WHERE id=?',(identifier,)).fetchone()[0])
                self.assertEqual(parent,extra['parentFragmentId'])
