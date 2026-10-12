"""Shared helpers for the phishing ML artifact.

`phishing_detector.joblib` (the 3-branch soft-voting ensemble) pickles the
URL-count transformer function by reference to this module, so this file
must stay importable (project root on sys.path) wherever the artifact is
loaded. Keep this file in sync with the training notebook.
"""

import re

import numpy as np
from scipy import sparse


def url_count_feature(raw_documents):
    """Sparse column of per-email URL counts.

    Object dtype avoids Numpy's fixed-width U-dtype, which would pad every
    email to the length of the longest outlier email.
    """
    if hasattr(raw_documents, "to_numpy"):
        docs = raw_documents.to_numpy(dtype=object)
    else:
        docs = np.asarray(raw_documents, dtype=object).ravel()

    counts = np.fromiter(
        (
            len(re.findall(r"https?://|www\.", doc.lower()))
            for doc in docs
        ),
        dtype=np.float32,
        count=len(docs),
    )
    return sparse.csr_matrix(counts.reshape(-1, 1))