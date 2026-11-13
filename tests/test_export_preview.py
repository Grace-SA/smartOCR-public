"""A preview must describe the records actually exported, including concurrent edits."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import app


class ExportPreviewTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{'id':'synthetic-a','merchant':'Example Shop','date':'2026-01-02','total':12.5,
                    'currency':'AUD','category':'Other','purpose':'unknown','tags':[], 'notes':'', 'status':'review'}]
        self.server=ThreadingHTTPServer(('127.0.0.1',0), app.Handler)
        self.port=self.server.server_address[1]
        self.patches=[patch.object(app,'PORT',self.port),patch.object(app,'records',lambda:self.rows),patch.object(app,'create_export')]
        for p in self.patches:p.start()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        for p in reversed(self.patches):p.stop()

    def post(self, body):
        client=http.client.HTTPConnection('127.0.0.1',self.port)
        client.request('POST','/api/export',json.dumps(body),{'Content-Type':'application/json'})
        response=client.getresponse();status=response.status;result=json.loads(response.read());client.close()
        return status,result

    def test_matching_preview_exports(self):
        status,_=self.post({'ids':['synthetic-a'],'format':'csv','expected_records':self.rows})
        self.assertEqual(status,200);app.create_export.assert_called_once()

    def test_changed_amount_rejects_without_creating_export(self):
        before=json.loads(json.dumps(self.rows));self.rows[0]['total']=99
        status,result=self.post({'ids':['synthetic-a'],'format':'pdf','expected_records':before})
        self.assertEqual(status,409);self.assertIn('changed',result['error']);app.create_export.assert_not_called()

    def test_changed_metadata_also_rejects(self):
        before=json.loads(json.dumps(self.rows));self.rows[0]['tags']=['updated']
        self.assertEqual(self.post({'ids':['synthetic-a'],'format':'xlsx','expected_records':before})[0],409)
        app.create_export.assert_not_called()

    def test_malformed_preview_rejected(self):
        self.assertEqual(self.post({'ids':['synthetic-a'],'format':'json','expected_records':['bad']})[0],400)
        app.create_export.assert_not_called()


if __name__ == '__main__':unittest.main()
