# Track map display coordinates

The rFactor internals SDK documents a left-handed world frame with positive Y upward. LMU recordings retain the original mPos X/Z values. The previous renderer treated Z directly as screen Y and mirrored the projected circuit. The display now negates the centered vertical coordinate for recorded_world_xz and GPS east/north Mercator trajectories. Reference SVG/PDF points already use screen coordinates and are not reflected.

The same projection handles strokes, S/F, replay vehicles, highlighted corners and hit testing. Rotation changes display orientation only. Sampling, CSV/JSON, lap timing, distance alignment, lateral offsets and calibration format are unchanged. Legacy HTML upgrades replace only the bounded map renderer and preserve all bytes outside it.

Primary SDK: https://www.studio-397.com/modding-resources/ (Example Plugin download, Include/InternalsPlugin.hpp, world coordinate system comment).

Official Sebring reference: https://www.sebringraceway.com/track-maps/ . The existing local catalog records each outline's original source, including official PDF outlines and separately labeled community SVG outlines. No private outlines or report payloads are distributed.

Local validation compared six recorded circuits (Sebring, Long Beach, Monza, Interlagos, Le Mans and Road Atlanta) with their stored sourced outlines. Reflection resolves the handedness discrepancy; rotation may differ between simulation world axes and a published map. The 27 reference layouts retain their original screen orientation. Circuits without recorded fixtures are covered by the coordinate convention, rather than claimed as individually verified game recordings.
