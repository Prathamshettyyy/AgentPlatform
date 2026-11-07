"""Verified source facts for Soil Report 25-0117 (AmeriKor, February 20, 2025).

Every value in this module was checked against the original PDF text (not against a previously
generated AI report).  The Requirement Agent uses these page references so that each
GEOTECHNICAL_SOURCE_REQUIREMENT can be traced to the exact PDF page *and* printed report page.

PDF page = physical page in the PDF file; Report page = printed folio ("Amerikor Project No. 25-0117 - N -").
For this document PDF page = Report page + 4 (e.g. PDF 7 = Report 3, PDF 14 = Report 10).
"""

from __future__ import annotations

SOURCE_REPORT_LABEL = "Soil report 25-0117 v1.pdf (AmeriKor Project No. 25-0117, February 20, 2025)"

PAGES = {
    "site_prep": "PDF pp. 7-8 (Report pp. 3-4), Sec. 1.3.1",
    "pt_slab": "PDF pp. 8-9 (Report pp. 4-5), Sec. 1.3.2",
    "piers": "PDF pp. 9-10 (Report pp. 5-6), Sec. 1.3.2",
    "pier_bearing": "PDF p. 10 (Report p. 6), Sec. 1.3.2",
    "footings": "PDF pp. 11-12 (Report pp. 7-8), Sec. 1.3.2",
    "slab_floor": "PDF pp. 11-12 (Report pp. 7-8), Sec. 1.3.2",
    "groundwater": "PDF p. 7 (Report p. 3), Sec. 1.2.2; PDF p. 13 (Report p. 9), Sec. 4.2",
    "pvr": "PDF p. 7 (Report p. 3), Sec. 1.2.3",
    "construction": "PDF p. 14 (Report p. 10), Sec. 5.1",
    "drainage": "PDF p. 14 (Report p. 10), Sec. 5.2",
}

# Allowable net bearing pressures exactly as printed in the soil report.
PIER_BEARING_DL_SLL_PSF = 2000
PIER_BEARING_TOTAL_PSF = 3000
FOOTING_BEARING_DL_SLL_PSF = 1800
FOOTING_BEARING_TOTAL_PSF = 2700
PT_BEARING_DL_SLL_PSF = 1400
PT_BEARING_TOTAL_PSF = 2100
SLAB_FLOOR_BEARING_PSF = 600
PIER_SHAFT_FRICTION_PSF = 300
FOOTING_MIN_EMBEDMENT_FT = 2.5
PT_GRADE_BEAM_MIN_DEPTH_FT = 1.5
PIER_FOUNDING_DEPTH_FT = 10.0
PIER_MAX_BELL_DIAMETER_FT = 5.0
PIER_MAX_BELL_TO_SHAFT_RATIO = 3
PIER_MIN_CC_SPACING_BELL_DIAMETERS = 1.5
PT_SELECT_FILL_MIN_FT = 1.0
FOOTING_SELECT_FILL_MIN_FT = 2.0
SLAB_FLOOR_SELECT_FILL_MIN_FT = 2.0
SELECT_FILL_EXTENT_BEYOND_FT = 5

GROUNDWATER_TEXT = (
    "Groundwater was encountered at 15.4 ft (B-1) and 14.5 ft (B-2) during drilling and measured at "
    "14.8 ft and 14.0 ft respectively within 15 minutes after drilling."
)

DRAINAGE_TEXT = "minimum slope of 6 inches in the first 10 feet"

EXTERNAL_VOID_FORM_NOTE = (
    "EXTERNAL ENGINEERING CONSIDERATION (not specified in the geotechnical report): carton void forms "
    "beneath grade beams are a general industry practice on expansive clay. The geotechnical report does "
    "not require them and does not give a void dimension; it states that grade beams on drilled piers may be "
    "formed directly on the subgrade soils. Whether to use void forms, and their dimension, is a Structural "
    "Engineer decision that must be confirmed by the Geotechnical Engineer."
)

# Phrases that must never be presented as geotechnical-report requirements.
UNSUPPORTED_AS_GEOTECH_REQUIREMENT = (
    "carton void",
    "3,600 psf",
    "5,400 psf",
    "1,600 psf",
    "2,400 psf",
)
