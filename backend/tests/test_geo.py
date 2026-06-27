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
