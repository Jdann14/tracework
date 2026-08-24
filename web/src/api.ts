export type Row = Record<string, unknown>;
export interface Column {name:string;type:string;nullable:boolean;missing?:number;distinct?:number;min?:number;max?:number;mean?:number}
export interface Profile {rows:number;columns:Column[];sample:Row[]}
export interface SourceVersion {id:string;dataset_id:string;hash:string;original_name:string;created_at:string;rows:number;schema:Column[];profile:Profile}
export interface Source {id:string;name:string;versions:SourceVersion[]}
export interface CheckSpec {name:string;sql:string;severity:'blocking'|'warning';description?:string}
export interface Step {name:string;title:string;sql:string;depends_on:string[];checks:CheckSpec[]}
export interface Spec {title:string;description:string;assumptions:string[];sources:{name:string;columns:Record<string,string>}[];steps:Step[];output:string;parameters:Record<string,unknown>}
export interface Version {id:string;pipeline_id:string;number:number;parent_id:string|null;hash:string;spec:Spec;approved_at?:string;approved?:boolean}
export interface Pipeline {id:string;title:string;versions:Version[]}
export interface Event {id:number;tool:string;arguments:unknown;response:unknown;created_at:string}
export interface Investigation {id:string;question:string;provider:string;status:string;version_id:string|null;message:string|null;error:string|null;events:Event[]}
export interface Run {id:string;version_id:string;status:string;created_at:string;started_at:string;finished_at:string;inputs:Record<string,string>;parameters:Record<string,unknown>;settings:Record<string,unknown>;error:string|null;cancel_requested:number}
export interface Artifact {id:string;step:string;dataset_id:string;hash:string;rows:number;profile:Profile;schema:Column[]}
export interface Check extends CheckSpec {id:string;step:string;status:string;violations:number;sample:Row[];error:string|null}
export interface Finding {id:string;artifact_id:string;title:string;detail:string;evidence:{step:string;row_index:number;row:Row}}
export interface RunDetail extends Run {version:Version;steps:{name:string;status:string;error:string|null}[];checks:Check[];artifacts:Artifact[];findings:Finding[];logs:{id:number;step:string|null;message:string;created_at:string}[];resolved_inputs:Record<string,SourceVersion>}
export interface WorkspaceData {sources:Source[];pipelines:Pipeline[];runs:Run[];investigations:Investigation[]}
export interface Dataset {id:string;name:string;schema:Column[];profile:Profile;rows:number;data:Row[];offset:number;limit:number}
export interface Comparison {left:string;right:string;input_changes:{source:string;before:SourceVersion;after:SourceVersion;content_changed:boolean;schema_changed:boolean}[];logic_changed:boolean;step_changes:{step:string;before:Step;after:Step}[];parameters_changed:boolean;settings_changed:boolean;rows:{key:string;before:string;after:string;delta:string;before_row:Row;after_row:Row}[];message:string|null;key:string;metric:string}
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const response=await fetch('/api'+path,{...options,headers:options.body instanceof FormData?options.headers:{'Content-Type':'application/json',...options.headers}});
  if(!response.ok){const body=await response.json().catch(()=>({detail:response.statusText}));throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));}
  return response.json();
}
export const post=<T,>(path:string,body?:unknown)=>api<T>(path,{method:'POST',body:body===undefined?undefined:JSON.stringify(body)});
export const short=(id:string)=>id.slice(0,7);
export const fmt=(value:unknown):string=>value===null||value===undefined?'—':typeof value==='object'?JSON.stringify(value):String(value);
export const time=(value:string)=>new Date(value).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
