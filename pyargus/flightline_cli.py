"""CLI registration for read-only baseline/candidate flightline diagnosis."""
def register(sub):
    from pyargus.qa.flightline_diagnostics import DEFAULTS
    parser=sub.add_parser('flightline-diagnostics',help='read-only flightline coverage / surface diagnosis; optional existing candidate comparison')
    parser.add_argument('project',help='saved baseline pyArgus project JSON')
    parser.add_argument('--out',required=True,help='new report folder')
    parser.add_argument('--candidate-project',help='optional saved project referencing already processed candidate clouds')
    for name,value in DEFAULTS.items():
        parser.add_argument('--'+name.replace('_','-'),type=int if name in ('min_points','min_cells') else float,default=value)
    parser.set_defaults(func=command)


def command(args):
    from pyargus.project import Project
    from pyargus.qa.flightline_diagnostics import run,DEFAULTS
    run(Project.load(args.project),args.out,
        candidate=Project.load(args.candidate_project) if args.candidate_project else None,
        config={name:getattr(args,name) for name in DEFAULTS})
    return 0
