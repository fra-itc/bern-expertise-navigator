"""Only explicit raster uploads are accepted as company branding."""
import base64
from io import BytesIO
from PIL import Image

def validate_logo(value):
    if not value:
        return ''
    try:
        prefix, encoded = value.split(',', 1)
        if prefix not in ('data:image/png;base64', 'data:image/jpeg;base64'):
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as im:
            if im.format not in ('PNG', 'JPEG') or im.width * im.height > 4000000:
                raise ValueError()
            im.load()
            im.thumbnail((600, 300))
            output = BytesIO()
            im.convert('RGBA').save(output, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
    except Exception as exc:
        raise ValueError('Upload a valid PNG or JPEG logo, up to 4 megapixels.') from exc
