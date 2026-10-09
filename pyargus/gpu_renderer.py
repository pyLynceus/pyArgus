"""Optional OpenGL 3.3 offscreen renderer; Tk remains the window owner.

Only display samples reach the GPU. Subtract a double-precision local origin
before uploading float32 coordinates; never upload State Plane XYZ directly.
The returned image is copied to Tk, so readback/presentation still cost CPU time.
"""
import threading
import numpy as np

_VERTEX = """#version 330
in vec3 in_position;
in vec3 in_color;
uniform mat3 camera;
uniform vec3 center;
uniform vec2 viewport_size;
uniform vec2 pan;
uniform float scale;
uniform float depth_range;
uniform float shear;
uniform bool grayscale;
uniform bool snap_pixels;
uniform float point_size;
out vec3 color;
void main() {
    vec3 q = camera * (in_position - center);
    vec2 pixel = vec2((q.x + shear*q.z)*scale, -q.y*scale)
                 + viewport_size*0.5 + pan;
    if (snap_pixels) pixel = roundEven(pixel);
    gl_Position = vec4(2.0*(pixel.x+0.5)/viewport_size.x-1.0,
                       1.0-2.0*(pixel.y+0.5)/viewport_size.y,
                       -q.z/depth_range, 1.0);
    gl_PointSize = point_size;
    color = grayscale ? vec3(dot(in_color, vec3(.299,.587,.114))) : in_color;
}
"""
_FRAGMENT = """#version 330
in vec3 color;
out vec4 frag;
void main() { frag = vec4(color, 1.0); }
"""
_LINE_GEOMETRY = """#version 330
layout(lines) in;
layout(triangle_strip, max_vertices=4) out;
in vec3 color[];
out vec3 line_color;
uniform vec2 viewport_size;
uniform float line_width;
void main() {
    vec2 d = (gl_in[1].gl_Position.xy-gl_in[0].gl_Position.xy)*viewport_size;
    float n = length(d);
    if (n < 0.000001) return;
    vec2 offset = vec2(-d.y,d.x)/n * line_width/viewport_size;
    for (int i=0;i<2;i++) {
        line_color=color[i];
        gl_Position=gl_in[i].gl_Position+vec4(offset,0,0); EmitVertex();
        gl_Position=gl_in[i].gl_Position-vec4(offset,0,0); EmitVertex();
    }
    EndPrimitive();
}
"""
_LINE_FRAGMENT = """#version 330
in vec3 line_color;
out vec4 frag;
void main() { frag = vec4(line_color, 1.0); }
"""


