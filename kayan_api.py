import os,json,uuid,urllib.request
from fastapi import FastAPI,Header,HTTPException,UploadFile,File
from fastapi.responses import HTMLResponse,Response
from fastapi.middleware.cors import CORSMiddleware
import psycopg
from psycopg.rows import dict_row
DB=os.environ["DATABASE_URL"]; KEY=os.environ["KAYAN_ACCESS_TOKEN"]; GROQ=os.getenv("GROQ_API_KEY","")
app=FastAPI(title="KAYAN Independent API",version="1.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
AGENTS=[{"id":"KAYAN","role":"Agente central e coordenador"},{"id":"PESQUISA","role":"Pesquisa e tendências"},{"id":"ESTRATEGIA","role":"Estratégia e campanhas"},{"id":"CRIACAO","role":"Roteiros, textos e conceitos visuais"},{"id":"QUALIDADE","role":"Revisão e verificação"},{"id":"OPERACOES","role":"Tarefas, arquivos e fluxos"}]
PANELS=["refrigeracao","modelo_ia","produtos_marketing"]
def conn(): return psycopg.connect(DB,row_factory=dict_row)
def auth(k):
 if k!=KEY: raise HTTPException(401,"Chave de acesso inválida")
@app.on_event("startup")
def init():
 with conn() as c:
  c.execute("CREATE TABLE IF NOT EXISTS kayan_tasks(id TEXT PRIMARY KEY,panel TEXT,title TEXT,input TEXT,result TEXT DEFAULT '',status TEXT DEFAULT 'created',created_at TIMESTAMPTZ DEFAULT now())")
  c.execute("CREATE TABLE IF NOT EXISTS kayan_messages(id BIGSERIAL PRIMARY KEY,role TEXT,content TEXT,panel TEXT,created_at TIMESTAMPTZ DEFAULT now())")
  c.execute("CREATE TABLE IF NOT EXISTS kayan_files(id TEXT PRIMARY KEY,name TEXT,mime_type TEXT,size_bytes BIGINT,data BYTEA,created_at TIMESTAMPTZ DEFAULT now())")
@app.get("/",response_class=HTMLResponse)
def home(): return open("kayan_index.html",encoding="utf-8").read()
@app.get("/health")
def health():
 try:
  with conn() as c:c.execute("SELECT 1")
  ok=True
 except Exception:ok=False
 return {"api":"online","database_connected":ok,"ai_configured":bool(GROQ),"provider":"Groq" if GROQ else None,"version":"1.0"}
@app.get("/api/agents")
def agents(x_api_key:str|None=Header(default=None)):auth(x_api_key);return {"central":"KAYAN","agents":AGENTS}
def ask(prompt):
 if not GROQ:return None
 body=json.dumps({"model":os.getenv("GROQ_MODEL","llama-3.3-70b-versatile"),"messages":[{"role":"system","content":"Você é KAYAN, agente central de inteligência. Coordene pesquisa, estratégia, criação, qualidade e operações. Responda em português brasileiro. Nunca invente fontes, métricas, publicações ou resultados."},{"role":"user","content":prompt}],"temperature":0.7}).encode()
 req=urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=body,headers={"Authorization":"Bearer "+GROQ,"Content-Type":"application/json"})
 with urllib.request.urlopen(req,timeout=45) as r:return json.loads(r.read())["choices"][0]["message"]["content"]
@app.post("/api/chat")
def chat(p:dict,x_api_key:str|None=Header(default=None)):
 auth(x_api_key);m=str(p.get("message","")).strip();panel=p.get("panel")
 if len(m)<2 or len(m)>10000:raise HTTPException(422,"Mensagem inválida")
 try:a=ask(m)
 except Exception as e:raise HTTPException(502,"Falha no provedor IA: "+type(e).__name__)
 if not a:a="KAYAN recebeu sua solicitação. O núcleo e o banco estão ativos, mas a IA generativa precisa de uma GROQ_API_KEY própria para responder de forma inteligente. Posso registrar e organizar operações enquanto isso."
 with conn() as c:
  c.execute("INSERT INTO kayan_messages(role,content,panel) VALUES('user',%s,%s)",(m,panel));c.execute("INSERT INTO kayan_messages(role,content,panel) VALUES('assistant',%s,%s)",(a,panel))
 return {"agent":"KAYAN","answer":a,"ai_live":bool(GROQ)}
@app.get("/api/chat/history")
def history(x_api_key:str|None=Header(default=None)):
 auth(x_api_key)
 with conn() as c:r=c.execute("SELECT role,content,panel,created_at FROM kayan_messages ORDER BY id DESC LIMIT 100").fetchall()
 return {"messages":list(reversed(r))}
@app.post("/api/tasks")
def task(p:dict,x_api_key:str|None=Header(default=None)):
 auth(x_api_key);panel=p.get("panel","refrigeracao")
 if panel not in PANELS:raise HTTPException(422,"Painel inválido")
 i=str(uuid.uuid4())
 with conn() as c:c.execute("INSERT INTO kayan_tasks(id,panel,title,input) VALUES(%s,%s,%s,%s)",(i,panel,str(p.get("title","Nova operação"))[:200],str(p.get("input",""))[:10000]))
 return {"id":i,"status":"created"}
@app.get("/api/tasks")
def tasks(x_api_key:str|None=Header(default=None)):
 auth(x_api_key)
 with conn() as c:r=c.execute("SELECT id,panel,title,input,status,created_at FROM kayan_tasks ORDER BY created_at DESC LIMIT 200").fetchall()
 return {"tasks":r}
@app.post("/api/files")
async def upload(file:UploadFile=File(...),x_api_key:str|None=Header(default=None)):
 auth(x_api_key);b=await file.read(10*1024*1024+1)
 if len(b)>10*1024*1024:raise HTTPException(413,"Limite de 10 MB por arquivo")
 i=str(uuid.uuid4())
 with conn() as c:c.execute("INSERT INTO kayan_files(id,name,mime_type,size_bytes,data) VALUES(%s,%s,%s,%s,%s)",(i,file.filename or "arquivo",file.content_type or "application/octet-stream",len(b),b))
 return {"id":i,"name":file.filename,"stored":"PostgreSQL"}
@app.get("/api/files")
def files(x_api_key:str|None=Header(default=None)):
 auth(x_api_key)
 with conn() as c:r=c.execute("SELECT id,name,mime_type,size_bytes,created_at FROM kayan_files ORDER BY created_at DESC LIMIT 200").fetchall()
 return {"files":r}
@app.get("/api/files/{i}")
def getfile(i:str,x_api_key:str|None=Header(default=None)):
 auth(x_api_key)
 with conn() as c:r=c.execute("SELECT name,mime_type,data FROM kayan_files WHERE id=%s",(i,)).fetchone()
 if not r:raise HTTPException(404,"Arquivo não encontrado")
 return Response(bytes(r["data"]),media_type=r["mime_type"],headers={"Content-Disposition":f'attachment; filename="{r["name"]}"'})
