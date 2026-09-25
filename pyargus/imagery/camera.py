"""The frame camera: calibration and ground-to-pixel projection.

The lens model here IS Agisoft's, evaluated in the STORED IMAGE's own
grid, because that is the frame the ``.cal`` sidecar LP360 delivers
beside every frame is defined in, and nothing downstream re-estimates
it. Normalised coordinates x = X/Z, y = Y/Z in a camera frame with x
along +col, y along +row and z forward; then::

    r2 = x^2 + y^2
    radial = 1 + K1 r2 + K2 r2^2 + K3 r2^3
    x' = x*radial + P1(r2 + 2x^2) + 2 P2 x y
    y' = y*radial + P2(r2 + 2y^2) + 2 P1 x y
    col = (W-1)/2 + CX + f x'      row = (H-1)/2 + CY + f y'

with f, CX, CY in PIXELS and K/P against a focal-normalised radius --
the sidecar's own units, transplanted nowhere.

Evaluating in the stored grid is the whole point. An earlier version
worked in a millimetre "photo frame" (y up) and rotated the RESULT
into the stored grid afterwards. The radial terms survive that,
because they are rotation-invariant -- but CX/CY and P1/P2 are not,
and the shipped TrueView default is ``quarter_turns=3``: the review
panel measured a ~27 px systematic on exactly the production path,
invisible to a test suite that only ever combined distortion with
``quarter_turns=0``. Here the quarter turns instead rotate the CAMERA
AXES before the lens model runs, so the model always sees the grid it
was calibrated in, and the equivalence test covers all four turns.

``quarter_turns`` is how many anticlockwise quarter turns take the
photo frame (the one the EO's Direction/Up vectors describe) to the
stored image grid; 3 for a TrueView 660.

FIELD-OF-VIEW GUARD. Brown-Conrady is a fit inside the calibrated
field and says nothing outside it. Extrapolated far off-axis, a lens
with strong barrel distortion folds back: the distorted radius stops
growing, turns around, and sweeps through zero, so a point 60 degrees
off-axis -- nowhere near the physical field -- lands on a valid pixel,
sometimes the exact image center, and then WINS the most-centered
competition. The panel reproduced that end to end. So every camera
computes the ideal radius where its own model folds, refuses a
calibration that folds before it reaches its own frame corner, and
masks points beyond the fold.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

TRUEVIEW_PIXEL_MM = 0.0024
CAL_SUFFIX = ".cal"


@dataclass
class Camera:
    """A calibrated frame camera in the sidecar's own (Agisoft) terms."""
    focal_px: float
    width_px: int             # of the STORED image
    height_px: int
    cx_px: float = 0.0        # principal point offset from the stored
    cy_px: float = 0.0        # image center, +col / +row
    k1: float = 0.0           # focal-normalised radius
    k2: float = 0.0
    k3: float = 0.0
    p1: float = 0.0
    p2: float = 0.0
    quarter_turns: int = 0    # photo frame -> stored grid, ACW
    pixel_mm: float = TRUEVIEW_PIXEL_MM   # for reporting only
    name: str = ""
    _r_valid: float = field(default=0.0, repr=False)

    def __post_init__(self):
        if self.focal_px <= 0:
            raise ValueError(f"camera {self.name!r}: non-positive focal "
                             f"length {self.focal_px} px")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError(f"camera {self.name!r}: pixel grid is not "
                             f"positive")
        if int(self.quarter_turns) != self.quarter_turns:
            raise ValueError(f"camera {self.name!r}: quarter_turns must be "
                             f"a whole number, got {self.quarter_turns!r}")
        self.quarter_turns = int(self.quarter_turns) % 4
        self._r_valid = self._validity_radius()

    @property
    def focal_mm(self):
        return self.focal_px * self.pixel_mm

    def _radial_distorted(self, r):
        """Distorted radius for an ideal radius (pure radial part)."""
        r2 = r * r
        return r * (1.0 + self.k1 * r2 + self.k2 * r2 * r2
                    + self.k3 * r2 * r2 * r2)

    def _validity_radius(self):
        """Ideal radius where this lens model stops being usable.

        The first radius at which the distorted radius stops growing
        (the barrel fold). A model that folds before it reaches its own
        frame corner cannot describe the image it was calibrated on --
        that is a corrupt or mis-transplanted calibration, and it
        refuses here rather than painting points with pixels from the
        far side of the fold.
        """
        corner = np.hypot((self.width_px - 1) / 2.0 + abs(self.cx_px),
                          (self.height_px - 1) / 2.0 + abs(self.cy_px)) \
            / self.focal_px
        r = np.linspace(1e-6, max(4.0 * corner, 1.0), 4000)
        rd = self._radial_distorted(r)
        falling = np.flatnonzero(np.diff(rd) <= 0)
        r_fold = float(r[falling[0]]) if falling.size else float(r[-1])
        reach = np.flatnonzero(rd >= corner)
        r_reach = float(r[reach[0]]) if reach.size else float("inf")
        if r_fold < r_reach:
            raise ValueError(
                f"camera {self.name!r}: the distortion model folds back at "
                f"an ideal radius of {r_fold:.3f}, before reaching its own "
                f"frame corner ({corner:.3f}) -- these coefficients cannot "
                f"describe this image. Check the .cal (K1={self.k1:.4g}, "
                f"K2={self.k2:.4g}, K3={self.k3:.4g}).")
        return r_fold

    def _rotate_to_stored(self, a, b):
        """Rotate photo-frame (x right, y DOWN) onto the stored grid.

        ``quarter_turns`` ACW turns of the image rotate its axes the
        same way: (a, b) -> (-b, a) per turn. Pinned against np.rot90
        in the tests, which is where the convention is defined.
        """
        turns = self.quarter_turns % 4
        if turns == 0:
            return a, b
        if turns == 1:
            return -b, a
        if turns == 2:
            return -a, -b
        return b, -a

    def _rotate_from_stored(self, a, b):
        """The inverse of ``_rotate_to_stored``: the same integer
        quarter turn the other way, which is the same table read
        backwards."""
        turns = (4 - self.quarter_turns % 4) % 4
        if turns == 0:
            return a, b
        if turns == 1:
            return -b, a
        if turns == 2:
            return -a, -b
        return b, -a

    def undistort(self, xd, yd, *, tol=1e-12, max_iter=30):
        """Distorted normalised coordinates -> ideal ones.

        The forward model has no closed form inverse, so this is a
        fixed-point iteration on the SAME expression, in the SAME units
        -- normalised by focal length, about the stored image centre,
        with the principal point already removed. Writing it any other
        way is how a lens model gets transplanted, and this project has
        paid for that once already at ~27 px on the production path.

        Returns (x, y, settled). A pixel outside the calibrated field
        can iterate away rather than settle, so the caller is told
        rather than handed a plausible answer: past the barrel's fold
        radius two object directions produce the same pixel and there
        is no way to choose between them.
        """
        xd = np.asarray(xd, dtype=float)
        yd = np.asarray(yd, dtype=float)
        x, y = xd.copy(), yd.copy()
        step = np.full(np.broadcast(xd, yd).shape, np.inf, dtype=float)
        for _ in range(max_iter):
            r2 = x * x + y * y
            radial = 1.0 + self.k1 * r2 + self.k2 * r2 * r2 \
                + self.k3 * r2 * r2 * r2
            tx = self.p1 * (r2 + 2.0 * x * x) + 2.0 * self.p2 * x * y
            ty = self.p2 * (r2 + 2.0 * y * y) + 2.0 * self.p1 * x * y
            with np.errstate(invalid="ignore", divide="ignore"):
                nx = (xd - tx) / radial
                ny = (yd - ty) / radial
            step = np.maximum(np.abs(nx - x), np.abs(ny - y))
            x, y = nx, ny
            if np.all(np.isfinite(step) & (step < tol)):
                break
        r2 = x * x + y * y
        settled = (np.isfinite(x) & np.isfinite(y) & (step < 1e-9)
                   & (r2 <= self._r_valid * self._r_valid))
        return x, y, settled

    def ray(self, r_cam, col, row):
        """Stored pixels -> unit directions in GROUND space.

        The exact inverse of :meth:`project`, up to the one thing a
        single photograph cannot know, which is how far away the point
        is. Returns ``(direction, usable)``: (N, 3) unit vectors from
        the camera's own origin, and a mask that is False where the
        pixel lies outside the calibrated field or the undistortion did
        not settle. Directions of masked-out pixels are garbage by the
        same contract ``project`` uses.
        """
        col = np.atleast_1d(np.asarray(col, dtype=float))
        row = np.atleast_1d(np.asarray(row, dtype=float))
        xd = (col - (self.width_px - 1) / 2.0 - self.cx_px) / self.focal_px
        yd = (row - (self.height_px - 1) / 2.0 - self.cy_px) / self.focal_px
        x, y, settled = self.undistort(xd, yd)
        a, b = self._rotate_from_stored(x, y)
        # project() formed (a, b) from (u0, -u1) and divided by -u2, so
        # a pixel's camera-frame direction is (a, -b, -1).
        u = np.column_stack([a, -b, -np.ones_like(np.asarray(a, dtype=float))])
        d = u @ np.asarray(r_cam, dtype=float).T
        with np.errstate(invalid="ignore", divide="ignore"):
            d = d / np.linalg.norm(d, axis=1, keepdims=True)
        return d, settled & np.isfinite(d).all(axis=1)

    def project(self, r_cam, origin, xyz):
        """Ground points -> stored pixels through one oriented camera.

        ``r_cam`` is the (3, 3) CAMERA-TO-GROUND rotation whose columns
        are the PHOTO-frame axes in ground space (x right, y up, optical
        axis -z -- what formats.eo builds from Direction/Up), ``origin``
        the (3,) camera position, ``xyz`` the (N, 3) ground points, all
        in one frame and unit.

        Returns (col, row, visible): stored-grid pixel coordinates and a
        mask of points that are in front of the lens AND inside the
        calibrated field. Coordinates of masked-out points are garbage
        by contract -- always index through the mask.
        """
        xyz = np.asarray(xyz, dtype=float)
        u = (xyz - np.asarray(origin, dtype=float)) @ r_cam   # R^T (X - C)
        forward = -u[:, 2]                    # optical axis is -z
        ahead = forward > 1e-12
        z = np.where(ahead, forward, 1.0)
        a, b = self._rotate_to_stored(u[:, 0], -u[:, 1])
        x = a / z
        y = b / z
        r2 = x * x + y * y
        within = ahead & (r2 <= self._r_valid * self._r_valid)
        radial = 1.0 + self.k1 * r2 + self.k2 * r2 * r2 \
            + self.k3 * r2 * r2 * r2
        xd = x * radial + self.p1 * (r2 + 2 * x * x) + 2 * self.p2 * x * y
        yd = y * radial + self.p2 * (r2 + 2 * y * y) + 2 * self.p1 * x * y
        col = (self.width_px - 1) / 2.0 + self.cx_px + self.focal_px * xd
        row = (self.height_px - 1) / 2.0 + self.cy_px + self.focal_px * yd
        return col, row, within

    def contains(self, col, row, margin=1.0):
        """Which (col, row) land inside the stored image, with margin
        enough for bilinear sampling."""
        return ((col >= margin) & (col <= self.width_px - 1 - margin)
                & (row >= margin) & (row <= self.height_px - 1 - margin))


