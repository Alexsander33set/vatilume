export interface AILimits {enabled:boolean;per_analysis_usd:number;daily_usd:number;monthly_usd:number}
export interface AISettings {validator_version?:string;limits:AILimits;authorized_total_usd:number;remaining_usd:number;model:string;models:{id:string;label:string;input:number;output:number}[];key_configured:boolean;usage:{total_usd:number;daily_usd:number;monthly_usd:number;pending_usd:number}}
export interface AIQuote {id:string;model:string;maximum_usd:number;sample_count:number;window:{start_ms:number;end_ms:number};snapshot_sha256:string;data_sent:string[];cached?:boolean;projection?:{hours_per_day:number;days:number;hours_origin:string};calculation_preview?:AIAnswer|null}
export interface AIEvidence {id:string;tool:string;arguments:Record<string,unknown>;window:{start_ms:number;end_ms:number};scope:string;snapshot_sha256:string;method:string;data:Record<string,unknown>}
export interface AIClaim {id:string;text:string;evidence_ids:string[];values?:Record<string,unknown>}
export interface AIAnswer extends AIClaim {kind:string;assumptions:string[];caveats:string[]}
export interface AIReport {validator_version?:string;answer?:AIAnswer;claims:AIClaim[];recommendations:AIClaim[];limitations:string[];evidence:Record<string,AIEvidence>;window:{start_ms:number;end_ms:number};model:string;elapsed_seconds:number;snapshot_sha256:string;validation:string;answer_status:string}
export interface AIRecord {id:string;created_ms:number;state:string;question:string;report:AIReport|null;error:string|null;estimated_cost_usd:number}
export interface AIRecent {id:string;created_ms:number;state:string;question:string;error:string|null}
