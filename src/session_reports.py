"""Session analysis and report orchestration, independent of the HUD."""
import endurance
import reporting
from app_config import ROOT
from laps import export_fastest, library_laps, track_script, write_compare
from paths import ASSETS
from sessionlab import analyze_session


@reporting.serialized
def make_report(folder):
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
    render_review(folder, fastest)


def render_review(folder, fastest=None):
    """Upgrade a review page without rewriting its CSV or lap exports."""
    reporting.render_review(folder,ASSETS,track_script(ASSETS),fastest)
