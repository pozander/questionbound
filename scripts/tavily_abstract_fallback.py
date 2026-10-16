#!/usr/bin/env python3
"""Bounded abstract enrichment: Tavily discovers; deterministic code extracts."""

from __future__ import annotations
import argparse, html, json, os, re, subprocess, sys, tempfile
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
import requests

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_KEY_FILE = PROJECT_ROOT / ".secrets" / "tavily.env"
MAX_RECORDS_CEILING, MAX_RESULTS_CEILING = 10, 3
MAX_QUERY_ATTEMPTS_CEILING, MAX_FETCHES_PER_RECORD_CEILING = 3, 3
MAX_DOWNLOAD_BYTES, RRF_K = 8 * 1024 * 1024, 60

class TavilyError(RuntimeError): pass

def load_api_key(path: Path) -> str:
    key = os.environ.get("TAVILY_API_KEY", "").strip().strip("'\"")
    if key: return key
    try: lines = path.expanduser().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError: return ""
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"): continue
        if value.startswith("TAVILY_API_KEY="): value = value.split("=", 1)[1].strip()
        return value.strip("'\"")
    return ""

def compact_space(value: Any) -> str: return re.sub(r"\s+", " ", str(value or "")).strip()
def normalized_text(value: Any) -> str:
    return re.sub(r"[^\w]+", " ", html.unescape(compact_space(value)).casefold()).strip()
def normalized_doi(value: Any) -> str:
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", compact_space(value).casefold())
    return value.removeprefix("doi:").strip()

def canonical_title(value: Any) -> str:
    """Normalize harmless chapter-number prefixes across bibliographic records."""
    title=normalized_text(value)
    return re.sub(r"^(?:chapter\s+)?\d+\s+", "", title).strip()

def first_author_surname(record: dict[str, Any]) -> str:
    authors = record.get("authors") or []
    first = re.split(r"\s*(?:;|\band\b)\s*", authors, 1)[0] if isinstance(authors, str) else compact_space(authors[0]) if authors else ""
    words = re.findall(r"[\w'’-]+", first)
    if not words: return ""
    return " ".join(words[-2:]) if len(words) > 1 and words[-2].casefold() in {"de","del","der","di","la","le","van","von"} else words[-1]

def bibliographic_keys(record: dict[str, Any]) -> list[str]:
    keys, doi = [], normalized_doi(record.get("doi"))
    title, surname = canonical_title(record.get("title")), normalized_text(first_author_surname(record))
    oid = compact_space(record.get("openalex_id") or record.get("openalex"))
    if doi: keys.append(f"doi:{doi}")
    if title and surname: keys.append(f"work:{title}|{surname}")
    if oid: keys.append(f"openalex:{oid.casefold()}")
    if title: keys.append(f"title-year:{title}|{record.get('year') or ''}")
    return keys

def record_key(record: dict[str, Any]) -> str:
    return (bibliographic_keys(record) or [""])[0]
def has_abstract(record: dict[str, Any]) -> bool: return bool(compact_space(record.get("abstract")))

def _merge_metadata(target: dict[str, Any], source: dict[str, Any]) -> None:
    for field, value in source.items():
        if field not in {"source_queries","source_ranks","retrieval_score"} and not target.get(field) and value:
            target[field] = deepcopy(value)
    ids = {compact_space(v) for v in [target.get("openalex_id"), target.get("openalex"), source.get("openalex_id"), source.get("openalex")] if v}
    target["openalex_ids"] = sorted(set(target.get("openalex_ids") or []) | ids)
    dois = {normalized_doi(v) for v in [target.get("doi"), source.get("doi")] if normalized_doi(v)}
    target["doi_aliases"] = sorted(set(target.get("doi_aliases") or []) | dois)

