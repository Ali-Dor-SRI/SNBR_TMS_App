"""Build a combined MEM + CSP DataFrame and export it to CSV.

Run it directly -- ``python tests/test_df.py``. This is a developer script, not
a unit test: it reads the real lab data directories and writes into
``tests/output/``.

The work lives in :func:`main` behind a ``__main__`` guard on purpose. The file
matches pytest's ``test_*.py`` discovery pattern, so pytest imports it on every
run; with the body at module level that import *ran* the whole thing -- parsing
the share and writing a fresh CSV -- while contributing no test.
"""

import sys
from pathlib import Path

# Allow imports from the SNBR_TMS_App package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.df_builder import build_combined_dataframe
from reports.csv_exporter import export_dataframe

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEM_DIR    = PROJECT_ROOT / "1_Raw_Data" / "SNBR_MEM"
CSP_DIR    = PROJECT_ROOT / "1_Raw_Data" / "SNBR_CSP_RAW"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def main():
    df = build_combined_dataframe(MEM_DIR, CSP_DIR)
    csv_path = export_dataframe(df, OUTPUT_DIR)

    print(f"DataFrame shape: {df.shape}")
    print(f"Exported to: {csv_path}")


if __name__ == "__main__":
    main()