class _NotIniCal(Exception):
    """Looked like an INI calibration and was not."""


def _read_ini_cal(path, text, *, pixel_mm, quarter_turns, name):
    """The ``[Calibration]`` INI that TopoDOT writes beside a flight.

    Same lens model, different spelling, and one real difference: Cx
    and Cy are the principal point measured from the image ORIGIN in
    pixels, while :class:`Camera` wants it as an offset from the image
    CENTRE. Getting that wrong is not subtle -- it is most of the frame
    -- but it is exactly the kind of thing that reads as plausible in
    code and lands the projection in the next county.

    ``dx``/``dy`` are the physical pixel pitch in METRES, which is
    where ``pixel_mm`` comes from when the file states it; the argument
    is only the fallback.
    """
    import configparser

    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise _NotIniCal(str(exc)) from None
    if not parser.has_section("Calibration"):
        raise _NotIniCal("no [Calibration] section")
    section = parser["Calibration"]

    def number(key, required=False):
        if key not in section:
            if required:
                raise ValueError(f"{path.name} lacks {key}; not a TopoDOT "
                                 f"calibration")
            return 0.0
        try:
            return float(section[key])
        except ValueError:
            raise ValueError(
                f"{path.name}: {key} is present but unreadable "
                f"({section[key]!r}). Refusing to silently treat it as "
                f"zero -- a dropped distortion term is tens of pixels at "
                f"the frame corner.") from None

    width = int(number("Nx", required=True))
    height = int(number("Ny", required=True))
    if width <= 0 or height <= 0:
        raise ValueError(f"{path.name}: image size {width}x{height}")
    pitch_m = number("dx")
    return Camera(
        focal_px=number("fx", required=True), width_px=width,
        height_px=height,
        cx_px=number("Cx") - (width - 1) / 2.0,
        cy_px=number("Cy") - (height - 1) / 2.0,
        k1=number("k1"), k2=number("k2"), k3=number("k3"),
        p1=number("P1"), p2=number("P2"),
        quarter_turns=quarter_turns,
        pixel_mm=pitch_m * 1000.0 if pitch_m > 0 else pixel_mm,
        name=name or path.stem)


