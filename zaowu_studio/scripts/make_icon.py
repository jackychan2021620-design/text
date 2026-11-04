"""Render our original SVG to a multi-resolution Windows ICO, no external assets."""
import struct
from pathlib import Path
from PySide6.QtCore import QByteArray,QBuffer,QIODevice,Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer

root=Path(__file__).resolve().parents[1]/'resources'
renderer=QSvgRenderer(str(root/'brand.svg'))
if not renderer.isValid(): raise SystemExit('Invalid brand SVG')
sizes=(16,24,32,48,64,128,256)
images=[]
for size in sizes:
    canvas=QImage(size,size,QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter=QPainter(canvas)
    renderer.render(painter)
    painter.end()
    raw=QByteArray()
    buffer=QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert canvas.save(buffer,'PNG')
    images.append(bytes(raw))
    if size==256: canvas.save(str(root/'brand.png'))
offset=6+16*len(sizes)
headers=[]
for size,png in zip(sizes,images):
    headers.append(struct.pack('<BBBBHHII',0 if size==256 else size,0 if size==256 else size,0,0,1,32,len(png),offset))
    offset+=len(png)
(root/'brand.ico').write_bytes(struct.pack('<HHH',0,1,len(sizes))+b''.join(headers)+b''.join(images))
print('Generated original brand.png and seven-resolution brand.ico')
