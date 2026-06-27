from app.geo import bbox_dims_m, polygon_area_m2

# прямоугольник в Алматы (~43.24 ш.): 0.001° долготы × 0.0005° широты
RECT = {"type": "Polygon", "coordinates": [[
    [76.900, 43.2400], [76.901, 43.2400], [76.901, 43.2405], [76.900, 43.2405], [76.900, 43.2400],
]]}


def test_bbox_dims_returns_length_ge_width_in_meters():
    length, width = bbox_dims_m(RECT)
    # долгота: 0.001 * 111320 * cos(43.24°) ≈ 81 м; широта: 0.0005 * 111320 ≈ 55.7 м
    assert 70 <= length <= 90
    assert 50 <= width <= 62
    assert length >= width


def test_polygon_area_matches_length_times_width():
    length, width = bbox_dims_m(RECT)
    area = polygon_area_m2(RECT)
    assert abs(area - length * width) < 0.15 * (length * width)


from app.geo import point_in_polygon

SQUARE = {"type": "Polygon", "coordinates": [[
    [76.90, 43.24], [76.91, 43.24], [76.91, 43.25], [76.90, 43.25], [76.90, 43.24]]]}
MULTI = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}


def test_point_in_polygon_inside_and_outside():
    assert point_in_polygon(76.905, 43.245, SQUARE) is True
    assert point_in_polygon(76.80, 43.20, SQUARE) is False


def test_point_in_polygon_multipolygon():
    assert point_in_polygon(76.905, 43.245, MULTI) is True
    assert point_in_polygon(76.95, 43.30, MULTI) is False