def load_and_rank_packs(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    clusters, aliases, queries = [], {}, []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise ValueError(f"{path} is not an OpenAlex JSON pack with a records list")
        query = compact_space(payload.get("query")) or path.stem; queries.append(query)
        for rank, raw in enumerate(payload["records"], 1):
            if not isinstance(raw, dict) or not bibliographic_keys(raw): continue
            matches = {aliases[k] for k in bibliographic_keys(raw) if k in aliases}
            index = min(matches) if matches else len(clusters)
            if not matches:
                item = deepcopy(raw); item.update(source_queries=[], source_ranks=[], retrieval_score=0.0, openalex_ids=[], doi_aliases=[]); clusters.append(item)
            item = clusters[index]; _merge_metadata(item, raw)
            for key in bibliographic_keys(raw) + bibliographic_keys(item): aliases[key] = index
            if query not in item["source_queries"]: item["source_queries"].append(query)
            item["source_ranks"].append({"query": query, "rank": rank}); item["retrieval_score"] += 1/(RRF_K+rank)
    ranked = sorted(clusters, key=lambda r: (-r["retrieval_score"], -len(r["source_queries"]), -int(r.get("cited_by_count") or 0), normalized_text(r.get("title"))))
    for rank, item in enumerate(ranked, 1): item.update(aggregate_rank=rank, retrieval_score=round(item["retrieval_score"], 8))
    return ranked, queries

def publisher_name(record: dict[str, Any]) -> str:
    for field in ("publisher","host_venue","source","journal"):
        value = record.get(field)
        if isinstance(value, dict): value = value.get("display_name") or value.get("name")
        if compact_space(value): return compact_space(value)
    return ""

def build_queries(record: dict[str, Any]) -> list[str]:
    title, surname = compact_space(record.get("title")), first_author_surname(record)
    doi, year, publisher = normalized_doi(record.get("doi")), compact_space(record.get("year")), publisher_name(record)
    queries = []
    if doi: queries.append(" ".join(filter(None, [f'"{doi}"', f'"{surname}"' if surname else "", "abstract"])))
    if title: queries.append(" ".join(filter(None, [f'"{title}"', f'"{surname}"' if surname else "", year, "abstract"])))
    if title and publisher: queries.append(f'"{title}" "{publisher}" abstract')
    return list(dict.fromkeys(queries))
def build_query(record: dict[str, Any]) -> str: return build_queries(record)[0]

def title_similarity(expected: str, observed: str) -> float:
    a, b = normalized_text(expected), normalized_text(observed)
    if not a or not b: return 0.0
    return max(SequenceMatcher(None,a,b).ratio(), len(set(a.split()) & set(b.split()))/max(1,len(set(a.split()))))

def identity_match(record: dict[str, Any], result: dict[str, Any]) -> tuple[bool,float,list[str]]:
    haystack = " ".join(compact_space(result.get(k)) for k in ("title","url","content","raw_content","document_text")).casefold()
    for doi in record.get("doi_aliases") or [normalized_doi(record.get("doi"))]:
        if doi and doi in haystack: return True, 1.0, ["doi"]
    similarity = title_similarity(record.get("title"), result.get("title"))
    surname = normalized_text(first_author_surname(record)); author = bool(surname and surname in normalized_text(haystack))
    year = compact_space(record.get("year")); year_match = bool(year and re.search(rf"(?<!\d){re.escape(year)}(?!\d)",haystack))
    score = .78*similarity + .14*author + .08*year_match
    reasons = [f"title={similarity:.3f}"] + (["author"] if author else []) + (["year"] if year_match else [])
    return similarity >= .82 or (similarity >= .68 and score >= .76), round(score,4), reasons

def visible_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?is)<(?:br|/p|/div|/li|/h[1-6]|/section|/article)\b[^>]*>","\n",text)
    text = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>"," ",text)
    return re.sub(r"[ \t]+"," ",re.sub(r"(?s)<[^>]+>"," ",text).replace("\r","\n")).strip()
def tidy_abstract(value: str) -> str:
    value = re.sub(r"(\w)-\s*\n\s*(\w)",r"\1\2",value)
    value = re.sub(r"!\[[^]]*]\([^)]*\)"," ",value); value = re.sub(r"\[([^]]+)]\([^)]*\)",r"\1",value)
    return compact_space(re.sub(r"[*_]{1,3}","",value)).strip(" -:;.—")
def extract_abstract(value: Any, max_chars: int=5000) -> str|None:
    flat = compact_space(visible_text(value))
    stop = r"keywords?|key words|(?:\d+(?:\.\d+)*[.)]?\s+)?introduction|references|article information"
    match = re.search(rf"(?is)(?:^|\b)abstract\s*(?:[:.\-—]|(?=[A-Z]))?\s*(.{{80,{max_chars}}}?)(?=\s+(?:{stop})\b)",flat)
    candidate = tidy_abstract(match.group(1))[:max_chars] if match else ""
    return candidate if len(candidate)>=80 else None

