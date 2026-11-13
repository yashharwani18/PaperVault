"""Ordinary MuPDF grid accounting for positive uniform-scale research crops.

No OCR/model/renderer working-memory bound. Coordinates must already be in the
render call's coordinate frame. An omitted page box gives an unclipped charge;
it does not certify that any observation support lies on a real page.
"""
import math

import pymupdf


def raster_cost(rect,scale,*,page_rect=None):
    if len(rect)!=4 or not all(math.isfinite(x) for x in rect) or rect[2]<=rect[0] or rect[3]<=rect[1]:
        raise ValueError('Invalid crop rectangle')
    if not math.isfinite(scale) or scale<=0:raise ValueError('Invalid raster scale')
    crop=pymupdf.Rect(rect)
    if page_rect is not None:
        crop &= pymupdf.Rect(page_rect)
    if crop.is_empty:
        return dict(width=0,height=0,pixels=0,bounds=None)
    transformed=crop*pymupdf.Matrix(scale,scale)
    if not all(math.isfinite(x) for x in transformed) or transformed.is_infinite:
        raise ValueError('Crop transform exceeds supported coordinates')
    # MuPDF rounds the transformed bounding rectangle onto its integer grid,
    # including its tolerance near integer boundaries. ceil(width) is insufficient.
    bounds=transformed.irect
    width,height=max(0,bounds.width),max(0,bounds.height)
    return dict(width=width,height=height,pixels=width*height,bounds=list(bounds))


def raster_pixels(rect,scale):
    return raster_cost(rect,scale)['pixels']
