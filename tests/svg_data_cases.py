"""Deterministic heatmap data-processing cases shared by unit and visual tests."""
import numpy as np
from veusz import document
from test_export_svg import make_document


def data_cases():
    cases = []
    def add(name, modes=('default', 'resample-pixels', 'resample-smooth'), **options):
        for mode in modes:
            cases.append(dict(name=name+'-'+mode, mode=mode, **options))
    for scaling in ('linear', 'sqrt', 'log', 'squared'):
        add('scale-'+scaling, scaling=scaling)
    for variant in ('signed', 'negative', 'zeros', 'constant', 'checker',
                    'impulses', 'nan', 'all-nan', 'infinity', 'strided'):
        add('values-'+variant, variant=variant)
    for bounds in ('manual', 'equal', 'reversed'):
        add('range-'+bounds, value_range=bounds)
    add('invert', invert=True)
    add('reverse-and-invert', value_range='reversed', invert=True)
    add('stepped-map', cmap='spectrum-step5')
    add('alpha-map', cmap='transblack')
    for scaling in ('sqrt', 'log', 'squared'):
        add('signed-'+scaling, scaling=scaling, variant='signed', value_range='manual')
    geometry_modes=('default','resample-pixels','resample-smooth','rectangles')
    for grid in ('regular-edges','irregular-edges','centers'):
        add('grid-'+grid, modes=geometry_modes, grid=grid)
    for logaxes in ('x','y','xy'):
        for mapping in ('pixels','bounds'):
            add('log-'+logaxes+'-'+mapping, modes=geometry_modes,
                logaxes=logaxes, mapping=mapping)
    for reverse in ('x','y','xy'):
        add('reverse-'+reverse, modes=geometry_modes, reverse=reverse)
    add('reverse-crop', modes=geometry_modes, reverse='xy', crop=True)
    add('crop', modes=geometry_modes, crop=True)
    add('outside', modes=geometry_modes, outside=True)
    add('fractional', fractional=True)
    add('fractional-page', fractional=True, fractional_page=True)
    add('axis-datascale', datascale=True)
    for alpha in ('gradient','binary','out-of-range','zero','mismatched'):
        add('mask-'+alpha, alpha=alpha)
    add('mask-with-global-alpha', alpha='gradient', transparency=37)
    add('mask-with-nan', alpha='gradient', variant='nan')
    add('invisible', transparency=100)
    add('dark-background', transparency=45, background=True)
    add('overlapping', alpha='gradient', transparency=37, overlap=True, background=True)
    add('axis-cache', overlap=True, visible_axes=True)
    for shape in ((29,40),(30,40),(40,29),(40,30),(1,40),(40,1),(33,47)):
        add('shape-%dx%d'%shape, modes=('default',), shape=shape)
    return cases


def make_data_document(case):
    doc=make_document(mode=case['mode'],fractional=case.get('fractional',False))
    ci=document.CommandInterface(doc)
    shape=case.get('shape',(40,40))
    y,x=np.mgrid[0:shape[0],0:shape[1]]
    data=(3+np.sin(x*.37)+np.cos(y*.29)+(x+y)/(2*max(shape))).astype(float)
    variant=case.get('variant')
    if variant=='signed': data-=3
    elif variant=='negative': data=-data
    elif variant=='zeros': data[:]=0
    elif variant=='constant': data[:]=2.5
    elif variant=='checker': data=(x%2+y%2)%2*8+.2
    elif variant=='impulses':
        data[:]=0
        data[0,0]=2
        data[-1,-1]=8
        data[shape[0]//2,shape[1]//2]=12
    elif variant=='nan': data[3:9,4:11]=np.nan
    elif variant=='all-nan': data[:]=np.nan
    elif variant=='infinity':
        data[2:5,2:5]=np.inf
        data[12:15,10:15]=-np.inf
    elif variant=='strided':
        yy,xx=np.mgrid[0:shape[0]*2,0:shape[1]*2]
        data=(3+np.sin(xx*.2)+np.cos(yy*.15))[::2,::2]
    coords=dict(xrange=(1,101),yrange=(1,101))
    grid=case.get('grid')
    if grid=='regular-edges':
        coords=dict(xedge=np.linspace(1,101,shape[1]+1),yedge=np.linspace(1,101,shape[0]+1))
    elif grid=='irregular-edges':
        coords=dict(xedge=np.geomspace(1,101,shape[1]+1),yedge=np.geomspace(1,101,shape[0]+1))
    elif grid=='centers':
        coords=dict(xcent=np.geomspace(10,90,shape[1]),ycent=np.linspace(10,90,shape[0]))
    ci.SetData2D('z',data,**coords)
    ci.Set('/page/graph/heatmap/colorScaling',case.get('scaling','linear'))
    ci.Set('/page/graph/heatmap/colorMap',case.get('cmap','spectrum'))
    ci.Set('/page/graph/heatmap/colorInvert',case.get('invert',False))
    ci.Set('/page/graph/heatmap/mapping',case.get('mapping','pixels'))
    ci.Set('/page/graph/heatmap/transparency',case.get('transparency',0))
    bounds=case.get('value_range')
    if bounds=='manual' or variant=='infinity': low,high=.1,6
    elif bounds=='equal': low,high=2.5,2.5
    elif bounds=='reversed': low,high=6,.1
    else: low=high='Auto'
    ci.Set('/page/graph/heatmap/min',low)
    ci.Set('/page/graph/heatmap/max',high)
    if case.get('alpha'):
        alpha=np.broadcast_to(np.linspace(0,1,shape[1]),shape).copy()
        kind=case['alpha']
        if kind=='binary': alpha=(((x//5)+(y//5))%2).astype(float)
        elif kind=='out-of-range': alpha=alpha*3-1
        elif kind=='zero': alpha[:]=0
        elif kind=='mismatched': alpha=alpha[:15,:17]
        ci.SetData2D('alpha',alpha)
        ci.Set('/page/graph/heatmap/transparencyData','alpha')
    for axis in ('x','y'):
        low,high=(11.2,71.7) if case.get('crop') else (1.,101.)
        if case.get('outside'): low,high=201.,301.
        if axis in case.get('reverse',''): low,high=high,low
        ci.Set('/page/graph/'+axis+'/min',low)
        ci.Set('/page/graph/'+axis+'/max',high)
        ci.Set('/page/graph/'+axis+'/log',axis in case.get('logaxes',''))
        if case.get('datascale'): ci.Set('/page/graph/'+axis+'/datascale',.1)
        if case.get('visible_axes'): ci.Set('/page/graph/'+axis+'/hide',False)
    if case.get('fractional_page'):
        ci.Set('/width','2.003in')
        ci.Set('/height','2.003in')
    if case.get('background'):
        ci.Set('/page/Background/hide',False)
        ci.Set('/page/Background/color','#26364a')
    if case.get('overlap'):
        ci.SetData2D('second',np.sin(x*.18)*np.cos(y*.23),**coords)
        ci.To('/page/graph')
        ci.Add('image',name='overlay',autoadd=False)
        ci.To('overlay')
        ci.Set('data','second')
        ci.Set('drawMode',case['mode'])
        ci.Set('colorMap','grey')
        ci.Set('transparency',65)
    return doc
