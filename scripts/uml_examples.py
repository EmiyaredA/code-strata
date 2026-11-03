"""Reproducible source-backed notation examples, never a model request."""
NOTATION_SOURCE = '''# Explicit sample declarations, not facts about a user's application.
class Repository:
    def write(self, value): self.value = value
class Service:
    def __init__(self, repository): self.repository = repository
    def save(self, value): self.repository.write(value)
repository = Repository()
service = Service(repository)
service.save("sample")
# A sample UML Profile is explicitly declared, rather than inferred from annotations.
PROFILE_XML = '<Profile name="Trace"><Stereotype name="SourceBacked" extends="Class"/></Profile>'
RESPONSIBILITIES = {"Service": "orchestration", "Repository": "persistence"}
STATES = ["READY", "WRITING", "SAVED"]  # logical order, no elapsed-time assertion
PORTS = {"service.repository": {"kind": "required"}, "repository.write": {"kind": "provided"}}
'''

def examples(evidence, migration=None):
    docs=[]
    def doc(kind, title, purpose):
        d=dict(type=kind,title=title,purpose=purpose,nodes=[],edges=[]);docs.append(d);return d
    def node(d,id,label,role,**kw):
        d['nodes'].append(dict(id=id,label=label,role=role,evidenceIds=[evidence],explanation='根据样例 notation.py 的显式声明整理；非运行时记录。',**kw))
    def edge(d,a,b,role,label='',**kw):
        d['edges'].append(dict(id='e'+str(len(d['edges'])),source=a,target=b,role=role,label=label,evidenceIds=[evidence],explanation='关系依据样例声明，不代表运行轨迹。',**kw))
    for kind,roles,erole in [('class',('class','class'),'dependency'),('component',('component','component'),'dependency'),('package',('package','package'),'package-import'),('object',('object','object'),'link'),('usecase',('actor','usecase'),'association'),('deployment',('device','artifact'),'dependency'),('state',('state','state'),'transition'),('sequence',('participant','participant'),'message'),('communication',('object','object'),'message')]:
        d=doc(kind,'保存配置 · '+kind,'解释样例中的保存职责与静态关系；对象仅表示源码构造关系。')
        for id,label,role in [('a','Service',roles[0]),('b','Repository',roles[1])]:
            node(d,id,label,role,**(dict(classifier=label,slots=['repository = repository']) if role=='object' and id=='a' else {}))
        edge(d,'a','b',erole,'save → write',order=0)
    for kind in ('flowchart','activity','swimlane','interaction-overview'):
        d=doc(kind,'配置迁移 · '+kind,'加锁后读取：先备份、检查未变化、再发布 TOML、回读校验；仅展开成功路径及检查失败分支。')
        if kind=='swimlane':
            node(d,'convert','迁移编排 / convert_legacy','lane',order=0)
            node(d,'publish','文件发布 / publish','lane',order=1)
        steps=[('lock','加锁并读取','action',63),('backup','备份旧配置','action',76),('check','旧文件未变化？','decision',77),('write','发布 TOML','interaction' if kind=='interaction-overview' else 'action',79),('verify','回读校验','action',80),('fail','抛出异常','action',78),('end','结束','end',86)]
        for id,label,role,line in steps:
            kw={}
            if kind=='swimlane':kw['parentId']='publish' if id in ('backup','write') else 'convert'
            if role=='interaction':kw['interaction']='publish(path, encode(document))'
            node(d,id,label,role,**kw)
            if migration and line in migration:d['nodes'][-1]['evidenceIds']=[migration[line]]
        for a,b,label in [('lock','backup',''),('backup','check',''),('check','write','是'),('write','verify',''),('check','fail','否'),('verify','end','成功'),('fail','end','停止')]:edge(d,a,b,'flow',label)
    d=doc('composite','保存配置 · 组合结构','配置中明确声明的 required/provided 端口和持有的存储部件。')
    node(d,'service','配置服务','structured-class');node(d,'repo','repository : Repository','part',parentId='service')
    node(d,'required','repository','port',parentId='service',portKind='required',side='left')
    node(d,'provided','write','port',parentId='repo',portKind='provided',side='right')
    edge(d,'required','provided','assembly','存储接口')
    d=doc('profile','源码标记 · Profile','仅来自样例 PROFILE_XML 的显式 Profile / Stereotype / Metaclass 定义。')
    node(d,'profile','Trace','profile');node(d,'stereo','SourceBacked','stereotype',parentId='profile')
    node(d,'meta','Class','metaclass');edge(d,'stereo','meta','extension','扩展 Class')
    d=doc('timing','保存配置 · 逻辑定时','仅呈现源码枚举状态的逻辑顺序，不提供真实执行时间。')
    node(d,'signal','保存状态','signal')
    for i,label in enumerate(('READY','WRITING','SAVED')):node(d,'t'+str(i),label,'state-event',parentId='signal',order=i)
    edge(d,'t0','t1','transition','开始写入');edge(d,'t1','t2','transition','写入完成')
    return docs
