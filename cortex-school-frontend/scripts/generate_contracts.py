"""Extract UI contracts without importing the backend or requiring a database.

Run after backend changes. All public business routes are represented; infrastructure
webhooks and the example endpoint intentionally have no end-user screen.
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / 'cortex-school-backend/app/modules'
definitions = {}
aliases = {}

def literal(node, fallback=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        if isinstance(node, ast.Attribute):
            return node.attr.lower()
        return fallback

def keywords(node):
    return {k.arg: literal(k.value) for k in node.keywords}

trees = {p: ast.parse(p.read_text(encoding='utf-8')) for p in MODULES.rglob('*.py') if p.name in ('schemas.py', 'models.py', 'router.py') or p.parent.name == 'routes'}
for path, tree in trees.items():
    for n in tree.body:
        if isinstance(n, ast.ClassDef):
            if any(ast.unparse(b) in ('StrEnum', 'str, Enum') for b in n.bases):
                definitions[n.name] = {'type': 'string', 'enum': [literal(v.value) for v in n.body if isinstance(v, ast.Assign)]}
            elif any('BaseModel' in ast.unparse(b) or ast.unparse(b).endswith('Response') for b in n.bases):
                definitions[n.name] = n
        elif isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Subscript):
            aliases[n.targets[0].id] = n.value

def schema(node, seen=()):
    if node is None:
        return {'type':'string'}
    name = ast.unparse(node)
    if isinstance(node, ast.BinOp):
        opts = []
        def flatten(v):
            if isinstance(v, ast.BinOp):
                flatten(v.left); flatten(v.right)
            else:
                opts.append(v)
        flatten(node)
        nonnull = [x for x in opts if not (isinstance(x, ast.Constant) and x.value is None)]
        if len(nonnull) == 1:
            return {**schema(nonnull[0], seen), 'nullable':len(nonnull)!=len(opts)}
        return {'oneOf':[schema(x, seen) for x in nonnull]}
    if isinstance(node, ast.Subscript):
        kind = ast.unparse(node.value)
        args = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if kind == 'Annotated':
            result = schema(args[0], seen)
            for extra in args[1:]:
                if isinstance(extra, ast.Call):
                    result.update({k:v for k,v in keywords(extra).items() if k in ('min_length','max_length','pattern','ge','le') and v is not None})
                    if keywords(extra).get('discriminator'):
                        result['discriminator'] = keywords(extra)['discriminator']
            return result
        if kind == 'Literal':
            return {'type':'string','enum':[literal(x) for x in args]}
        if kind == 'list':
            return {'type':'array','items':schema(args[0],seen)}
        if kind == 'dict':
            return {'type':'object','additionalProperties':schema(args[-1],seen)}
    if name in aliases and name not in seen:
        return schema(aliases[name], (*seen,name))
    if name in definitions and name not in seen:
        obj = definitions[name]
        if isinstance(obj, dict):
            return obj
        props = {}
        for base in obj.bases:
            inherited = schema(base, (*seen,name))
            props.update(inherited.get('properties',{}))
        for field in obj.body:
            if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name):
                value = schema(field.annotation,(*seen,name))
                value['required'] = field.value is None
                if field.value is not None:
                    default = literal(field.value)
                    if isinstance(field.value, ast.Call):
                        kw = keywords(field.value)
                        value['required'] = 'default' not in kw and 'default_factory' not in kw
                        default = kw.get('default')
                        value.update({k:v for k,v in kw.items() if k in ('min_length','max_length','ge','le') and v is not None})
                    if default is not None:
                        value['default'] = default
                props[field.target.id] = value
        return {'type':'object','properties':props,'name':name}
    types = {'int':'integer','float':'number','bool':'boolean','date':'string','datetime':'string','time':'string','uuid.UUID':'string','EmailStr':'string'}
    result = {'type':types.get(name,'string')}
    if name in ('date','datetime','time','uuid.UUID','EmailStr'):
        result['format'] = {'datetime':'date-time','uuid.UUID':'uuid','EmailStr':'email'}.get(name,name)
    return result

routes = []
for path,tree in trees.items():
    if path.name != 'router.py' and path.parent.name != 'routes':
        continue
    routers = {}
    for n in tree.body:
        if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func).endswith('APIRouter'):
            routers[ast.unparse(n.targets[0])] = keywords(n.value).get('prefix') or ''
    for n in tree.body:
        if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if not isinstance(d,ast.Call) or not isinstance(d.func,ast.Attribute) or d.func.attr not in ('get','post','put','patch','delete'):
                continue
            router = ast.unparse(d.func.value)
            if router not in routers or not d.args:
                continue
            url = routers[router] + literal(d.args[0],'')
            module = path.relative_to(MODULES).parts[0]
            if module in ('webhooks','example'):
                continue
            defaults = [None]*(len(n.args.args)-len(n.args.defaults))+list(n.args.defaults)
            params = []
            body = None
            upload = False
            for arg,default in zip(n.args.args,defaults):
                if arg.arg in ('session','current_user','request'):
                    continue
                if arg.arg == 'payload':
                    body = schema(arg.annotation)
                    continue
                if default and isinstance(default,ast.Call) and ast.unparse(default.func)=='Depends':
                    continue
                if 'UploadFile' in ast.unparse(arg.annotation) if arg.annotation else False:
                    upload = True
                    continue
                info = schema(arg.annotation)
                kw = keywords(default) if isinstance(default,ast.Call) else {}
                info.update({'name':kw.get('alias') or arg.arg,'in':'path' if '{'+arg.arg+'}' in url else 'query','required':default is None,'default':kw.get('default',literal(default))})
                params.append(info)
            role = 'onboarding' if module == 'onboarding' and not url.endswith(('/approve', '/reject')) else 'operator' if module == 'onboarding' else 'guardian' if url.startswith('/guardian') else 'teacher' if url.startswith('/teacher') or url=='/ai/teacher-update-draft/' else 'shared' if url=='/ai/chat/' else 'admin'
            routes.append({'id':n.name,'title':n.name.replace('_',' ').capitalize(),'method':d.func.attr.upper(),'path':url,'module':module,'role':role,'params':params,'body':body,'upload':upload})
target = Path(__file__).resolve().parents[1]/'src/contracts.json'
target.write_text(json.dumps(routes,indent=2),encoding='utf-8')
print(f'Generated {len(routes)} business endpoint contracts in {target}')
