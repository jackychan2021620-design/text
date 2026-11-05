"""Fetch pinned official language models over verified TLS and verify SHA256."""
import hashlib
from pathlib import Path
import requests
HASHES={'chi_sim':'a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730','eng':'7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'}
def main():
    root=Path(__file__).resolve().parents[1]/'.ocr'/'tessdata';root.mkdir(parents=True,exist_ok=True)
    for lang,digest in HASHES.items():
        path=root/(lang+'.traineddata')
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:continue
        r=requests.get('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/'+path.name,timeout=(10,60));r.raise_for_status()
        if hashlib.sha256(r.content).hexdigest()!=digest:raise ValueError('OCR模型校验失败')
        path.write_bytes(r.content)
    print('中文与英文OCR模型已校验。仍需安装Tesseract可执行程序。')
if __name__=='__main__':main()