def read_cal(path, *, pixel_mm=TRUEVIEW_PIXEL_MM, quarter_turns=3,
             name=None):
    """A TrueView/Agisoft ``.cal`` sidecar -> Camera.

    Values are kept in the sidecar's own units (see the module
    docstring), so there is no transplant to get wrong. A key that is
    ABSENT defaults to zero -- a sidecar may legitimately omit a term
    it did not fit -- but a key that is PRESENT and unreadable refuses
    by name: silently zeroing K1 alone is a ~70 px error at the frame
    corner on the Summerville camera, which is precisely the
    uncalibrated projection the CLI refuses to make.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if text.lstrip().startswith("["):
        # Two different files wear the .cal suffix on this hardware.
        # The JSON one is what Summerville shipped; the INI one is what
        # TopoDOT writes beside a TrueView flight, and the difference is
        # not cosmetic -- it names its keys differently and states the
        # principal point from the image ORIGIN rather than its centre.
        # Reading the wrong one as the other is a 2,700 px error, so the
        # first character decides and neither is guessed at.
        try:
            return _read_ini_cal(path, text, pixel_mm=pixel_mm,
                                 quarter_turns=quarter_turns, name=name)
        except _NotIniCal:
            pass
    data = json.loads(text)
    if isinstance(data, list):
        if not data:
            raise ValueError(f"{path.name} holds an empty calibration list")
        if len(data) > 1:
            raise ValueError(
                f"{path.name} holds {len(data)} calibrations; this reader "
                f"describes one camera and will not guess which. Split the "
                f"sidecar, or pass the camera's own file with --cal.")
        data = data[0]
    try:
        focal_px = float(data["CalibratedFocalLength"])
        width = int(data["ImageWidth"])
        height = int(data["ImageHeight"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            f"{path.name} lacks a readable CalibratedFocalLength/"
            f"ImageWidth/ImageHeight; not a TrueView calibration "
            f"sidecar") from None

    def value(key):
        if key not in data:
            return 0.0
        try:
            return float(data[key])
        except (TypeError, ValueError):
            raise ValueError(
                f"{path.name}: {key} is present but unreadable "
                f"({data[key]!r}). Refusing to silently treat it as zero -- "
                f"a dropped distortion term is tens of pixels at the frame "
                f"corner.") from None

    return Camera(
        focal_px=focal_px, width_px=width, height_px=height,
        cx_px=value("CalibratedCX"), cy_px=value("CalibratedCY"),
        k1=value("CalibratedK1"), k2=value("CalibratedK2"),
        k3=value("CalibratedK3"),
        p1=value("CalibratedP1"), p2=value("CalibratedP2"),
        quarter_turns=quarter_turns, pixel_mm=pixel_mm,
        name=name or path.stem)


def find_cal(image_path):
    """The calibration sidecar for one image.

    LP360 writes ``<image>.cal`` beside every frame, so THAT file is
    the answer whenever it exists: taking the first sidecar in the
    folder instead hands a flattened multi-camera delivery one lens for
    all three (measured by the review panel: the port camera silently
    inherited the nadir focal length). The folder-wide fallback stays
    for deliveries that ship a single sidecar, and only searches beside
    the image itself.
    """
    image_path = Path(image_path)
    exact = image_path.with_name(image_path.name + CAL_SUFFIX)
    if exact.is_file():
        return exact
    stem = image_path.with_suffix(CAL_SUFFIX)
    if stem.is_file():
        return stem
    folder = image_path if image_path.is_dir() else image_path.parent
    if folder.is_dir():
        candidates = sorted(p for p in folder.iterdir()
                            if p.is_file() and p.suffix.lower() == CAL_SUFFIX)
        if len(candidates) > 1:
            names = ", ".join(p.name for p in candidates)
            raise ValueError(
                f"no image-specific calibration for {image_path.name}; "
                f"multiple .cal files beside it ({names}). Refusing to "
                f"choose a camera calibration by filename order. Supply "
                f"the image's own sidecar or an explicit --cal file.")
        if candidates:
            return candidates[0]
    return None
