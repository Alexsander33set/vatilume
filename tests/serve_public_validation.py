"""Fresh synthetic UI state for public-distribution tests; no host data or keys."""
import json
import sys
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import uvicorn
import test_analysis
from device_observability.web import create_app

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='vatilume-public-ui-') as directory:
        root=Path(directory)
        test_analysis.BASE=int(time.time()*1000)-30000
        test_analysis.synthetic(root)
        path=root/'collector.toml';path.write_text('data_dir="."\n')
        app=create_app(path,token='synthetic-public-test',port=8767,
                       ai_transport=lambda *args: (_ for _ in ()).throw(AssertionError('No inference allowed')))
        uvicorn.run(app,host='127.0.0.1',port=8767,access_log=False)
