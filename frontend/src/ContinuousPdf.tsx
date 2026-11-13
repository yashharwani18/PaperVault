import {forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import type {PDFViewer} from 'pdfjs-dist/web/pdf_viewer.mjs';
import {LoaderCircle} from 'lucide-react';
import {isAndroid} from './androidBridge';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import androidWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';

export type ContinuousPdfHandle={goToPage:(page:number)=>void};
type Props={id:string;initialPage:number;zoom:number;highlightPage?:number;boxes:number[][];onPageChange:(page:number)=>void;onReady:(pages:number)=>void;onError:(error:string)=>void};

/** Mozilla's rendering queue keeps nearby pages ready and releases distant canvases. */
export default forwardRef<ContinuousPdfHandle,Props>(function ContinuousPdf({id,initialPage,zoom,highlightPage,boxes,onPageChange,onReady,onError},ref){
 const container=useRef<HTMLDivElement>(null),pages=useRef<HTMLDivElement>(null),reader=useRef<PDFViewer|null>(null);
 const latest=useRef({zoom,boxes,highlightPage,onPageChange,onReady,onError});latest.current={zoom,boxes,highlightPage,onPageChange,onReady,onError};
 const [loading,setLoading]=useState(true),[pageText,setPageText]=useState('');
 const jumpedToHighlight=useRef(false),textRequest=useRef(0);
 function decorate(){
  const view=reader.current,{boxes,highlightPage}=latest.current;
  if(!view||!highlightPage)return;
  const page=view.getPageView(highlightPage-1)?.div as HTMLDivElement|undefined;
  if(!page)return;
  page.querySelector('.source-highlights')?.remove();
  if(!boxes.length)return;
  const overlay=document.createElement('div');overlay.className='source-highlights';overlay.setAttribute('aria-hidden','true');
  for(const b of boxes){const marker=document.createElement('span');marker.className='source-highlight';Object.assign(marker.style,{left:`${b[0]*100}%`,top:`${b[1]*100}%`,width:`${b[2]*100}%`,height:`${b[3]*100}%`});overlay.append(marker);}
  page.append(overlay);
  if(!jumpedToHighlight.current&&view.currentPageNumber===highlightPage&&page.querySelector('canvas')&&container.current){
   jumpedToHighlight.current=true;
   const marker=overlay.firstElementChild as HTMLElement,scroller=container.current;
   const offset=marker.getBoundingClientRect().top-scroller.getBoundingClientRect().top+scroller.scrollTop;
   scroller.scrollTo({top:Math.max(0,offset-scroller.clientHeight*.35),behavior:'instant'});
  }
 }
 useImperativeHandle(ref,()=>({goToPage(page){const view=reader.current;if(view?.pagesCount)view.scrollPageIntoView({pageNumber:Math.max(1,Math.min(page,view.pagesCount))});}}),[]);
 useEffect(()=>{
  let alive=true;const controller=new AbortController();let destroy:(()=>void)|undefined;
  jumpedToHighlight.current=false;setLoading(true);setPageText('');
  void(async()=>{try{
   // The component bundle reads the matching core library from globalThis.
   const engine=isAndroid()?await import('pdfjs-dist/legacy/build/pdf.mjs'):await import('pdfjs-dist');
   engine.GlobalWorkerOptions.workerSrc=isAndroid()?androidWorkerUrl:workerUrl;
   const {PDFViewer,EventBus,PDFLinkService,ScrollMode}=await import('pdfjs-dist/web/pdf_viewer.mjs');
   if(!alive||!container.current||!pages.current)return;
   const eventBus=new EventBus(),links=new PDFLinkService({eventBus,externalLinkTarget:2,externalLinkRel:'noopener noreferrer'});
   const options={container:container.current,viewer:pages.current,eventBus,linkService:links,removePageBorders:true,annotationMode:engine.AnnotationMode.ENABLE,maxCanvasPixels:8_000_000,enableScripting:false,abortSignal:controller.signal,imageResourcesPath:'/pdfjs/images/'};
   const view=new PDFViewer(options);reader.current=view;links.setViewer(view);view.scrollMode=ScrollMode.VERTICAL;
   let previousWidth=container.current.clientWidth;
   const resize=new ResizeObserver(()=>{const width=container.current?.clientWidth;if(width&&width!==previousWidth){previousWidth=width;if(view.pagesCount&&latest.current.zoom===1)view.currentScaleValue='page-width';view.update();}});
   resize.observe(container.current);
   controller.signal.addEventListener('abort',()=>resize.disconnect(),{once:true});
   async function updateText(number:number){const request=++textRequest.current;try{const source=await view.pdfDocument?.getPage(number);const text=await source?.getTextContent();if(alive&&request===textRequest.current)setPageText(text?.items.map(item=>'str' in item?item.str:'').join(' ')||'');}catch{/* Page loading errors are reported by pagerendered. */}}
   eventBus.on('pagesinit',()=>{if(!alive)return;view.currentScaleValue=latest.current.zoom===1?'page-width':String(latest.current.zoom);view.scrollPageIntoView({pageNumber:Math.max(1,Math.min(initialPage,view.pagesCount))});latest.current.onReady(view.pagesCount);latest.current.onPageChange(view.currentPageNumber);void updateText(view.currentPageNumber);});
   eventBus.on('pagechanging',({pageNumber}:{pageNumber:number})=>{if(alive){latest.current.onPageChange(pageNumber);void updateText(pageNumber);}});
   eventBus.on('pagerendered',({pageNumber,error}:{pageNumber:number;error?:Error})=>{if(!alive)return;if(error){latest.current.onError(error.message);return;}const page=view.getPageView(pageNumber-1)?.div as HTMLDivElement|undefined;const canvas=page?.querySelector('canvas');if(canvas){canvas.dataset.testid='pdf-canvas';canvas.dataset.pdfPage=String(pageNumber);canvas.setAttribute('aria-label',`PDF page ${pageNumber}`);}setLoading(false);decorate();});
   const task=engine.getDocument({url:`/api/documents/${id}/file`,cMapUrl:'/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/pdfjs/standard_fonts/',wasmUrl:'/pdfjs/wasm/'});
   destroy=()=>{view.setDocument(null);links.setDocument(null);void task.destroy();};
   const document=await task.promise;if(!alive){destroy();return;}links.setDocument(document);view.setDocument(document);
  }catch(error){if(alive){setLoading(false);latest.current.onError((error as Error).message);}}})();
  return()=>{alive=false;textRequest.current++;destroy?.();controller.abort();reader.current=null;};
 },[id]);
 useEffect(()=>{const view=reader.current;if(!view?.pagesCount)return;view.currentScaleValue=zoom===1?'page-width':String(zoom);},[zoom]);
 useEffect(()=>{decorate();},[boxes,highlightPage]);
 return <div className="pdf-reader-shell"><div ref={container} className="pdf-stage pdf-continuous" tabIndex={0} role="region" aria-label="Scrollable PDF pages"><div ref={pages} className="pdfViewer"/></div>{loading&&<div className="pdf-loading" role="status"><LoaderCircle className="spin" size={24}/>Opening document…</div>}<div className="sr-only" data-testid="pdf-page-text">{pageText}</div></div>;
});
