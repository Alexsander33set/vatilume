import type {ProcessHistory} from './process-types'
export type Point = { time_ms: number; [key: string]: number | undefined }
export interface ComponentEnergy { id: string; label: string; energy_kwh: number | null; cost_brl: number | null; covered_seconds: number; coverage_percent: number; priced_seconds: number; peak_w: number | null; average_w: number | null }
export interface Sensor { id: string; collector: string; metric: string; label: string; scope: string; unit: string; raw_unit: string; value: number | null; raw_value: number | null; quality: string; time_ms: number; error?: string }
export interface Event { id: number; type: string; time_ms: number; details: Record<string, unknown> }
export interface Overview { window: {start_ms:number;end_ms:number}; inventory: {cpu_model?:string;architecture?:string;collector_version?:string}; sample_count:number; first_record_ms:number|null;last_record_ms:number|null; components:ComponentEnergy[];latest:Record<string,{value:number;time_ms:number}>;series:Point[];processes:ProcessHistory;sensors:Sensor[];events:Event[];quality:{reading_errors:number;adapter_errors:number;rejected_intervals:number} }
export interface CollectorSettings {values:{interval_seconds:number;thermal_interval_seconds:number;process_interval_seconds:number;process_top_n:number;enabled_collectors:string[]};revision:string;applied_revision:string|null;applied:boolean;reload_supported:boolean}
export interface Tariff {id:string;effective_ms:number;price:string;description:string;created_ms:number}
export interface Settings {collector:CollectorSettings;tariffs:Tariff[];version:string}
export interface Status {state:string;server_time_ms:number;configuration:CollectorSettings;database_bytes:number;wal_bytes:number;sources:number;health:{updated_utc_ns:number;last_committed_sequence:number;pending_cycles:number;dropped_cycles:number;last_error:string|null;last_commit_ms:number}}
