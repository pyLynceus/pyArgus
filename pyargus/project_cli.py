"""Project CLI registration, isolated from single-cloud commands."""
import json
from pyargus import project


def register(sub):
    for name,help_text,handler in (
            ('project-info','inventory and match a saved multi-file project',_info),
            ('project-qa','QA across every cloud in a saved project',_qa),
            ('project-align','align all project strips and export per-source clouds',_align)):
        p = sub.add_parser(name,help=help_text)
        p.add_argument('project')
        if name!='project-info': p.add_argument('--out',required=True)
        if name=='project-align':
            p.add_argument('--cell',type=float,default=6.)
            p.add_argument('--min-points',type=int,default=6)
            p.add_argument('--boresight',action='store_true',help='also solve boresight (default: vertical offsets only)')
        p.set_defaults(func=handler)


def _info(args):
    result=project.load(project.Project.load(args.project),log=print)
    print(json.dumps(result.inventory,indent=2)); return 0


def _qa(args):
    project.qa(project.Project.load(args.project),args.out,log=print); return 0


def _align(args):
    project.align(project.Project.load(args.project),args.out,cell=args.cell,
                  min_points=args.min_points,solve_boresight=args.boresight,log=print)
    return 0
