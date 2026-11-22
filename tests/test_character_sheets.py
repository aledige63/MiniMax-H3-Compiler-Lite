"""Schede neutre con la stessa persona e disposizioni diverse, senza file utente."""
import io
import json
import unittest
from unittest.mock import Mock

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.analysis import encoded_image, infer
from app.image_profiles import DEFAULTS, LEVELS, SHEET_INSTRUCTION, analysis_instruction


LAYOUTS = ('classic', 'wide_turnaround', 'three_panel', 'nine_panel', 'seven_panel', 'mixed_mosaic')


def character_sheet(layout):
    """Fixture disegnata: uomo adulto vestito, giacca verde con scritta sul retro."""
    size = (1200, 720)
    if layout == 'classic':
        boxes = [(0, 0, 400, 720)] + [(400 + 200 * i, 0, 600 + 200 * i, 720) for i in range(4)]
    elif layout == 'wide_turnaround':
        boxes = [(240 * i, 0, 240 * (i + 1), 720) for i in range(5)]
    elif layout == 'three_panel':
        boxes = [(400 * i, 0, 400 * (i + 1), 720) for i in range(3)]
    elif layout == 'mixed_mosaic':
        size = (1200, 900)
        boxes = [(0, 0, 330, 600), (330, 0, 620, 600), (620, 0, 910, 600),
                 (910, 0, 1200, 300), (910, 300, 1200, 600),
                 (0, 600, 300, 900), (300, 600, 600, 900),
                 (600, 600, 900, 900), (900, 600, 1200, 900)]
    elif layout in {'nine_panel', 'seven_panel'}:
        columns = 4 if layout == 'nine_panel' else 3
        width = 800 // columns
        boxes = [(0, 0, 400, 720)] + [(400 + width * i, 360 * row, 400 + width * (i + 1), 360 * (row + 1))
                                     for row in range(2) for i in range(columns)]
    else:
        raise ValueError(layout)
    image = Image.new('RGB', size, '#e8e8e8')
    font = ImageFont.load_default(size=36)
    for index, box in enumerate(boxes):
        tile = Image.new('RGB', (400, 700), 'white')
        draw = ImageDraw.Draw(tile)
        back = index == 1
        draw.rectangle((132, 230, 268, 455), fill='#247340', outline='#143d24', width=4)
        draw.polygon([(132, 235), (100, 250), (75, 420), (115, 430), (150, 300)], fill='#247340')
        draw.polygon([(268, 235), (300, 250), (325, 420), (285, 430), (250, 300)], fill='#247340')
        draw.ellipse((75, 410, 115, 455), fill='#e5b28c'); draw.ellipse((285, 410, 325, 455), fill='#e5b28c')
        draw.rectangle((150, 455, 195, 620), fill='#2d4e7a'); draw.rectangle((205, 455, 250, 620), fill='#2d4e7a')
        draw.rectangle((137, 620, 195, 652), fill='#ba6024'); draw.rectangle((205, 620, 263, 652), fill='#ba6024')
        draw.rectangle((178, 205, 222, 240), fill='#e5b28c')
        draw.ellipse((145, 82, 255, 218), fill='#e5b28c', outline='#6f452f', width=3)
        draw.pieslice((144, 75, 256, 180), 180, 360, fill='#352b26')
        if back:
            draw.ellipse((145, 80, 255, 207), fill='#352b26')
            draw.text((200, 315), 'BIRCH', font=font, fill='white', anchor='mm')
        else:
            draw.pieslice((151, 130, 249, 216), 0, 180, fill='#ad4b22')
            draw.ellipse((162, 132, 193, 158), outline='black', width=5)
            draw.ellipse((207, 132, 238, 158), outline='black', width=5)
            draw.line((193, 143, 207, 143), fill='black', width=4)
            draw.line((200, 235, 200, 450), fill='#143d24', width=4)
        if index == len(boxes) - 1:
            tile = tile.crop((120, 65, 280, 235))  # Un dettaglio facciale anche nelle righe inferiori.
        width, height = box[2] - box[0], box[3] - box[1]
        fitted = ImageOps.contain(tile, (width - 12, height - 12))
        image.paste(fitted, (box[0] + (width - fitted.width) // 2, box[1] + (height - fitted.height) // 2))
        ImageDraw.Draw(image).rectangle(box, outline='#626262', width=3)
    output = io.BytesIO(); image.save(output, format='PNG')
    return output.getvalue()


class CharacterSheetTests(unittest.TestCase):
    def test_all_layouts_use_the_entire_picture_in_one_request(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                content = character_sheet(layout)
                client = Mock(keep_alive='0')
                client._request.return_value = dict(done=True, done_reason='stop', message=dict(content=json.dumps(
                    dict(description='A man with round glasses and a reddish beard wears a green jacket with "BIRCH" printed on the back.'))))
                result = infer(client, 'image_character_sheet', 'vision-test', 'digest', 'hash', role='identity',
                               content=content, analysis=dict(DEFAULTS, category='character', level='medium'))
                self.assertEqual(result.status, 'proposal')
                self.assertEqual(result.metrics.inference_calls, 1)
                client._request.assert_called_once()
                request = client._request.call_args.args[1]
                self.assertEqual(request['messages'][-1]['images'], [encoded_image(content)])
                self.assertTrue(request['messages'][0]['content'].startswith(SHEET_INSTRUCTION))
                self.assertEqual(set(request['format']['properties']), {'description'})

    def test_layout_guidance_is_independent_of_selected_level(self):
        for level in LEVELS:
            prompt = analysis_instruction(dict(DEFAULTS, category='character', level=level), '', sheet=True)
            for expected in ['ALL visible regions', 'lower rows and close-ups', 'no fixed panel count',
                             'not separate characters', 'ONE unified appearance description',
                             'Every sentence must describe the person', 'one coherent portrait',
                             'Panel numbers, captions, borders', 'printed on a garment']:
                with self.subTest(level=level, expected=expected): self.assertIn(expected, prompt)
            self.assertNotIn('Supported arrangements',prompt)

    def test_single_picture_analysis_does_not_assert_a_character_sheet(self):
        prompt = analysis_instruction(dict(DEFAULTS, category='character'), '', sheet=False)
        self.assertNotIn(SHEET_INSTRUCTION, prompt)
        self.assertNotIn('Nine-panel', prompt)


if __name__ == '__main__': unittest.main()
