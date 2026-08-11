"""isomap — isometric pixel-art city map generator.

Core libraries (city-agnostic):
- config: city configuration loading
- gridlib: CRS transforms and world-grid <-> quadrant coordinate math
- tilelib: quadrant schema, seam rules, generation window validation, planning
- store: SQLite quadrant state store
"""
