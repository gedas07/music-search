import os,unittest,tempfile
from pathlib import Path
os.environ.update({'SLSKD_URL':'http://slskd.invalid','TELEGRAM_BOT_TOKEN':'123:test','YOUTUBE_API_KEY':'test'})
from app.services import duplicates_service as dups
from app.services import manual_playlist_service as manual

class DuplicatesCleanupTests(unittest.TestCase):
 def test_find_duplicates_groups_similar_and_keeps_best_first(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);library=root/'library';library.mkdir()
   (library/'Artist - Track.flac').write_bytes(b'a'*500)
   (library/'artist - track.mp3').write_bytes(b'b'*100)
   (library/'artist - track (1).mp3').write_bytes(b'c'*90)
   (library/'Other - Song.mp3').write_bytes(b'd'*10)
   with patch_roots(root):
    groups=dups.find_duplicates()
   self.assertEqual(len(groups),1)
   files=groups[0]['files']
   self.assertEqual(len(files),3)
   self.assertEqual(files[0]['name'],'Artist - Track.flac')
   self.assertTrue(files[0]['is_best'])
   self.assertFalse(files[1]['is_best'])

 def test_delete_paths_rejects_outside_and_deletes_inside(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);library=root/'library';library.mkdir();outside=root/'outside';outside.mkdir()
   target=library/'x.mp3';target.write_bytes(b'a')
   outsider=outside/'y.mp3';outsider.write_bytes(b'b')
   with patch_roots(root):
    result=dups.delete_paths([str(target),str(outside)])
   self.assertEqual(result[0]['status'],'deleted')
   self.assertFalse(target.exists())
   self.assertEqual(result[1]['status'],'rejected')
   self.assertTrue(outsider.exists())

 def test_prune_removes_missing_entries_keeps_good_ones(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);library=root/'library';library.mkdir();playlists=library/'PLAYLISTS';playlists.mkdir()
   good=library/'keep.flac';good.write_bytes(b'a')
   (playlists/'My List.m3u').write_text('../keep.flac\n../gone.flac\n',encoding='utf-8')
   with patch_roots(root):
    result=dups.prune_playlist('My List')
   self.assertEqual(result['status'],'pruned')
   self.assertEqual(result['removed'],1)
   content=(playlists/'My List.m3u').read_text(encoding='utf-8')
   self.assertIn('../keep.flac',content)
   self.assertNotIn('gone.flac',content)

 def test_orphan_report_scans_whole_library(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);library=root/'library';library.mkdir()
   nested=library/'listas antiguas';nested.mkdir()
   good=library/'ok.flac';good.write_bytes(b'a')
   (nested/'Otra.m3u').write_text('../ok.flac\n../missing.flac\n',encoding='utf-8')
   with _RootsPatch(root):
    reports=dups.playlist_orphans_report()
   self.assertEqual(len(reports),1)
   self.assertEqual(reports[0]['name'],'Otra')
   self.assertEqual(reports[0]['missing'],1)

 def test_delete_playlist_removes_m3u_anywhere_in_library(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);library=root/'library';library.mkdir()
   nested=library/'otra carpeta';nested.mkdir()
   target=nested/'Mix.m3u';target.write_text('../a.flac\n',encoding='utf-8')
   with _RootsPatch(root):
    result=dups.delete_playlist('Mix')
   self.assertEqual(result['status'],'deleted')
   self.assertFalse(target.exists())

 def test_prune_deletes_playlist_when_empty_and_requested(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);library=root/'library';library.mkdir();playlists=library/'PLAYLISTS';playlists.mkdir()
   (playlists/'Empty.m3u').write_text('../gone1.flac\n../gone2.flac\n',encoding='utf-8')
   with patch_roots(root):
    result=dups.prune_playlist('Empty',delete_if_empty=True)
   self.assertEqual(result['status'],'deleted')
   self.assertFalse((playlists/'Empty.m3u').exists())

class _RootsPatch:
 def __init__(self,root):
  import unittest.mock as mock
  library=root/'library'
  self.cms=[
   mock.patch.multiple(
    dups,
    LIBRARY_ROOT=library,
    DOWNLOADS_ROOT=root/'downloads',
   ),
   mock.patch.multiple(
    manual,
    LIBRARY_ROOT=library,
    DOWNLOADS_ROOT=root/'downloads',
    PLAYLISTS_ROOT=library/'PLAYLISTS',
   ),
  ]
 def __enter__(self):
  for cm in self.cms:cm.__enter__()
  return self
 def __exit__(self,*args):
  for cm in reversed(self.cms):cm.__exit__(*args)

def patch_roots(root):
 return _RootsPatch(root)
