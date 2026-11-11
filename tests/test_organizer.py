import os,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('SLSKD_URL','http://slskd.invalid')
from app.services import organizer_service as organizer

TAGS={'artist':'Algiva','album':'Pirata de Bokita','year':'2005','track':3,'title':'Pirata de Bokita'}

class OrganizerTests(unittest.TestCase):
 def test_tags_drive_artist_album_year_structure(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);downloads=root/'downloads';inbox=downloads/'PeerFolder';inbox.mkdir(parents=True)
   source=inbox/'01 - whatever.flac';source.write_bytes(b'x'*50)
   with patch.object(organizer,'LIBRARY_ROOT',root/'library'),patch.object(organizer,'DOWNLOADS_ROOT',downloads),patch.object(organizer,'read_tags',return_value=dict(TAGS)):
    destination=organizer.organize_file(source)
   self.assertEqual(destination,root/'library'/'Algiva'/'Pirata de Bokita (2005)'/'03 - Pirata de Bokita.flac')
   self.assertTrue(destination.exists())
   self.assertFalse(inbox.exists())

 def test_same_size_destination_removes_duplicate_source(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);downloads=root/'downloads';downloads.mkdir()
   source=downloads/'dup.flac';source.write_bytes(b'x'*50)
   existing=root/'library'/'Algiva'/'Algiva - dup.flac';existing.parent.mkdir(parents=True);existing.write_bytes(b'y'*50)
   with patch.object(organizer,'LIBRARY_ROOT',root/'library'),patch.object(organizer,'DOWNLOADS_ROOT',downloads),patch.object(organizer,'read_tags',return_value={'artist':'Algiva','album':None,'year':None,'track':None,'title':'dup'}):
    destination=organizer.organize_file(source)
   self.assertEqual(destination,existing)
   self.assertFalse(source.exists())

 def test_managed_playlist_zones_are_untouched(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);downloads=root/'downloads'
   managed=downloads/'lossless'/'playlists'/'Now';managed.mkdir(parents=True)
   protected=managed/'track.flac';protected.write_bytes(b'a')
   with patch.object(organizer,'LIBRARY_ROOT',root/'library'),patch.object(organizer,'DOWNLOADS_ROOT',downloads),patch.object(organizer,'read_tags',return_value={'artist':'X','album':None,'year':None,'track':None,'title':'X'}),patch.object(organizer,'get_busy_filenames',return_value=set()):
    result=organizer.sweep_downloads()
   self.assertEqual(result['moved'],0)
   self.assertTrue(protected.exists())

 def test_busy_files_are_skipped(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);downloads=root/'downloads';downloads.mkdir()
   busy_file=downloads/'songo.flac';busy_file.write_bytes(b'a')
   old=busy_file.stat().st_mtime-1000
   os.utime(busy_file,(old,old))
   with patch.object(organizer,'LIBRARY_ROOT',root/'library'),patch.object(organizer,'DOWNLOADS_ROOT',downloads),patch.object(organizer,'read_tags',return_value={'artist':'X','album':None,'year':None,'track':None,'title':'X'}),patch.object(organizer,'get_busy_filenames',return_value={'songo.flac'}):
    result=organizer.sweep_downloads()
   self.assertEqual(result['moved'],0)
   self.assertEqual(result['skipped_busy'],1)
   self.assertTrue(busy_file.exists())

 def test_recent_files_are_left_alone(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);downloads=root/'downloads';downloads.mkdir()
   fresh=downloads/'fresh.flac';fresh.write_bytes(b'a')
   with patch.object(organizer,'LIBRARY_ROOT',root/'library'),patch.object(organizer,'DOWNLOADS_ROOT',downloads),patch.object(organizer,'read_tags',return_value={'artist':'X','album':None,'year':None,'track':None,'title':'X'}),patch.object(organizer,'get_busy_filenames',return_value=set()):
    result=organizer.sweep_downloads()
   self.assertEqual(result['moved'],0)
   self.assertTrue(fresh.exists())
