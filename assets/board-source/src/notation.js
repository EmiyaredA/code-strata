export const TYPE_GROUPS = [
  ['流程',[['flowchart','流程图'],['swimlane','泳道图']]],
  ['UML 结构',[['class','类图'],['object','对象图'],['package','包图'],['component','组件图'],['composite','组合结构图'],['deployment','部署图'],['profile','制品图（Profile）']]],
  ['UML 行为',[['activity','活动图'],['state','状态机图'],['usecase','用例图']]],
  ['UML 交互',[['sequence','时序图'],['communication','通信图'],['timing','定时图'],['interaction-overview','交互概览图']]],
];
export const TYPE_OPTIONS = TYPE_GROUPS.flatMap(([group,types])=>types.map(([value,label])=>({value,label,group})));
export const CONTROL_TYPES = new Set(['activity','flowchart','swimlane','interaction-overview','state']);
export const nodeTitle = n => n.label+(n.classifier?' : '+n.classifier:'');
export const nodeMembers = n => [...(n.slots||n.members||[]),...(n.interaction?['ref · '+n.interaction]:[]),...(n.role==='state-event'?[n.time!=null?String(n.time):'顺序 '+n.order]:[])];
export const edgeCaption = e => [e.role==='message'||e.role==='return'||e.role==='async' ? e.communication ? `${e.order}:` : '' : '', e.label].filter(Boolean).join(' ');
