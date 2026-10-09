"""Parallel orthographic stereo with horizontal depth shear about camera center."""
import numpy as np


def eye_pixels(projected, scale, width, height, pan, strength, eye):
    if not np.isfinite(strength) or not 0 <= strength <= 6:
        raise ValueError('Stereo depth must be between 0 and 6 degrees.')
    q=np.asarray(projected)
    xy=q[:,:2].copy()
    # Positive depth faces the viewer: near points have crossed disparity.
    xy[:,0]+=eye*np.tan(np.deg2rad(strength/2))*q[:,2]
    return xy*[scale,-scale]+[width/2,height/2]+pan


def render(projected, rgb, scale, width, height, pan, strength, swap=False, overlays=(), linework=()):
    """Independent eye depth buffers; grayscale avoids class-color suppression."""
    from PIL import Image, ImageDraw
    q=np.asarray(projected)
    luminance=np.clip(np.asarray(rgb) @ np.array([.299,.587,.114]),0,255).astype(np.uint8)
    eyes=[]
    for eye in (1,-1):
        xy=np.rint(eye_pixels(q,scale,width,height,pan,strength,eye)).astype(np.int64)
        keep=(xy[:,0]>=0)&(xy[:,0]<width)&(xy[:,1]>=0)&(xy[:,1]<height)
        ids=np.flatnonzero(keep)
        ids=ids[np.argsort(q[ids,2],kind='stable')]
        p=xy[ids];key=p[:,1]*width+p[:,0]
        _,rev=np.unique(key[::-1],return_index=True)
        take=len(key)-1-rev
        pixels=np.full((height,width),20,dtype=np.uint8)
        pixels[p[take,1],p[take,0]]=luminance[ids[take]]
        image=Image.fromarray(pixels);draw=ImageDraw.Draw(image)
        for points,line_width,vertices in overlays:
            coords=eye_pixels(points,scale,width,height,pan,strength,eye)
            if len(coords)>1 and line_width>0:draw.line([tuple(p) for p in coords],fill=240,width=line_width)
            if vertices or len(coords)==1:
                for x,y in coords:draw.ellipse((x-2,y-2,x+2,y+2),fill=240)
        pixels=np.array(image)
        if linework:
            from pyargus.linework import paint
            gray=[(points,int(np.dot(color,[.299,.587,.114])),width,top) for points,color,width,top in linework]
            paint(pixels,q,gray,scale,pan,strength,eye)
        eyes.append(pixels)
    if swap:eyes.reverse()
    return np.stack((eyes[0],eyes[1],eyes[1]),axis=2)
