#!/usr/bin/env python3
"""Create an isolated, deterministic seven-type UML demo; never calls a model.

The migration fixture preserves the real source's line numbers. Other examples
use a small executable domain model, not claims about the user's application.
"""
import argparse
from pathlib import Path
import shutil

from exploration.store import Store
from exploration.snapshots import capture
from exploration.diagrams import source_evidence, validate_diagrams

DOMAIN = '''from enum import Enum

class State(Enum):
    READY = "ready"
    SAVED = "saved"
    FAILED = "failed"

class Repository:
    def write(self, value):
        raise NotImplementedError

class MemoryRepository(Repository):
    def write(self, value):
        self.value = value

class ConfigService:
    def __init__(self, repository: Repository):
        self.repository = repository
        self.state = State.READY

    def save(self, value):
        try:
            self.repository.write(value)
            self.state = State.SAVED
        except Exception:
            self.state = State.FAILED
            raise

def cli(service, value):
    # The operator supplies input through the CLI.
    service.save(value)
'''
DEPLOYMENT = '''# Local demonstration topology, not the user's production infrastructure.
[workstation]
process = "Python CLI"
entry = "domain.py:cli"
service = "ConfigService"
repository = "MemoryRepository"
'''


def seed(folder):
    folder = Path(folder).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=False)
    project = folder / 'project'
    project.mkdir()
    (project / 'domain.py').write_text(DOMAIN)
    (project / 'pyproject.toml').write_text(DEPLOYMENT)
    path = project / 'backend/fpl_config/migration.py'
    path.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'tests/fixtures/uml_migration.py', path)
    db = folder / 'history.sqlite3'
    store = Store(db)
    sid, data, context = capture(project)
    store.save_snapshot(sid, str(project), data, context)
    conv = store.create(str(project), 'codex', '七种 UML 交互示例（确定性样例，无模型请求）')['id']
    run = store.start(conv, '根据样例源码展示七种 UML；配置迁移只聚焦加锁后的发布路径。')
    store.bind(run, sid)

    def ev(file, start, end=None):
        return source_evidence(store, run, sid, store.source(sid, file, start, end or start))

    migration = 'backend/fpl_config/migration.py'
    refs = {line: ev(migration, line) for line in (63, 64, 69, 70, 72, 76, 77, 79, 80, 83, 84, 86)}
    refs[63] = ev(migration, 63, 65)
    refs[69] = ev(migration, 69, 72)
    refs[83] = ev(migration, 83, 84)
    domain = ev('domain.py', 1, 32)
    deployment = ev('pyproject.toml', 1, 6)
    docs = []

    def doc(kind, title, purpose):
        value = dict(type=kind, title=title, purpose=purpose, nodes=[], edges=[])
        docs.append(value)
        return value

    def node(d, key, label, role, evidence, explanation, **extra):
        d['nodes'].append(dict(id=key, label=label, role=role, evidenceIds=evidence,
                              explanation=explanation, **extra))

    def edge(d, a, b, role, evidence, label='', **extra):
        d['edges'].append(dict(id=f'e{len(d["edges"])}', source=a, target=b, role=role,
            label=label, evidenceIds=evidence, explanation=extra.pop('explanation', '依据已读源码整理的关系。'), **extra))

    d = doc('activity', '配置迁移 · 安全发布', '聚焦 apply=True、加锁后未发现 TOML 的成功路径：先备份，再发布与校验。异常与其他入口分支未展开。')
    steps = [('lock','获取独占锁',63),('read','读取并校验旧配置',69),('backup','备份旧 .env',76),
             ('unchanged','确认旧文件未变化',77),('publish','发布 config.toml',79),('verify','回读校验',80),('cleanup','未变化时清理旧 .env',83)]
    for key,label,line in steps:
        node(d,key,label,'action',[refs[line]],f'`{migration}:{line}`：'+label+'。'+('发布入口在持有锁后；此处无绕过锁的连线。' if key=='lock' else ''))
    for before,after in zip(steps,steps[1:]):
        edge(d,before[0],after[0],'flow',[refs[before[2]],refs[after[2]]],explanation=f'在前一步成功后继续；{migration}:{before[2]}。')

    d = doc('sequence','保存配置 · 交互顺序','从 CLI 输入到服务，再到存储；返回只表示正常调用路径，失败会进入异常分支。')
    for key,label in [('cli','CLI'),('service','ConfigService'),('repo','MemoryRepository')]:
        node(d,key,label,'participant',[domain],f'`domain.py:23`：{label} 参与保存调用。')
    for a,b,role,label in [('cli','service','message','1  save(value)'),('service','repo','message','2  write(value)'),('repo','service','return','3  正常返回'),('service','service','message','4  state = SAVED'),('service','cli','return','5  保存完成')]:
        edge(d,a,b,role,[domain],label,order=len(d['edges']))

    d=doc('class','配置对象 · 类型关系','展示源码中声明的类型、继承和依赖；成员采用 Python 签名。')
    for key,label,role,members in [('repo','Repository','class',['+ write(value)']),('memory','MemoryRepository','class',['+ write(value)']),('service','ConfigService','class',['repository: Repository','state: State','+ save(value)']),('state','State','enum',['READY','SAVED','FAILED'])]:
        node(d,key,label,role,[domain],'类型来自 `domain.py:1`。',members=members)
    edge(d,'memory','repo','inheritance',[domain]);edge(d,'service','repo','association',[domain],'repository');edge(d,'service','state','dependency',[domain],'state')

    d=doc('component','保存配置 · 职责组件','将源码职责整理为 CLI、服务和存储边界，属于源码推导，并非独立部署进程。')
    for key,label in [('cli','CLI 入口'),('service','配置服务'),('repo','存储适配')]:node(d,key,label,'component',[domain],'根据 `domain.py:1` 的职责整理。')
    edge(d,'cli','service','dependency',[domain],'调用 save');edge(d,'service','repo','dependency',[domain],'调用 write')

    d=doc('state','保存配置 · 状态变化','展示 State 枚举及 save() 的成功、失败赋值；不推断源码未声明的恢复路径。')
    node(d,'start','','start',[],'进入初始化。')
    for key in ('READY','SAVED','FAILED'):node(d,key,key,'state',[domain],'状态及赋值依据 `domain.py:3`。')
    edge(d,'start','READY','flow',[])
    edge(d,'READY','SAVED','transition',[domain],'write 成功');edge(d,'READY','FAILED','transition',[domain],'抛出异常')

    d=doc('usecase','配置工具 · 使用目标','从 cli(service, value) 推导操作者与保存目标；系统边界是示例工具。')
    node(d,'operator','CLI 操作者','actor',[domain],'操作者由 `domain.py:31` 的 CLI 输入语义推导。')
    node(d,'system','配置工具','system',[domain],'根据模块职责推导的系统边界。')
    node(d,'save','保存配置','usecase',[domain],'用户可通过 CLI 保存输入。',parentId='system')
    edge(d,'operator','save','association',[domain])

    d=doc('deployment','本地工具 · 部署结构','只展示 pyproject.toml 明确声明的本机 Python 进程与入口产物；没有远端服务。')
    node(d,'host','开发工作站','device',[deployment],'依据 `pyproject.toml:2`。')
    node(d,'runtime','Python CLI','execution',[deployment],'配置中声明的运行进程。',parentId='host')
    node(d,'artifact','domain.py','artifact',[domain,deployment],'包含 CLI、服务与内存存储。',parentId='runtime')
    # Containment is sufficient; do not invent a network link between nested objects.

    values=validate_diagrams(store,run,sid,str(project),dict(diagrams=docs))
    store.save_diagram_draft(run,str(project),values)
    store.assistant(conv,run,'已载入七种 UML 确定性示例。所有节点绑定样例源码；本任务未调用模型。')
    store.finish(run,'completed',diagrams=values)
    return project,db

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',help='新建独立示例目录；必须不存在')
    args=parser.parse_args()
    project,db=seed(args.directory)
    print(f'python3 scripts/serve.py --project "{project}" --history-db "{db}" --open')
