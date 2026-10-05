"""Real driving stays live in every phase; disk recording is Qualify/Race only."""
def should_record(session,demo=False):
    return bool(demo) or isinstance(session,int) and not isinstance(session,bool) and (5<=session<=8 or 10<=session<=13)
