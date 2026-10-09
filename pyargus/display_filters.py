"""Named display class filters and their validation."""
CLASS_GROUPS={'All':None,'Ground':(2,),'Vegetation':(3,4,5),'Buildings':(6,),'Noise':(7,18)}


def parse_classes(text):
    value=text.strip()
    for name,classes in CLASS_GROUPS.items():
        if name.lower()==value.lower():return classes
    try:
        classes=tuple(sorted(set(int(x.strip()) for x in value.split(','))))
    except ValueError:raise ValueError('Choose a named class group, All, or comma-separated class numbers.') from None
    if not classes or any(c<0 or c>255 for c in classes):raise ValueError('Class numbers must be between 0 and 255.')
    return classes


