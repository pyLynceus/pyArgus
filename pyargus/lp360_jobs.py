"""LP360 job discovery and explicit processing recipes; no vendor runtime is used."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import os
import math
import numpy as np
from pyargus import project


@dataclass
class Discovery:
    root: str
    cloud_groups: dict = field(default_factory=dict)
    trjs: list = field(default_factory=list)
    sbets: list = field(default_factory=list)
    controls: list = field(default_factory=list)
    eos: list = field(default_factory=list)
    calibrations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class Recipe:
    root: str
    clouds: list = field(default_factory=list)
    trajectories: list = field(default_factory=list)
    control: str = ''
    control_order: str = 'auto'
    allow_no_control: bool = False
    eo: str = ''
    images: str = ''
    calibration: str = ''
    colorize: bool = False
    align: bool = True
    map_crs: str = ''
    same_vertical: bool = False
    gps_week: int | None = None
    cell: float = 3.
    slope: float = .15
    window: float = 60.
    threshold: float = 1.5
    alignment_cell: float = 6.
    min_points: int = 6
    contour_interval: float = 1.
    max_points: int = 25_000_000
    max_grid_cells: int = 5_000_000
    workers: int = 2
    memory_mb: float = 4096.
    quarter_turns: int = 3
    noise_min: float | None = None
    noise_max: float | None = None
    alignment_reporting: dict = field(default_factory=dict)

    def spec(self):
        bindings={}
        for cloud in self.clouds:
            same=[t['path'] for t in self.trajectories if Path(t['path']).stem.casefold()==Path(cloud).stem.casefold()]
            if len(same)==1:bindings[cloud]=same[0]
        return project.Project(list(self.clouds),[project.TrajectoryInput(**t) for t in self.trajectories],
                               map_crs=self.map_crs or None,same_vertical=self.same_vertical,
                               gps_week=self.gps_week,bindings=bindings,max_points=self.max_points,alignment_reporting=self.alignment_reporting)


def discover(root, *, cancel=lambda:False, log=lambda s:None):
    root=Path(root).resolve()
    if not root.is_dir():raise ValueError('Choose an existing LP360 project folder.')
    result=Discovery(str(root));primary={};other={};visited=0
    def blocked(name):
        name=name.casefold()
        return name.startswith(('pyargus','pospac_')) or name in ('.git','.venv','venv','__pycache__','records','logs','multicam','node_modules','dist','build','output','outputs')
    def error(exc):result.warnings.append(str(exc))
    for folder,dirs,files in os.walk(root,followlinks=False,onerror=error):
        if cancel():raise InterruptedError('LP360 discovery stopped')
        dirs[:]=sorted(d for d in dirs if not blocked(d) and not (Path(folder)/d).is_symlink())
        for name in sorted(files):
            visited+=1
            if visited>250_000:raise ValueError('Choose a smaller project folder: discovery exceeded 250,000 files.')
            p=Path(folder)/name
            if p.is_symlink():continue
            suffix=p.suffix.casefold();lower=p.stem.casefold()
            if suffix in ('.las','.laz'):
                groups=primary if p.parent.name.casefold()=='las' and p.parent.parent.name.casefold().startswith('flight_') else other
                groups.setdefault(str(p.parent),[]).append(str(p))
            elif suffix=='.trj':result.trjs.append(str(p))
            elif suffix=='.out' and lower.startswith('sbet'):result.sbets.append(str(p))
            elif suffix=='.csv' and any(s in lower for s in ('control','gcp','checkpoint','allpts')):result.controls.append(str(p))
            elif suffix=='.csv' and lower.startswith('eo_photos'):result.eos.append(str(p))
            elif suffix=='.cal':result.calibrations.append(str(p))
        if visited and visited%5000<len(files):log(f'Discovery: {visited:,} filenames checked')
    result.cloud_groups=primary or other
    if primary and other:result.warnings.append('Derived or non-flight LAS folders were excluded; use manual LAS selection if you need those files.')
    if not result.eos:
        adjusted=root/'adjusted_eo.csv'
        if adjusted.is_file():result.eos.append(str(adjusted));result.warnings.append('Only adjusted_eo.csv was found; verify that its orientation and datum are intended for this run.')
    return result


def _headers(recipe):
    import laspy
    headers=[]
    for p in recipe.clouds:
        with laspy.open(p) as reader:headers.append(reader.header.copy())
    return headers


def suggest(discovery, group=None):
    recipe=Recipe(discovery.root)
    if group is None and len(discovery.cloud_groups)==1:group=next(iter(discovery.cloud_groups))
    if group is not None:recipe.clouds=list(discovery.cloud_groups[group])
    if len(discovery.controls)==1:recipe.control=discovery.controls[0]
    if recipe.clouds:
        parents={Path(p).parent.parent for p in recipe.clouds}
        flight=next(iter(parents)) if len(parents)==1 else Path(discovery.root)
        local=[p for p in discovery.eos if Path(p).is_relative_to(flight)]
        if len(local)==1:recipe.eo=local[0]
        elif len(discovery.eos)==1:recipe.eo=discovery.eos[0]
        recipe.images=str(flight)
        try:headers=_headers(recipe);crs=headers[0].parse_crs()
        except Exception:return recipe
        if crs is not None:
            recipe.same_vertical=bool(crs.is_compound and all(h.parse_crs() is not None and h.parse_crs().equals(crs) for h in headers))
            factor=crs.axis_info[0].unit_conversion_factor
            if math.isclose(factor,1.):recipe.cell=1.;recipe.window=18.;recipe.threshold=.5;recipe.alignment_cell=2.;recipe.contour_interval=.25
        import laspy
        from pyargus.formats.trj import read_trj
        selected=[]
        for cloud in recipe.clouds:
            candidates=[p for p in discovery.trjs if Path(p).stem.casefold()==Path(cloud).stem.casefold() and Path(p).is_relative_to(flight)]
            if len(candidates)!=1:continue
            t=candidates[0]
            try:times=read_trj(t).records['time']
            except Exception:
                selected.append(dict(path=t,time_mode='',gps_week=None,confirmed=False));continue
            with laspy.open(cloud) as reader:
                sample=reader.read_points(10000)
                stored=np.asarray(sample.gps_time) if 'gps_time' in reader.header.point_format.dimension_names else np.array([])
            modes=[]
            if stored.size:
                if np.mean((stored>=times[0])&(stored<=times[-1]))>.8:modes.append('same')
                if int(headers[recipe.clouds.index(cloud)].global_encoding.gps_time_type)==1:
                    week=int(np.floor((np.median(stored)+1e9-np.median(times))/604800+.5))
                    sow=stored+1e9-week*604800
                    if np.mean((sow>=times[0])&(sow<=times[-1]))>.8:modes.append('week')
            selected.append(dict(path=t,time_mode=modes[0] if len(modes)==1 else '',gps_week=None,confirmed=False))
        if len(selected)==len(recipe.clouds):recipe.trajectories=selected
        elif not selected and len(discovery.sbets)==1:recipe.trajectories=[dict(path=discovery.sbets[0],time_mode='week',gps_week=None,confirmed=False)]
        else:recipe.trajectories=selected
    return recipe


def inspect_recipe(recipe):
    """Return actionable issues and detected metadata; never choose among conflicts."""
    from pyargus.formats.control import read_control_csv
    from pyargus.classify.job import validate_noise_bounds
    issues=[];info=dict(points=0,uncompressed_bytes=0,units='not determined',control_order=recipe.control_order)
    def issue(field,message):issues.append(dict(field=field,message=message))
    if not recipe.clouds:issue('clouds','Select a LAS folder or browse for source clouds.')
    if len(set(recipe.clouds))!=len(recipe.clouds):issue('clouds','The source cloud list contains duplicates.')
    stems=[(str(Path(p).parent),Path(p).stem.casefold()) for p in recipe.clouds]
    if len(set(stems))!=len(stems):issue('clouds','Both LAS and LAZ copies of the same source were selected; choose one copy.')
    headers=[];crs=None
    try:
        headers=_headers(recipe);info['points']=sum(h.point_count for h in headers);info['uncompressed_bytes']=sum(h.point_count*h.point_format.size for h in headers)
        if headers:
            import pyproj
            crs=headers[0].parse_crs() or (pyproj.CRS.from_user_input(recipe.map_crs) if recipe.map_crs else None)
            if crs is None:issue('map_crs','LAS CRS is missing; enter its verified projected CRS.')
            else:
                horizontal=crs.sub_crs_list[0] if crs.is_compound else crs
                if not horizontal.is_projected:issue('map_crs','A projected LAS coordinate system is required.')
                info.update(crs_wkt=crs.to_wkt(),units=crs.axis_info[0].unit_name)
                factors=[a.unit_conversion_factor for a in crs.axis_info]
                if len(factors)>2 and not np.allclose(factors,factors[0],rtol=1e-12,atol=0):issue('map_crs','Horizontal and vertical LAS units differ.')
                for h in headers:
                    tagged=h.parse_crs()
                    if tagged is not None and not tagged.equals(crs):issue('clouds','Selected clouds use different coordinate systems.')
                    if 'gps_time' not in h.point_format.dimension_names and recipe.align:issue('clouds','Alignment requires LAS GPS timestamps.')
                if not recipe.same_vertical:issue('same_vertical','Confirm common XYZ units and vertical datum; a horizontal CRS alone does not establish these.')
            if any(h.point_count==0 for h in headers):issue('clouds','An input cloud is empty.')
            if any(int(h.global_encoding.gps_time_type)==0 for h in headers) and recipe.gps_week is None:issue('gps_week','LAS GPS week time requires the verified project GPS week.')
    except Exception as exc:issue('clouds',str(exc))
    if recipe.align and not recipe.trajectories:issue('trajectories','Alignment needs TRJ/SBET files. Browse for them or disable alignment.')
    for t in recipe.trajectories:
        if not Path(t['path']).is_file():issue('trajectories','Missing trajectory: '+t['path'])
        else:
            try:
                from pyargus.formats.trj import read_trj
                from pyargus.formats.sbet import read_sbet
                data=read_trj(t['path']).records if Path(t['path']).suffix.lower()=='.trj' else read_sbet(t['path'])
                if not np.isfinite(data['time']).all():raise ValueError('Trajectory contains nonfinite timestamps')
            except Exception as exc:issue('trajectories',Path(t['path']).name+': '+str(exc))
        if t.get('time_mode') not in ('same','week'):issue('time_mode','Choose same stored timestamps or GPS week seconds for '+Path(t['path']).name)
    try:
        from pyargus.qa.alignment_report import settings, read_checks
        read_checks(settings(recipe.alignment_reporting))
    except (ValueError,TypeError,OSError) as exc:issue('alignment_reporting',str(exc))
    if recipe.control:
        try:
            order=recipe.control_order
            if order=='auto' and headers:
                scores={}
                lower=np.min([h.mins[:2] for h in headers],axis=0);upper=np.max([h.maxs[:2] for h in headers],axis=0);pad=np.maximum((upper-lower)*.02,20)
                for candidate in ('pnez','penz'):
                    _,x,y,z=read_control_csv(recipe.control,candidate)
                    scores[candidate]=float(np.mean((x>=lower[0]-pad[0])&(x<=upper[0]+pad[0])&(y>=lower[1]-pad[1])&(y<=upper[1]+pad[1]))) if len(x) else 0.
                best=max(scores,key=scores.get)
                order=best if scores[best]>.5 and scores[best]>min(scores.values()) else 'auto'
            if order not in ('pnez','penz'):issue('control_order','Control column order is ambiguous; select P,N,E,Z or P,E,N,Z.')
            else:
                control=read_control_csv(recipe.control,order)
                if not len(control[0]):issue('control','Control CSV has no points.')
                info.update(control_order=order,control_points=len(control[0]))
        except Exception as exc:issue('control',str(exc))
    elif not recipe.allow_no_control:issue('control','Control CSV was not selected. Browse for it or explicitly continue without control.')
    if recipe.colorize:
        if not recipe.eo or not Path(recipe.eo).is_file():issue('eo','Select the EO CSV for recoloring.')
        if not recipe.images or not Path(recipe.images).is_dir():issue('images','Select the imagery folder for recoloring.')
        if recipe.calibration and not Path(recipe.calibration).is_file():issue('calibration','The calibration override is missing.')
        if recipe.eo and recipe.images and Path(recipe.eo).is_file() and Path(recipe.images).is_dir():
            try:
                from pyargus.formats.eo import read_eo_csv
                from pyargus.imagery.colorize import find_images
                from pyargus.imagery.job import resolve_cameras
                cameras=resolve_cameras(read_eo_csv(recipe.eo),find_images(recipe.images),cal=recipe.calibration or None,quarter_turns=recipe.quarter_turns)
                info['camera_groups']=len(cameras)
            except Exception as exc:issue('imagery',str(exc))
    for name in ('cell','window','threshold','alignment_cell','contour_interval','memory_mb'):
        value=getattr(recipe,name)
        if not math.isfinite(value) or value<=0:issue(name,name+' must be finite and positive.')
    if not math.isfinite(recipe.slope) or recipe.slope<0:issue('slope','Slope must be finite and nonnegative.')
    for name in ('min_points','max_points','max_grid_cells','workers'):
        if not isinstance(getattr(recipe,name),int) or getattr(recipe,name)<=0:issue(name,name+' must be a positive integer.')
    if recipe.quarter_turns not in (0,1,2,3):issue('quarter_turns','Image-grid quarter turns must be 0, 1, 2 or 3.')
    try:project._week(recipe.gps_week)
    except ValueError as exc:issue('gps_week',str(exc))
    if recipe.window<recipe.cell:issue('window','Ground window must be at least one cell.')
    if recipe.align and info['points']>recipe.max_points:issue('max_points',f"{info['points']:,} points exceed the alignment array limit. Raise it for available RAM, choose a smaller block, or disable alignment.")
    try:validate_noise_bounds(recipe.noise_min,recipe.noise_max)
    except ValueError as exc:issue('noise',str(exc))
    return issues,info