class MetadataParser(HTMLParser):
    def __init__(self): super().__init__(); self.metadata={}; self.json_ld=[]; self.in_json=False; self.parts=[]; self.in_title=False; self.title_parts=[]
    def handle_starttag(self,tag,attrs):
        values={k.casefold():v or "" for k,v in attrs}
        if tag.casefold()=="meta":
            name=(values.get("name") or values.get("property") or "").casefold(); content=values.get("content","").strip()
            if name and content: self.metadata.setdefault(name,[]).append(html.unescape(content))
        if tag.casefold()=="script" and "ld+json" in values.get("type","").casefold(): self.in_json=True; self.parts=[]
        if tag.casefold()=="title": self.in_title=True
    def handle_data(self,data):
        if self.in_json: self.parts.append(data)
        if self.in_title: self.title_parts.append(data)
    def handle_endtag(self,tag):
        if tag.casefold()=="script" and self.in_json: self.json_ld.append("".join(self.parts)); self.in_json=False
        if tag.casefold()=="title": self.in_title=False

def html_document_title(parser: MetadataParser) -> str:
    for name in ("citation_title","dc.title","dcterms.title","og:title"):
        if parser.metadata.get(name): return compact_space(parser.metadata[name][0])
    return compact_space("".join(parser.title_parts))

def extract_html_abstract(document: str) -> tuple[str|None,str|None]:
    parser=MetadataParser()
    try: parser.feed(document)
    except Exception: pass
    for name in ("citation_abstract","dc.description","dcterms.abstract"):
        for value in parser.metadata.get(name,[]):
            candidate=tidy_abstract(value)
            if len(candidate)>=80: return candidate[:5000],f"html_meta:{name}"
    for block in parser.json_ld:
        try: payload=json.loads(block)
        except (json.JSONDecodeError,TypeError): continue
        for node in payload if isinstance(payload,list) else [payload]:
            if isinstance(node,dict):
                for name in ("abstract",):
                    candidate=tidy_abstract(node.get(name,""))
                    if len(candidate)>=80: return candidate[:5000],f"html_jsonld:{name}"
    candidate=extract_abstract(document); return (candidate,"html_visible:abstract_label") if candidate else (None,None)

PUBLISHER_DOMAINS=("springer.com","sagepub.com","wiley.com","tandfonline.com","sciencedirect.com","elsevier.com","oup.com","cambridge.org","emerald.com")
SOCIAL_DOMAINS=("researchgate.net","academia.edu","semanticscholar.org","scribd.com")
def source_class(url: str) -> tuple[str,int]:
    host=urlparse(url).netloc.casefold().split(":")[0]
    if any(host==d or host.endswith("."+d) for d in PUBLISHER_DOMAINS): return "publisher",0
    if host.endswith(".edu") or ".edu." in host or host.endswith(".ac.uk") or ".ac." in host or any(x in host for x in ("repository","researchportal","pure.")): return "institutional_repository",1
    if host in {"doi.org","dx.doi.org","api.crossref.org","crossref.org"}: return "doi_or_crossref",2
    if host.endswith("openalex.org"): return "openalex",3
    if any(host==d or host.endswith("."+d) for d in SOCIAL_DOMAINS): return "commercial_or_social_repository",5
    return "other",4

class WebFetcher:
    def __init__(self,timeout=30.0,max_bytes=MAX_DOWNLOAD_BYTES): self.timeout,self.max_bytes=timeout,max_bytes
    def fetch(self,url):
        try:
            response=requests.get(url,headers={"User-Agent":"QuestionBound/1.0 (abstract verification)"},timeout=self.timeout,stream=True,allow_redirects=True); response.raise_for_status()
            chunks=[]; total=0
            for chunk in response.iter_content(65536):
                total+=len(chunk)
                if total>self.max_bytes: raise ValueError(f"document exceeds {self.max_bytes} bytes")
                chunks.append(chunk)
            content=b"".join(chunks); content_type=response.headers.get("Content-Type","").split(";",1)[0].casefold(); final_url=response.url
            if content_type=="application/pdf" or final_url.casefold().endswith(".pdf") or content.startswith(b"%PDF"):
                with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
                    handle.write(content); handle.flush(); process=subprocess.run(["pdftotext","-f","1","-l","3",handle.name,"-"],capture_output=True,text=True,timeout=self.timeout,check=False)
                if process.returncode: raise ValueError(compact_space(process.stderr) or "pdftotext failed")
                return {"url":final_url,"content_type":"application/pdf","bytes":total,"document_text":process.stdout,"abstract":extract_abstract(process.stdout),"method":"pdf_pdftotext:first_3_pages"}
            document=content.decode(response.encoding or "utf-8",errors="replace"); abstract,method=extract_html_abstract(document); parser=MetadataParser()
            try: parser.feed(document)
            except Exception: pass
            return {"url":final_url,"content_type":content_type or "text/html","bytes":total,"document_title":html_document_title(parser),"document_text":visible_text(document)[:50000],"abstract":abstract,"method":method}
        except (requests.RequestException,ValueError,subprocess.SubprocessError) as exc: return {"url":url,"error":compact_space(exc)}

