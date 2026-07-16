import json
import os
import sys
sys.path.insert(0, os.environ.get("IAB_EPISODE_REPOSITORY", "repository"))
from repository.adapter import Device


def main():
    out=[]
    a=Device(); e=[]; a.acquire(e.append, timeout=10); out.append({"id":"per_device_timeout","passed":all(x in e for x in ["acquire","timeout:device","abort"]),"events":e})
    a=Device(); e=[]; a.acquire(e.append); a.abort(e.append); a.acquire(e.append, second=True); out.append({"id":"abort_releases_lease","passed":all(x in e for x in ["acquire","abort","lease:released","acquire:second"]),"events":e})
    a=Device(); e=[]; a.acquire(e.append); a.shutdown(e.append); out.append({"id":"shutdown_pending","passed":all(x in e for x in ["acquire","shutdown","lease:released","closed"]),"events":e})
    print("IAB_EPISODE_RESULTS="+json.dumps({"scenarios":out}))
if __name__ == "__main__": main()
