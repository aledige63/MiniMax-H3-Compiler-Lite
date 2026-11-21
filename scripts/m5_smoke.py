"""M5: prove sintetiche sequenziali, una inferenza per caso, nessun workflow H3."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw
from app.analysis import infer, installed_model
from app.domain import CompileInput
from app.interpreter import OllamaClient, DEFAULT_TEXT_MODEL, SYSTEM_PROMPT


class RecordedClient(OllamaClient):
    """Solo collaudo sintetico: conserva l'output senza tentare riparazioni."""
    raw_output = None

    def _request(self, path, body=None):
        result = super()._request(path, body)
        if path == '/api/chat':
            self.raw_output = result.get('message', {}).get('content')
        return result


def base():
    return dict(request='<Subject 1> guarda la camera.',declared_duration_s=8.0,pictures=[dict(id='face',slot=1,name='Ann',role='identity',description_en='a young woman with brown hair',confirmed=True,linked_to_h3=True)],active_units=[dict(subject=1,name='Ann',role='character',description_en='Ann',confirmed=True,sources=[dict(picture_id='face',attribute='identity')])])


def guide_picture(id,slot,role,description,**guidance):
    return dict(id=id,slot=slot,role=role,description_en=description,confirmed=True,linked_to_h3=True,guidance=dict(enabled=True,**guidance))


def cases():
    chosen=base();chosen['camera']=dict(framing='american',angle='dutch',movement='push_in',amplitude='small',speed='slow',subject=1)
    timed=base();timed['request']='<Subject 1> pronuncia d1, poi cammina verso la porta.';timed['dialogues']=[dict(id='d1',text='Eccomi.',language='Italian',speaker_subject=1,confirmed=True)];timed['camera']=dict(framing='full',movement='tracking',subject=1,placement='after_dialogue',dialogue_id='d1')
    combined=base();combined['request']='<Subject 1> cammina attraverso la stanza.';combined['videos']=[dict(id='v1',slot=1,role='camera_and_subject_motion',description_en='a camera and Subject motion reference',duration_s=5.0,confirmed=True,linked_to_h3=True,file_exists=True,guidance=dict(enabled=True,mappings=[dict(figure='the mannequin',role='motion',subject=1)],prompt_en='Preserve the guide movement rhythm.'))]
    composed=base();composed['request']='<Subject 1> parte dalla posizione indicata e cammina verso destra.';composed['pictures'] += [guide_picture('composition',2,'initial_composition','one simplified figure on the left',mappings=[dict(figure='the left figure',subject=1)]),guide_picture('style',3,'style','a restrained ink illustration',prompt_en='Use broad ink strokes on plain paper.')]
    anchor=base();anchor['request']='<Subject 1> si volta verso sinistra e raggiunge il frame finale indicato.';anchor['pictures'].append(guide_picture('last',2,'frame_anchor','the same woman facing left',anchor='last',workflow='external Ref2VA last-frame workflow'))
    conflict=base();conflict['request']='La camera segue <Subject 1> mentre cammina, in un tracking shot.';conflict['camera']=dict(movement='static',placement='throughout')
    return [('camera_choices',chosen,'proposal'),('camera_after_dialogue',timed,'proposal'),('combined_guide',combined,'proposal'),('composition_and_style',composed,'proposal'),('last_frame_anchor',anchor,'proposal'),('camera_conflict',conflict,'clarification_needed')]


def fixture(role):
    image=Image.new('RGB',(640,360),'#faf7ed');draw=ImageDraw.Draw(image)
    if role=='spatial_map':
        draw.rectangle((40,30,600,330),outline='#333333',width=5);draw.ellipse((110,210,150,250),fill='#c43030');draw.line((170,230,430,150),fill='#204ca4',width=8);draw.polygon([(430,150),(403,150),(420,174)],fill='#204ca4');draw.text((90,270),'RED CIRCLE',fill='#111111');draw.text((420,110),'BLUE ARROW',fill='#111111')
    else:
        for n in range(5):draw.line((80,70+n*40,560,110+n*28),fill='#293a4b',width=9-n)
    output=io.BytesIO();image.save(output,'PNG');return output.getvalue()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);parser.add_argument('--output',type=Path,default=Path('benchmark-runs/m5-real.json'));parser.add_argument('--vision',action='store_true');parser.add_argument('--vision-model');parser.add_argument('--case',action='append',choices=[name for name,_,_ in cases()]);args=parser.parse_args()
    if args.vision and not args.vision_model:
        parser.error('--vision requires --vision-model')
    client=RecordedClient();report=dict(model=args.model,system_prompt_sha256=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),note='Fixture sintetiche. Una chiamata per caso; nessuna generazione H3 o analisi video.',runs=[]);args.output.parent.mkdir(parents=True,exist_ok=True)
    failed=False
    for case,raw,expected in cases():
        if args.case and case not in args.case:continue
        data=CompileInput.model_validate(raw);result=client.compile(data,args.model)
        errors=[]
        if result.status!=expected:errors.append('unexpected status')
        if result.metrics.inference_calls!=1:errors.append('call count')
        if result.status=='proposal':
            prompt=result.prompt;narrative=result.interpretation.narrative_en
            if 'On-screen speech' in prompt or 'line ends' in narrative:errors.append('speech regression')
            for ref in [*data.active_picture_guides,*data.active_video_guides]:
                if ref.guidance.prompt_en and prompt.count(ref.guidance.prompt_en)!=1:errors.append('verbatim guide count')
            if case=='camera_choices' and not all(word in narrative.lower() for word in ['dutch','knees','push','slow']):errors.append('camera selection omitted')
            if case=='camera_after_dialogue' and (narrative.find('{{dialogue:d1}}')>narrative.lower().find('track') or '<d>[Italian] Eccomi.</d>.' not in prompt):errors.append('camera timing or dialogue')
            if case=='combined_guide' and ('video continuation' in prompt or 'Use the camera movement and mapped Subject motion from <Video 1>.' not in prompt):errors.append('guide scope')
            if case=='last_frame_anchor' and 'The shot ends on <Picture 2>.' not in prompt:errors.append('anchor missing')
        failed |= bool(errors)
        report['runs'].append(dict(case=case,expected=expected,input=data.model_dump(mode='json'),result=result.model_dump(mode='json'),raw_output=client.raw_output,checks=errors));args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(case=case,status=result.status,errors=errors,narrative=result.interpretation.narrative_en if result.interpretation else None,question=result.interpretation.question if result.interpretation else None,wall_s=result.metrics.wall_s),ensure_ascii=False),flush=True)
    if args.vision:
        model=installed_model(client,args.vision_model,'vision');report['vision']=[]
        for role in ['spatial_map','style']:
            content=fixture(role);result=infer(client,'image_analyze',args.vision_model,model['digest'],hashlib.sha256(content).hexdigest(),content=content,role=role)
            report['vision'].append(dict(role=role,result=result.model_dump(mode='json')));args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            failed |= result.status!='proposal';print(json.dumps(dict(vision=role,status=result.status,text=result.text),ensure_ascii=False),flush=True)
    return int(failed)


if __name__=='__main__':raise SystemExit(main())
