"""Session analysis and report orchestration, independent of the HUD."""
import endurance
import reporting
from app_config import ROOT
from laps import export_fastest, library_laps, track_script, write_compare
from paths import ASSETS
from sessionlab import analyze_session


@reporting.serialized
def make_report(folder,isolated=None):
    # Portable builds isolate large Python/native heaps; source callers can opt in.
    import sys
    from pathlib import Path
    folder=Path(folder)
    use_worker=getattr(sys,'frozen',False) if isolated is None else isolated
    if use_worker:
        from report_worker import run
        return run(folder,ROOT)
    try:analyze_session(folder)
    except Exception as e:(folder/'analysis_error.txt').write_text(str(e),encoding='utf-8')
    try:endurance.analyze(folder)
    except Exception as e:(folder/'endurance_error.txt').write_text(str(e),encoding='utf-8')
    fastest = None
    try:
        library = folder.parent
        _,fastest = export_fastest(folder,ASSETS/'compare.html',library)
        if library in (ROOT/'Logs',ROOT/'DemoLogs',ROOT/'ImportedLogs'):
            selection = library_laps(library)
            write_compare(ROOT/('DemoFastestLapCompare.html' if library.name=='DemoLogs' else
                               'FastestLapCompare.html'),ASSETS/'compare.html',selection)
    except Exception as error:
        (folder/'fastest_lap_error.txt').write_text(str(error),encoding='utf-8')
    try:render_review(folder, fastest)
    finally:
        # Separate from HTML generation: a review-page failure must not prevent
        # native race images, and an image error must leave existing reports intact.
        try:
            from race_report import generate
            generate(folder)
        except Exception as error:
            from report_worker import ReportDeferred
            if isinstance(error,ReportDeferred):raise
            (folder/'race_images_error.txt').write_text(str(error),encoding='utf-8')


def render_review(folder, fastest=None):
    """Upgrade a review page without rewriting its CSV or lap exports."""
    reporting.render_review(folder,ASSETS,track_script(ASSETS),fastest)
