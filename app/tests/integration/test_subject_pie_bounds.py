"""Guard pie geometry against Streamlit's legend-reduced plot dimensions."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dlrag.ui.library import DOMAINS

APP = Path(__file__).parents[2] / 'src/dlrag/ui/app.py'


def render_collection(monkeypatch, counts):
    documents = [dict(doc_id=f'{domain}-{i}', title=f'Document {i}', authors=[],
                      topics=[domain], year=2025, status='ready')
                 for domain, count in zip(DOMAINS, counts) for i in range(count)]
    def local_api(base, method, path, **kwargs):
        assert method == 'GET'
        if path == '/health':
            return {'status':'ready', 'mode':'mock'}
        assert path.startswith('/documents')
        return {'documents':documents}
    monkeypatch.setattr('dlrag.ui.client.call_api', local_api)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    charts = app.get('vega_lite_chart')
    return app, json.loads(charts[0].proto.spec) if charts else None


@pytest.mark.parametrize('plot_width,plot_height', [(455,211), (165,211), (340,340), (180,300), (2,2)])
def test_pie_stroke_fits_inside_available_plot(monkeypatch, plot_width, plot_height):
    # 455x211 and 165x211 are real legend-reduced plot sizes from the old browser UI.
    _, spec = render_collection(monkeypatch, (1,1,1))
    outer = spec['mark'].get('outerRadius', spec['mark'].get('radius'))
    if isinstance(outer, dict):
        # The emitted Vega expression uses min/max and arithmetic, shared by Python.
        radius = eval(outer['expr'], {'__builtins__':{}},
                      {'min':min, 'max':max, 'width':plot_width, 'height':plot_height})
    else:
        radius = outer
    assert radius is not None
    stroke = spec['mark']['strokeWidth']
    assert 0 <= radius <= 140
    assert radius + stroke / 2 <= min(plot_width, plot_height) / 2
    assert radius >= min(140, min(plot_width, plot_height) / 2) - stroke


@pytest.mark.parametrize('counts', [(1,1,1), (3,0,0), (18,1,0)])
def test_pie_keeps_counts_palette_and_existing_layout(monkeypatch, counts):
    app, spec = render_collection(monkeypatch, counts)
    assert [metric.value for metric in app.metric] == [f'{sum(counts)} 篇', *[f'{n} 篇' for n in counts]]
    assert spec['mark']['type'] == 'arc' and spec['height'] == 340
    color = spec['encoding']['color']
    assert color['scale'] == {'domain':list(DOMAINS), 'range':['#247f87','#e9aa58','#8072b2']}
    assert color['legend']['orient'] == 'bottom'
    assert not (color['legend'].get('title') or '').strip()
    assert spec['encoding']['theta'] == {'field':'篇数', 'type':'quantitative'}
    # Data may be moved into Arrow by Streamlit; metrics and palette retain all categories.
    assert [radio.label for radio in app.sidebar.radio] == ['功能', '馆藏导航']
    assert app.selectbox[0].label == '浏览所属学科'


def test_empty_collection_retains_existing_message_without_pie(monkeypatch):
    app, spec = render_collection(monkeypatch, (0,0,0))
    assert spec is None
    assert any('暂无已分类文献' in item.value for item in app.info)
