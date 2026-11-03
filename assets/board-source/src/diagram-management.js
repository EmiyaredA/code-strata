import { closeTab, UML_TYPES } from './uml-model.js';

export function reconcileDiagramTabs(state, available) {
  const ids=new Set(available.map(d=>d.id));
  return state.tabs.reduce((next,id)=>ids.has(id)?next:closeTab(next,id),state);
}
export function diagramCheckLabel(check) {
  if (!check) return '待检查';
  if (check.status==='checking') return '检查中';
  if (check.status==='unavailable') return '图已移除';
  if (check.status==='error') return '检查失败';
  if (check.status==='stale') return '源码已变化';
  return check.analyzerChanged?'分析器已变化':'关联源码未变化';
}
export function managementRequest(operation, question, type, target) {
  if (!['create','update'].includes(operation)) throw new Error('无效的图操作');
  if (operation==='create'&&!question.trim()) throw new Error('请填写想了解的内容');
  if (operation==='update'&&!target?.id) throw new Error('更新目标尚未读取');
  const diagramType=operation==='update'&&target.type!=='legacy'?target.type:type;
  const text=operation==='create'?`请根据当前项目代码生成一张${UML_TYPES[diagramType]||'合适类型的 UML'}，用于理解：${question.trim()}。标题由你概括，必须提供源码依据。`:
    `请根据当前代码更新图「${target.title}」，保留其功能主题与用途：${target.purpose}。${target.type==='legacy'?'请将旧版阅读图转换为合适的 UML 新版本，沿用原图 ID。':'保留 UML 类型。'}重新查询相关实现，说明相对旧版本的主要变化。${question.trim()?`补充要求：${question.trim()}`:''}`;
  return {operation,question:text,diagramType:diagramType||'auto',...(operation==='update'?{target:{id:target.id,revision:target.revision,lifecycleVersion:target.lifecycleVersion}}:{})};
}
