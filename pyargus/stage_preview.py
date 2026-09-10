"""North-up display previews; no alteration of analysis or export geometry."""
import numpy as np

CLASS_STYLES = {
    0: ('Created / never classified',(155,155,155)),
    1: ('Unclassified',(195,195,195)),
    2: ('Ground',(194,143,78)),
    3: ('Low vegetation',(156,224,97)),
    4: ('Medium vegetation',(57,184,85)),
    5: ('High vegetation',(20,112,54)),
    6: ('Building',(232,82,76)),
    7: ('Low noise',(236,66,232)),
    9: ('Water',(70,157,239)),
    17: ('Bridge deck',(240,173,65)),
    18: ('High noise',(174,80,230)),
}


def class_colors(labels):
    labels = np.asarray(labels,dtype=int)
    palette = np.array([CLASS_STYLES.get(i,('Other',(130,180,205)))[1] for i in range(256)],dtype='uint8')
    return palette[np.clip(labels,0,255)]


def _frame(x,y,title):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA',(1100,850),(18,27,38,255))
    draw = ImageDraw.Draw(image)
    draw.text((20,16),title,fill='white')
    draw.text((20,38),'North up | Display preview',fill='white')
    lo=np.array([np.min(x),np.min(y)])
    span=np.array([np.ptp(x),np.ptp(y)])
    scale=min(780/max(span[0],1e-9),740/max(span[1],1e-9))
    def xy(x,y):
        return np.column_stack((30+(np.asarray(x)-lo[0])*scale,810-(np.asarray(y)-lo[1])*scale))
    return image,draw,xy


def classification(x,y,z,labels):
    image,draw,xy = _frame(x,y,'Classified point cloud')
    # Bounded display work; topmost sampled return wins at a shared pixel.
    ids=np.arange(0,len(x),max(1,int(np.ceil(len(x)/200000))))
    ids=ids[np.argsort(np.asarray(z)[ids],kind='stable')]
    positions=np.rint(xy(np.asarray(x)[ids],np.asarray(y)[ids])).astype(int)
    pixels=np.asarray(image).copy()
    key=positions[:,1]*image.width+positions[:,0]
    _,back=np.unique(key[::-1],return_index=True); take=len(key)-1-back
    pixels[positions[take,1],positions[take,0],:3]=class_colors(np.asarray(labels)[ids[take]])
    from PIL import Image,ImageDraw
    image=Image.fromarray(pixels); draw=ImageDraw.Draw(image)
    draw.text((840,64),'LAS classification',fill='white')
    for j,c in enumerate(np.unique(labels)):
        name,color=CLASS_STYLES.get(int(c),('Other',(130,180,205)))
        row=88+j*23
        if row>775:
            draw.text((840,row),'Additional classes present',fill='white'); break
        draw.rectangle((840,row,850,row+10),fill=color)
        draw.text((858,row),f'{c}: {name}',fill='white')
    draw.text((20,828),f'{len(ids):,} sampled / {len(x):,} points. Preview sampling does not change output.',fill='white')
    return np.asarray(image).copy()


def contours(lines,breaks=()):
    allxy=np.concatenate([line.xy for line in lines])
    image,draw,xy=_frame(allxy[:,0],allxy[:,1],'Generated contours')
    for line in lines:
        coords=xy(line.xy[:,0],line.xy[:,1])
        draw.line([tuple(p) for p in coords],fill=(255,187,82) if line.is_index else (109,185,204),width=2 if line.is_index else 1)
    for b in breaks:
        draw.line([tuple(p) for p in xy(b[:,0],b[:,1])],fill=(239,107,205),width=2)
    for j,(name,color) in enumerate([('Index contour',(255,187,82)),('Intermediate',(109,185,204)),('Breakline',(239,107,205))]):
        draw.line((840,85+j*28,865,85+j*28),fill=color,width=2)
        draw.text((875,78+j*28),name,fill='white')
    draw.text((20,828),f'{len(lines):,} contours | {len(set(line.level for line in lines))} elevation levels',fill='white')
    return np.asarray(image).copy()


def publish(runner,render,*args):
    try: runner.report=render(*args)
    except Exception as exc:
        runner.log(f'Output saved; preview unavailable: {exc}')