class Renderer:
    """One UI-thread-owned context with resident point buffers."""
    def __init__(self):
        import moderngl
        self.gl = moderngl
        self.owner = threading.get_ident()
        self.ctx = moderngl.create_standalone_context(require=330)
        self.resources = []
        self.cloud = None
        self.cloud_key = None
        self.frame = None
        self.size = None
        self.uploads = 0
        try:
            self.device = str(self.ctx.info["GL_RENDERER"])
            if any(word in self.device.lower() for word in
                   ("llvmpipe", "softpipe", "software", "gdi generic")):
                raise RuntimeError("OpenGL is using a software renderer: "+self.device)
            with self.ctx:
                self.point_program = self.ctx.program(vertex_shader=_VERTEX,
                                                       fragment_shader=_FRAGMENT)
                self.line_program = self.ctx.program(vertex_shader=_VERTEX,
                                                      geometry_shader=_LINE_GEOMETRY,
                                                      fragment_shader=_LINE_FRAGMENT)
                self.resources = [self.point_program, self.line_program]
        except Exception:
            self.close()
            raise

    def _thread(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("GPU rendering must run on its owning UI thread")

    def _resize(self, width, height):
        if self.size == (width, height):
            return
        if max(width,height) > self.ctx.info["GL_MAX_TEXTURE_SIZE"]:
            raise ValueError("Viewport exceeds the graphics device texture limit")
        if self.frame is not None:
            for item in self.frame:
                item.release()
        color = self.ctx.texture((width,height), 3)
        depth = self.ctx.depth_renderbuffer((width,height))
        fbo = self.ctx.framebuffer([color],depth)
        self.frame = (fbo,color,depth)
        self.size = (width,height)

    def _upload(self, points, rgb, keep, key):
        # Keep source references alive so an id cannot be recycled underneath a cache key.
        if key is not None and key == self.cloud_key:
            return
        if self.cloud is not None:
            for item in self.cloud:
                item.release()
        selected = np.asarray(points,dtype=np.float64)[keep]
        self.source = (points,rgb)
        self.origin = (selected.min(axis=0)+selected.max(axis=0))/2 if len(selected) else np.zeros(3)
        self.radius = max(1.,float(np.linalg.norm(np.ptp(selected,axis=0)))) if len(selected) else 1.
        data = np.empty((max(1,len(selected)),6),dtype="f4")
        if len(selected):
            data[:len(selected),:3] = selected-self.origin
            data[:len(selected),3:] = np.asarray(rgb)[keep]/255.
        buffer = self.ctx.buffer(data.tobytes())
        vao = self.ctx.vertex_array(self.point_program,
                                   [(buffer,"3f 3f","in_position","in_color")])
        self.cloud = (vao,buffer)
        self.count = len(selected)
        self.cloud_key = key
        self.uploads += 1

    def _uniforms(self, program, center, yaw, pitch, scale, pan, shear, gray, depth):
        a,b=np.deg2rad([yaw,pitch])
        right=np.array([np.cos(a),np.sin(a),0.])
        up=np.array([-np.sin(a)*np.sin(b),np.cos(a)*np.sin(b),np.cos(b)])
        matrix=np.stack((right,up,np.cross(right,up)))
        program["camera"].write(np.asarray(matrix.T,dtype="f4").tobytes())
        program["center"].value=tuple(np.asarray(center)-self.origin)
        program["viewport_size"].value=self.size
        program["pan"].value=tuple(pan)
        program["scale"].value=float(scale)
        program["depth_range"].value=float(depth)
        program["shear"].value=float(shear)
        program["grayscale"].value=gray
        program["snap_pixels"].value=program is self.point_program
        if "point_size" in program:program["point_size"].value=1.

    def render(self, points, rgb, center, yaw, pitch, scale, width, height, pan,
               *, keep=None, key=None, stereo_depth=None, swap=False, linework=()):
        self._thread()
        if stereo_depth is not None and (not np.isfinite(stereo_depth) or not 0<=stereo_depth<=6):
            raise ValueError("Stereo depth must be between 0 and 6 degrees")
        if keep is None:
            keep=np.ones(len(points),dtype=bool)
        with self.ctx:
            self._resize(width,height)
            self._upload(points,rgb,keep,key)
            depth=self.radius+float(np.linalg.norm(np.asarray(center)-self.origin))+1.
            for positions,*_ in linework:
                if len(positions):
                    depth=max(depth,float(np.max(np.linalg.norm(np.asarray(positions)-self.origin,axis=1)))+
                              float(np.linalg.norm(np.asarray(center)-self.origin))+1.)
            lines=[]
            try:
                for positions,color,line_width,top in linework:
                    positions=np.asarray(positions)
                    if not len(positions) or line_width<=0:
                        continue
                    # Independent segments; the geometry shader supplies portable pixel widths.
                    pairs=np.stack((positions[:-1],positions[1:]),axis=1).reshape(-1,3) if len(positions)>1 else positions
                    program=self.line_program if len(positions)>1 else self.point_program
                    data=np.empty((len(pairs),6),dtype="f4")
                    data[:,:3]=pairs-self.origin;data[:,3:]=np.asarray(color)/255.
                    buf=self.ctx.buffer(data.tobytes())
                    vao=self.ctx.vertex_array(program,[(buf,"3f 3f","in_position","in_color")])
                    lines.append((vao,buf,float(line_width),top,program))
                result=[]
                eyes=(1,-1) if stereo_depth is not None else (0,)
                for eye in eyes:
                    fbo=self.frame[0];fbo.use();fbo.depth_mask=True
                    background=(20,20,20) if stereo_depth is not None else (16,25,37)
                    fbo.clear(*(value/255. for value in background),depth=1.)
                    self.ctx.enable_only(self.gl.DEPTH_TEST|self.gl.PROGRAM_POINT_SIZE)
                    self.ctx.depth_func="<="
                    shear=eye*np.tan(np.deg2rad((stereo_depth or 0.)/2))
                    self._uniforms(self.point_program,center,yaw,pitch,scale,pan,shear,
                                   stereo_depth is not None,depth)
                    if self.count:
                        self.cloud[0].render(self.gl.POINTS,vertices=self.count)
                    fbo.depth_mask=False
                    self._uniforms(self.line_program,center,yaw,pitch,scale,pan,shear,
                                   stereo_depth is not None,depth)
                    for vao,buf,line_width,top,program in lines:
                        self.ctx.enable_only((self.gl.NOTHING if top else self.gl.DEPTH_TEST)|self.gl.PROGRAM_POINT_SIZE)
                        if program is self.line_program:
                            program['line_width'].value=line_width
                            vao.render(self.gl.LINES)
                        else:
                            program['point_size'].value=line_width
                            vao.render(self.gl.POINTS)
                    pixels=np.frombuffer(fbo.read(components=3,alignment=1),dtype=np.uint8)
                    result.append(pixels.reshape(height,width,3)[::-1].copy())
                if stereo_depth is None:
                    return result[0]
                if swap:
                    result.reverse()
                return np.stack((result[0][:,:,0],result[1][:,:,1],result[1][:,:,2]),axis=2)
            finally:
                for vao,buf,*_ in lines:
                    vao.release();buf.release()
                self.frame[0].depth_mask=True

    def close(self):
        self._thread()
        if self.ctx is None:
            return
        with self.ctx:
            if self.cloud is not None:
                for item in self.cloud:
                    item.release()
            if self.frame is not None:
                for item in self.frame:
                    item.release()
            for item in self.resources:
                item.release()
        self.ctx.release()
        self.ctx=None;self.cloud=None;self.frame=None;self.resources=[]
