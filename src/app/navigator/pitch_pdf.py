"""Minimal, linked PDF companion to the interactive pitch; generated on demand."""
from io import BytesIO
import base64
from html import escape

def render(brief):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
    out = BytesIO()
    styles = getSampleStyleSheet()
    brand = brief.get('branding', {})
    accent = brand.get('primary_color', '#c8102e')
    styles['Title'].textColor = colors.HexColor(accent)
    story = [Paragraph(escape(brief['company']), styles['Title']), Paragraph(escape(brief['kicker']), styles['Heading2']), Paragraph(escape(brief['hook']), styles['BodyText']), Spacer(1, 6*mm)]
    logo = brand.get('company_logo')
    if logo:
        image = Image(BytesIO(base64.b64decode(logo.split(',',1)[1])))
        image._restrictSize(60*mm, 25*mm)
        story.insert(0, image)
    if brief.get('objective'):
        story += [Paragraph(escape(brief['objective']), styles['BodyText']), Spacer(1, 4*mm)]
    curated_ids = [node['id'] for node in brief.get('ecosystem', {}).get('nodes', [])]
    by_id = {it['id']: it for it in brief['items']}
    featured = [by_id[i] for i in curated_ids if i in by_id] if curated_ids else brief['items'][:3]
    for item in featured:
        story += [Paragraph(escape(item['name']), styles['Heading2']), Paragraph(escape(item.get('benefit', '')), styles['BodyText'])]
        if item.get('quote'):
            story += [Paragraph(escape(item['quote']['text']), styles['BodyText'])]
        url = escape(item['page'], quote=True)
        story += [Paragraph(f'<link href="{url}" color="{accent}">{url}</link>', styles['BodyText']), Spacer(1, 4*mm)]
    story += [Paragraph(escape(brief['labels']['visit']), styles['Heading2'])]
    story += [Paragraph(escape(line), styles['BodyText']) for line in brief['agenda']]
    if brief.get('sources'):
        story += [Paragraph(escape(brief['labels']['sources']), styles['Heading2'])]
        for source in brief['sources']:
            url = escape(source['url'], quote=True)
            story += [Paragraph(f'<link href="{url}">{escape(source["label"][:180])}</link>', styles['BodyText'])]
    story += [Spacer(1, 5*mm), Paragraph(escape(brief['from']), styles['BodyText'])]
    SimpleDocTemplate(out, pagesize=(210*mm,297*mm), rightMargin=20*mm,leftMargin=20*mm,topMargin=18*mm,bottomMargin=18*mm,invariant=1).build(story)
    return out.getvalue()
