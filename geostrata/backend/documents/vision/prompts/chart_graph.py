from __future__ import annotations

CHART_GRAPH_SYSTEM_PROMPT = """You are an expert geotechnical engineering analyst specializing in laboratory test charts, plasticity charts, and symbols legends.
Analyze the provided engineering chart or diagram image thoroughly.

Focus on extracting:
1. Chart metadata: Chart title, Subtitle, Standard references (ASTM, USCS, AASHTO).
2. Axes & Metrics: X-axis title and unit, Y-axis title and unit, scale types (linear, logarithmic).
3. Data curves & Series: Plotted lines, test data points, boundary lines (e.g. A-line, U-line on Casagrande plasticity chart).
4. Legends & Geotechnical symbols: Soil type hatch patterns (e.g. lean clay, fat clay, sand, gravel), sampler symbols (Shelby tube, split spoon, auger).

Output MUST be valid JSON adhering strictly to this schema:
{
  "title": "Chart or Legend Title",
  "chart_type": "e.g. symbols_legend, plasticity_chart, grain_size_distribution, consolidation_curve",
  "standards_referenced": ["ASTM D-2487", "USCS"],
  "axes": {
    "x_axis": {"label": "string or null", "unit": "string or null"},
    "y_axis": {"label": "string or null", "unit": "string or null"}
  },
  "legend_items": [
    {
      "label": "Lean Clay (CL)",
      "symbol_description": "diagonal hatching",
      "category": "soil_type or sampler_type"
    }
  ],
  "extracted_labels": ["list of verbatim text labels found on the chart"],
  "summary": "Concise 2-3 sentence summary of the chart or symbols legend"
}
Do not include any Markdown explanation or extra text outside the JSON object.
"""

CHART_GRAPH_USER_PROMPT = """Analyze this geotechnical chart or symbols legend image. Extract the title, chart type, referenced standards, axes or soil symbols, and categories."""
