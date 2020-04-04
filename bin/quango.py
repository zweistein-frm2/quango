import sys
from os import path

# Add import path for inplace usage
sys.path.insert(0, path.abspath(path.join(path.dirname(__file__), '..')))

import quango.main

sys.exit(quango.main.main())
