"""Decode user images through Qt before passing a normalized PNG to native tools."""
from pathlib import Path
from PySide6.QtCore import QByteArray,QBuffer,QIODevice,Qt
from PySide6.QtGui import QImage,QImageReader,QPainter,QColor

def read_image(path):
    reader=QImageReader(str(path));reader.setAutoTransform(True);reader.setDecideFormatFromContent(True)
    size=reader.size()
    if size.isValid() and size.width()*size.height()>40000000:raise ValueError('图片过大，请截取数据区域后重试（最多4000万像素）')
    image=reader.read()
    if image.isNull():raise ValueError('无法解码图片：'+reader.errorString()+'；请重新导出为PNG或JPG')
    if image.hasAlphaChannel():
        white=QImage(image.size(),QImage.Format.Format_RGB32);white.fill(QColor('white'))
        p=QPainter(white);p.drawImage(0,0,image);p.end();image=white
    return image

def png_bytes(image):
    data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer,'PNG'):raise ValueError('无法转换OCR输入图片为PNG')
    buffer.close();return bytes(data)

def image_tiles(image):
    # Mobile screenshots contain small text and several unrelated panels. OCR
    # overlapping sections instead of forcing the whole page into one text block.
    width=image.width();height=image.height();scale=min(3,1200/width) if width<800 else 1
    tile_height=min(height,max(600,int(1800/scale)))
    overlap=min(120,tile_height//5);step=max(1,tile_height-overlap)
    for index,top in enumerate(range(0,height,step)):
        tile=image.copy(0,top,width,min(tile_height,height-top))
        if scale!=1:tile=tile.scaledToWidth(round(width*scale),Qt.TransformationMode.SmoothTransformation)
        yield index,top,tile.width()/width,tile
        if top+tile_height>=height:break
