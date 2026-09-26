"""Point d'entrée de l'application empaquetée (PyInstaller)."""

import sys

from sp500_analyzer.app.main import main

sys.exit(main())