class TavilyClient:
    def __init__(self,api_key,timeout=30.0): self.api_key,self.timeout=api_key,timeout
    def search(self,query,max_results):
        payload={"query":query,"search_depth":"basic","max_results":max_results,"topic":"general","include_answer":False,"include_raw_content":False,"include_usage":True,"auto_parameters":False}
        try:
            response=requests.post(TAVILY_SEARCH_URL,headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"},json=payload,timeout=self.timeout); response.raise_for_status(); data=response.json()
        except (requests.RequestException,ValueError) as exc: raise TavilyError(f"Tavily search failed: {str(exc).replace(self.api_key,'[REDACTED]')}") from exc
        if not isinstance(data,dict) or not isinstance(data.get("results"),list): raise TavilyError("Tavily returned an unexpected response shape")
        return data

def ordered_candidates(record,response):
    accepted,audit=[],[]
    for rank,result in enumerate(response.get("results",[]),1):
        if not isinstance(result,dict): continue
        ok,score,reasons=identity_match(record,result); classification,priority=source_class(compact_space(result.get("url")))
        entry={"rank":rank,"title":compact_space(result.get("title")),"url":compact_space(result.get("url")),"source_class":classification,"tavily_score":result.get("score"),"identity_accepted":ok,"identity_score":score,"identity_reasons":reasons,"content_preview":compact_space(result.get("content"))[:500]}; audit.append(entry)
        if ok and entry["url"]: accepted.append({"priority":priority,"rank":rank,"result":result,"audit":entry})
    return sorted(accepted,key=lambda x:(x["priority"],x["rank"])),audit

def enrich_records(records,client,max_records,max_results,*,max_query_attempts=2,max_fetches_per_record=3,fetcher=None):
    fetcher=fetcher or WebFetcher(); attempts=[]
    for record in [r for r in records if not has_abstract(r)][:max_records]:
        attempt={"aggregate_rank":record.get("aggregate_rank"),"openalex_ids":record.get("openalex_ids") or [record.get("openalex_id")],"title":record.get("title"),"searches":[],"status":"not_found_or_ambiguous"}; seen=set(); fetch_audit=[]; fetch_count=0
        for query in build_queries(record)[:max_query_attempts]:
            try: response=client.search(query,max_results)
            except TavilyError as exc: attempt["searches"].append({"query":query,"status":"request_failed","error":str(exc)}); continue
            ordered,inspected=ordered_candidates(record,response); attempt["searches"].append({"query":query,"request_id":response.get("request_id"),"usage":response.get("usage"),"results_inspected":inspected})
            for candidate in ordered:
                url=compact_space(candidate["result"].get("url"))
                if url in seen or fetch_count>=max_fetches_per_record: continue
                seen.add(url); fetch_count+=1; result=candidate["result"]; fetched=fetcher.fetch(url); combined={"title":fetched.get("document_title", ""),"document_text":fetched.get("document_text","")}
                ok,score,reasons=identity_match(record,combined); abstract=fetched.get("abstract") if ok else None
                fetch_audit.append({"url":fetched.get("url"),"source_class":candidate["audit"]["source_class"],"content_type":fetched.get("content_type"),"bytes":fetched.get("bytes"),"method":fetched.get("method"),"error":fetched.get("error"),"identity_accepted_after_fetch":ok,"identity_score_after_fetch":score,"identity_reasons_after_fetch":reasons,"abstract_found":bool(abstract)})
                if abstract:
                    record["abstract"]=abstract; record["abstract_provenance"]={"provider":"deterministic extraction after Tavily discovery","source_url":fetched.get("url"),"source_title":compact_space(result.get("title")),"source_class":candidate["audit"]["source_class"],"request_id":response.get("request_id"),"retrieved_at":datetime.now(timezone.utc).isoformat(),"method":fetched.get("method")}; attempt.update(status="abstract_added",source_url=fetched.get("url")); break
            if attempt["status"]=="abstract_added" or fetch_count>=max_fetches_per_record: break
        attempt["fetches"]=fetch_audit; attempts.append(attempt)
    return records,attempts

def write_json(path,payload,force):
    if path.exists() and not force: raise FileExistsError(f"Refusing to overwrite {path}; use --force if intentional")
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def parser():
    p=argparse.ArgumentParser(description="Bounded Tavily discovery plus deterministic abstract extraction")
    p.add_argument("--input",action="append",required=True); p.add_argument("--output",required=True); p.add_argument("--audit-output",required=True)
    p.add_argument("--max-records",type=int,default=5); p.add_argument("--max-results",type=int,default=3); p.add_argument("--max-query-attempts",type=int,default=2); p.add_argument("--max-fetches-per-record",type=int,default=3); p.add_argument("--timeout",type=float,default=30.0); p.add_argument("--api-key-file",default=str(DEFAULT_API_KEY_FILE)); p.add_argument("--dry-run",action="store_true"); p.add_argument("--force",action="store_true"); return p

def main(argv=None):
    args=parser().parse_args(argv)
    for name,value,ceiling in (("--max-records",args.max_records,MAX_RECORDS_CEILING),("--max-results",args.max_results,MAX_RESULTS_CEILING),("--max-query-attempts",args.max_query_attempts,MAX_QUERY_ATTEMPTS_CEILING),("--max-fetches-per-record",args.max_fetches_per_record,MAX_FETCHES_PER_RECORD_CEILING)):
        if not 1<=value<=ceiling: raise SystemExit(f"{name} must be between 1 and {ceiling}")
    if args.timeout<=0: raise SystemExit("--timeout must be positive")
    inputs=[Path(v).expanduser().resolve() for v in args.input]; output,audit=Path(args.output).expanduser(),Path(args.audit_output).expanduser()
    if not args.dry_run and not args.force and any(p.exists() for p in (output,audit)): print("error: Refusing to overwrite existing output(s); use --force if intentional",file=sys.stderr); return 2
    try: records,queries=load_and_rank_packs(inputs)
    except (OSError,ValueError,json.JSONDecodeError) as exc: print(f"error: {exc}",file=sys.stderr); return 2
    selected=[r for r in records if not has_abstract(r)][:args.max_records]
    if args.dry_run:
        maximum_searches=sum(min(len(build_queries(r)),args.max_query_attempts) for r in selected)
        print(f"Unique reconciled works: {len(records)}\nMissing abstracts selected: {len(selected)} (ceiling {MAX_RECORDS_CEILING})\nMaximum Tavily results per search: {args.max_results}\nMaximum search credits for this run: {maximum_searches}\nMaximum direct page fetches: {len(selected)*args.max_fetches_per_record}")
        for i,r in enumerate(selected,1):
            print(f"\n{i}. {r.get('title')}")
            for q in build_queries(r)[:args.max_query_attempts]: print(f"   Query: {q}")
        return 0
    key=load_api_key(Path(args.api_key_file).expanduser().resolve())
    if not key: print("error: Tavily API key not found",file=sys.stderr); return 2
    enriched,attempts=enrich_records(records,TavilyClient(key,args.timeout),args.max_records,args.max_results,max_query_attempts=args.max_query_attempts,max_fetches_per_record=args.max_fetches_per_record,fetcher=WebFetcher(args.timeout)); generated=datetime.now(timezone.utc).isoformat()
    credits=sum(int((s.get("usage") or {}).get("credits") or 0) for a in attempts for s in a.get("searches",[]))
    out={"source":"OpenAlex packs with bounded Tavily discovery and deterministic source extraction","input_files":[str(p) for p in inputs],"queries":queries,"count":len(enriched),"records":enriched,"tavily_enrichment":{"generated_at":generated,"attempted":len(attempts),"abstracts_added":sum(a["status"]=="abstract_added" for a in attempts),"reported_credits":credits}}
    aud={"generated_at":generated,"provider":"Tavily Search (discovery only)","endpoint":TAVILY_SEARCH_URL,"configuration":{"max_records":args.max_records,"max_results_per_search":args.max_results,"max_query_attempts":args.max_query_attempts,"max_fetches_per_record":args.max_fetches_per_record,"automatic_retries":0},"attempts":attempts}
    try: write_json(output,out,args.force); write_json(audit,aud,args.force)
    except OSError as exc: print(f"error: {exc}",file=sys.stderr); return 2
    print(f"Works attempted: {len(attempts)}\nTavily credits reported: {credits}\nAbstracts added: {out['tavily_enrichment']['abstracts_added']}\nEnriched pack: {args.output}\nAudit: {args.audit_output}"); return 0

if __name__=="__main__": raise SystemExit(main())
