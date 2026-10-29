export function keepStandardVisible(viewport, frame, bounds, anchor) {
  const next={...viewport},z=viewport.zoom;
  if(anchor){
    if(anchor.x*z+next.x<20||anchor.x*z+next.x>frame.width-20)next.x=frame.width/2-anchor.x*z;
    if(anchor.y*z+next.y<20||anchor.y*z+next.y>frame.height-20)next.y=frame.height/2-anchor.y*z;
  }else{
    if(next.x+bounds.width*z<20||next.x>frame.width-20)next.x=(frame.width-bounds.width*z)/2;
    if(next.y+bounds.height*z<20||next.y>frame.height-20)next.y=(frame.height-bounds.height*z)/2;
  }
  return next;
}
