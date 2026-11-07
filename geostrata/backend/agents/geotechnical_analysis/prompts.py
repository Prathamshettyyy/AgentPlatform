from __future__ import annotations

GEOTECHNICAL_SYSTEM_PROMPT = """You are a senior geotechnical engineering AI assistant.
Your role is to interpret structured document intelligence data from geotechnical soil investigation reports and synthesize an evidence-grounded engineering evaluation.

MANDATORY RULES:
1. EVIDENCE GROUNDING: Every finding, measurement, and parameter must reference real evidence IDs provided in the context. NEVER invent evidence IDs.
2. DISTINGUISH FACTS FROM INTERPRETATION: Clearly separate what was measured and recorded by the geotechnical consultant from engineering inferences or commentary.
3. NO FINAL DESIGN APPROVAL: You are an advisory engineering-assistance tool. You must not claim to approve, certify, or finalize foundation designs.
4. HONEST UNCERTAINTY: If data is missing (e.g. SPT blow counts, structural column loads, drainage plan), explicitly state that it was not reported or is missing. Never treat missing numbers as zero.
5. FOUNDATION VS FLOOR SLABS: Strictly distinguish the slab-on-grade interior floor recommendation (which requires 2 ft select fill and provides 600 psf net bearing) from post-tensioned foundation slabs (which specify 2,100 psf / 1,400 psf on 1 ft select fill).
6. DISCREPANCY DETECTION: Flag any inconsistencies in project name, lot description, site address, or date across documents.
"""

SOIL_ANALYSIS_PROMPT = """Based on the following extracted geotechnical subsurface and laboratory data:

Project Context:
{project_info}

Boring Logs and Strata:
{boring_logs}

Laboratory Test Results:
{lab_results}

Groundwater Measurements:
{groundwater_info}

Synthesize a comprehensive interpretation of the subsurface soil conditions and laboratory properties:
1. Identify the dominant USCS classification and consistency across all exploratory borings.
2. Characterize the moisture content, plasticity index, liquid limit, and % passing #200 sieve.
3. Evaluate the Potential Vertical Rise (PVR) and discuss shrink-swell hazards.
4. Note presence of calcareous nodules, soil color variations, and depth observations.
5. Summarize groundwater encounter depths during drilling and post-drilling stabilization.
6. Note whether Standard Penetration Testing (SPT) was performed or if continuous flight auger drilling was used.
"""

FOUNDATION_ANALYSIS_PROMPT = """Based on the extracted foundation systems and design parameters:

Extracted Systems:
{foundation_systems}

Site & Subgrade Preparation Requirements:
{site_prep}

Synthesize an engineering comparison of the foundation options:
1. Detail Post-Tensioned Slabs, Drilled Underreamed Piers, Continuous Footings/Grade Beams, and Separate Slab-on-Grade Floor.
2. Specify allowable bearing pressures, load cases, factors of safety, and required select fill pad thicknesses for each.
3. Detail Drilled Underreamed Pier parameters: depth (~10 ft), bell/shaft ratio (max 3), spacing (>= 1.5 x bell), and critical caving / groundwater construction warnings.
4. Explicitly explain why Slab-on-Grade Floor is an interior floor slab recommendation, NOT an independent foundation system.
5. Construct a structured comparison matrix comparing bearing capacity, settlement control, constructability/caving risk, and suitability for expansive clay.
"""

RISKS_AND_MISSING_PROMPT = """Based on the extracted geotechnical findings:

Soil Conditions:
{soil_conditions}

Foundation Systems:
{foundation_systems}

Site Preparation:
{site_prep}

Perform a rigorous risk and missing information assessment:
1. Identify all geotechnical and constructability risks supported by evidence (e.g. expansive lean clay shrink-swell, pier bell caving, groundwater table elevation, foundation settlement).
2. Explicitly enumerate all missing information necessary for complete project-specific foundation engineering (e.g. column/wall structural loads, architectural layout, proposed finished floor elevations, site grading and surface drainage plan, confirmed legal property description).
3. Formulate targeted, professional questions for the Geotechnical Engineer and Structural Engineer.
"""

