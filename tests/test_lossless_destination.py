import os,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('SLSKD_URL','http://slskd.invalid')
from app import monitor
from app.services import organizer_service as organizer

class DestinationTests(unittest.TestCase):
 def test_move_single_download_organizes_into_library_by_artist(self):
  for suffix in ('.flac','.wav','.WAV','.alac','.aiff','.mp3','.m4a'):
   with self.subTest(suffix=suffix),tempfile.TemporaryDirectory() as temp:
    root=Path(temp);inbox=root/'downloads'/'inbox';inbox.mkdir(parents=True);source=inbox/('original'+suffix);source.write_bytes(b'unchanged audio bytes')
    with patch.object(monitor,'DOWNLOADS_ROOT',root/'downloads'),patch.object(organizer,'DOWNLOADS_ROOT',root/'downloads'),patch.object(organizer,'LIBRARY_ROOT',root/'library'):
     actual=monitor.move_single_download(source,'Fisher','Losing It')
    self.assertEqual(actual,root/'library'/'Fisher'/('Fisher - Losing It'+suffix.lower()))
    self.assertEqual(actual.read_bytes(),b'unchanged audio bytes')
    self.assertFalse(source.exists())
    self.assertFalse(inbox.exists())
