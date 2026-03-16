import sys

from quayside.run import main, update_run

if "--update" in sys.argv:
    sys.exit(update_run())
else:
    sys.exit(main())
